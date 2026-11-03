"""Create a post-hoc review note bound to the audited review snapshot."""
from pathlib import Path
import objective_experiment as exp
import objective_review as review

def main():
    snap_path=review.REVIEW/'results/snapshot.json';snap=exp.read(snap_path)
    if snap['status']!='closed' or snap['total']!=172 or snap['model_verdicts'].get('invalid')!=15 or snap['followup_counts'].get('expert_review_recommended')!=2:
        raise ValueError('unexpected review snapshot')
    note=(r'\paragraph{事后来源复核}'+'\n'
      '在正式实验结束后，经研究者授权，将172道题的题干、选项、评分侧答案及原文上下文发送至超算Qwen3-8B进行AI复核。'
      '模型标记157题有效、15题存在疑点；该模型与原实验8B同源，不能据此估计题目准确率或替代独立人工审核。'
      '对15条疑点进行AI辅助原文跟进，13条的现有原文支持原答案，另有OBJ-116的细化措辞和OBJ-170的边界通量表述建议领域专家核查。'
      '这些跟进不是人工裁决，冻结题库、原始回答和得分均未改动。由于答案已在实验结束后发送给该服务，后续同服务评价应考虑潜在材料暴露。\n')
    target=exp.WORK/'graduation-thesis-materials/graduation-manuscript/docs/chap02_objective_review.tex'
    target.write_text(note,encoding='utf8',newline='\n')
    exp.save(review.REVIEW/'analysis/manuscript_provenance.json',dict(snapshot_sha256=exp.sha(snap_path),
        note_sha256=exp.sha(target),code_sha256=exp.sha(Path(__file__))))
    print('post-hoc manuscript note generated')
if __name__=='__main__':main()
