"""Publish a closed, audited post-hoc failure-recovery snapshot."""
import objective_experiment as exp
import objective_json_full as full
import objective_json_failure_rerun as run
import objective_json_publish as publish
import objective_json_sync as sync


def append_after(path, needle, addition):
    text=path.read_text(encoding='utf8')
    if text.count(needle)!=1:raise ValueError('Expected unique text in '+str(path))
    path.write_text(text.replace(needle,needle+addition,1),encoding='utf8',newline='\n')


def main():
    out=run.OUT;snap=out/'results/snapshot.json';audit=exp.read(out/'results/json_audit.json')
    if audit['status']!='passed' or audit['snapshot_sha256']!=exp.sha(snap):raise ValueError('Matching audit required')
    full.OUT=out;publish.main();sync.main()
    root=exp.WORK/'graduation-thesis-materials';ms=root/'graduation-manuscript'
    recovered=audit['rerun_answered'];valid=audit['rerun_format_valid'];total=audit['rerun']
    caveat=(f'原批次有{total}项生成失败，经研究者明确要求后每项补试一次；补试获得{recovered}份回答，其中{valid}份格式有效。'
            '原始失败、服务故障和未知回执均保留，部分旧请求是否曾被服务接受无法确认。'
            '结果属于按失败状态选择的事后恢复，不等同于预注册的单次运行或独立未见测试。')
    append_after(ms/'docs/chap02_objective_results.tex','生成失败按零分计入固定分母。',caveat)
    append_after(ms/'docs/abstract.tex','存在潜在材料暴露。',f'原{total}项生成失败经授权各补试一次，结果为事后恢复口径。')
    abstract=ms/'docs/abstract.tex';text=abstract.read_text(encoding='utf8')
    text=text.replace('Some facts recur; expert review is pending and prior answer exposure limits 8B inference.',
        'Some facts recur; expert review is pending. Failed generations received one post-hoc retry; prior answer exposure limits 8B inference.')
    abstract.write_text(text,encoding='utf8',newline='\n')
    append_after(ms/'docs/chap05.tex','潜在暴露限制其结果解释。',f'原{total}项生成失败各补试一次，结果采用事后恢复口径。')
    appendix=ms/'docs/appendix_ch02.tex';text=appendix.read_text(encoding='utf8').replace('objective_json_v2/full/','objective_json_v5_failure_rerun/')
    appendix.write_text(text,encoding='utf8',newline='\n')
    research=root/'graduation-research/chapters/chapter02.md'
    append_after(research,'存在潜在暴露。',f'原{total}项生成失败按用户要求各补试一次，结果属于事后恢复口径；未知回执仍有重复调用不确定性。')
    exp.save(out/'results/publish_final.json',dict(snapshot_sha256=exp.sha(snap),audit_sha256=exp.sha(out/'results/json_audit.json'),
        manuscript_sha256=exp.sha(ms/'docs/chap02_objective_results.tex'),recovered_answers=recovered))
    print('Post-hoc failure recovery manuscript synchronized')


if __name__=='__main__':main()
