"""Synchronize only an audited endpoint-transition snapshot to the thesis."""
import objective_experiment as exp
import objective_json_full as full
import objective_json_transition as transition
import objective_json_publish as publish
import objective_json_sync as sync


def add_once(path, needle, addition):
    text = path.read_text(encoding='utf8')
    if text.count(needle) != 1:
        raise ValueError('Expected one manuscript target: ' + str(path))
    path.write_text(text.replace(needle, needle + addition, 1), encoding='utf8', newline='\n')


def main():
    out = transition.OUT
    snap = out/'results/snapshot.json'
    audit = exp.read(out/'results/json_audit.json')
    if audit.get('status') != 'passed' or audit.get('snapshot_sha256') != exp.sha(snap):
        raise ValueError('Matching transition audit required')
    full.OUT = out
    publish.main()
    sync.main()
    root = exp.WORK/'graduation-thesis-materials'
    ms = root/'graduation-manuscript'
    add_once(ms/'docs/chap02_objective_results.tex',
        '生成失败按零分计入固定分母。',
        '8B运行期间原服务故障，649项出现连接中断或非JSON响应，另有7项中断后无终态回执；'
        '这些任务未盲目重发，依冻结规则计零。其余未发起任务在同模型的新端点续跑。'
        '因此8B的端到端得分包含服务故障影响，不可解释为正常部署下的纯模型能力。')
    add_once(ms/'docs/abstract.tex', '存在潜在材料暴露。', '8B服务故障造成大量任务计零，限制其结果解释。')
    add_once(ms/'docs/chap05.tex', '潜在暴露限制其结果解释。', '此外8B服务故障造成大量任务计零。')
    appendix = ms/'docs/appendix_ch02.tex'
    text = appendix.read_text(encoding='utf8').replace('objective_json_v2/full/', 'objective_json_v4/')
    appendix.write_text(text, encoding='utf8', newline='\n')
    add_once(root/'graduation-research/chapters/chapter02.md', '存在潜在暴露。',
        '8B服务故障导致649项连接或响应失败及7项未知终态，均保留计零，未发起任务在新端点续跑；结果不能单独解释为模型能力。')
    exp.save(out/'results/transition_publish_provenance.json', dict(snapshot_sha256=exp.sha(snap),
        thesis_sha256=exp.sha(ms/'docs/chap02_objective_results.tex'), audit_sha256=exp.sha(out/'results/json_audit.json')))
    print('Transition manuscript and caveats synchronized')


if __name__ == '__main__': main()
