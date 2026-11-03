"""Render the transition snapshot with explicit service-incident context."""
import objective_json_transition as transition


def main():
    transition.report()
    page = transition.OUT/'results/index.html'
    text = page.read_text(encoding='utf8')
    text = text.replace('<h1>第2章客观题实验</h1>',
        '<h1>第2章客观题实验</h1><p><strong>8B原服务故障，产生649项连接中断或非JSON响应；'
        '另有7项中断请求无终态回执。上述失败保留并计入固定分母，不能将成绩当作正常服务下的纯模型能力。'
        '新地址仅运行原本未发起的任务，结果合并时保留部署身份。</strong> '
        '<a href="../../objective_json_v2/full/service_incident_20261103.json">故障记录</a></p>')
    page.write_text(text, encoding='utf8')


if __name__ == '__main__': main()
