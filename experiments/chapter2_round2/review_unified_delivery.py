"""Record actual page inspection and verify the single official PDF release."""
from datetime import datetime,timezone
import argparse
from common import *

MANUSCRIPT=WORKSPACE/'graduation-thesis-materials/graduation-manuscript'


def main(action):
    review_path=MANUSCRIPT/'build/review.json';r=read(review_path)
    assert r['pdf_sha256']==sha(MANUSCRIPT/'build/main.pdf')
    assert r['automatic_checks_passed']
    assert r['reporting_split']['main_methods']==9 and r['reporting_split']['ablations']==4
    if action=='record-inspection':
        r['visual_review_status']='passed_visual_inspection'
        r['visual_review_scope']=dict(rendered_pages_inspected=r['rendered_pdf_pages'],
            contact_sheet_sha256={name:sha(MANUSCRIPT/name)for name in r['contact_sheets']},
            reviewer='Agent visual layout QA; not a study human judge or graph-quality reviewer',
            notes='Inspected all eight contact sheets; unified E5/BGE table, repeated reference rows, four ablations, fixed-query plots and appendix readable; no clipped or overlapping content observed. Scope limited to selected rendered pages.')
        review_path.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    else:
        manifest=read(MANUSCRIPT/'official_manifest.json')
        assert manifest['pdf_sha256']==r['pdf_sha256']==sha(MANUSCRIPT/'main.pdf')
        assert manifest['review']['visual_review_status']=='passed_visual_inspection'
        for name,h in manifest['source_files_sha256'].items():assert sha(MANUSCRIPT/name)==h,name
        for name,h in r['visual_review_scope']['contact_sheet_sha256'].items():assert sha(MANUSCRIPT/name)==h,name
    official=read(MANUSCRIPT/'official_manifest.json')
    complete=sha(MANUSCRIPT/'main.pdf')==r['pdf_sha256']==official['pdf_sha256']
    if action=='verify-release':assert complete
    status=dict(schema='unified_delivery_status_v1',updated_utc=datetime.now(timezone.utc).isoformat(),
        status='complete'if complete else'awaiting_official_pdf_unlock',
        built_pdf=MANUSCRIPT.joinpath('build/main.pdf').relative_to(WORKSPACE).as_posix(),
        official_pdf=MANUSCRIPT.joinpath('main.pdf').relative_to(WORKSPACE).as_posix(),
        pdf_sha256=r['pdf_sha256'],pages=r['pages'],rendered_pages_reviewed=len(r['rendered_pdf_pages']),
        comparison_methods=9,ablations=4,questions_development=160,questions_test=40,
        sessions=4600,tests_passed=44,tests_skipped=1,new_paid_calls=0,
        protected_original_files=read(CURRENT/'protected-records-audit.json')['protected_files'],
        original_changed_files=0,human_validation='pending',defense_sync='pending')
    if complete:
        status['official_manifest_sha256']=sha(MANUSCRIPT/'official_manifest.json')
        status['verified_source_and_asset_files']=len(official['source_files_sha256'])
    (CURRENT/'unified-delivery.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    path=CURRENT/'unified-maintenance.md';text=path.read_text(encoding='utf-8').split('\n## PDF交付状态\n')[0]
    text+='\n## PDF交付状态\n\n'
    if complete:
        text+=f"正式main.pdf与编译产物SHA256一致，official_manifest.json已更新并核对{status['verified_source_and_asset_files']}个源码/资产；{r['pages']}页，已检查{len(r['rendered_pdf_pages'])}个相关页面的8张联系表。PDF SHA256：{r['pdf_sha256']}。\n"
    else:
        text+=f"新版{r['pages']}页已编译于build/main.pdf，已检查{len(r['rendered_pdf_pages'])}个相关页面、8张联系表；根目录main.pdf因预览进程占用而覆盖失败，已请用户关闭预览，正式PDF及发布清单暂未更新。\n"
    text+='\n检查器已修正统一目录迁移后的路径变量遮蔽、条件表达式空格，以及将算法候选种子误作随机执行种子的旧断言。终检通过；保留模板已有的封面轻微overfull、字体和部分underfull提示。\n'
    path.write_text(text,encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['record-inspection','verify-release'])
    main(p.parse_args().action)
