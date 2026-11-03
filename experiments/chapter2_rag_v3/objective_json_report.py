"""Report a JSON run without mutating the historical scorer module."""
import sys
from types import ModuleType
import objective_experiment as experiment
import objective_json_full as full
import objective_json_strict as strict


def main():
    full.use_full()
    adapter = ModuleType('objective_scoring')
    adapter.score = strict.score
    sys.modules['objective_scoring'] = adapter
    experiment.report()
    page = full.OUT / 'results/index.html'
    html = page.read_text(encoding='utf-8').replace(
        'href="../../results/index.html"', 'href="../../../results/index.html"')
    incident = full.OUT / 'service_incident_20261103.json'
    if incident.exists():
        html = html.replace('<h1>第2章客观题实验</h1>',
            '<h1>第2章客观题实验</h1><p><strong>8B服务发生过故障；'
            '请结合故障记录和最新运行状态解读进度，不能假定未决请求已安全恢复。</strong> '
            '<a href="../service_incident_20261103.json">故障记录</a></p>')
    page.write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
