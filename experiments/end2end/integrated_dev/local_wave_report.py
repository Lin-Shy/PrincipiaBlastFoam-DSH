"""Refresh the effective task results without dispatching any runs."""
import json
import runpy
from b11_live import batch


def summarize():
    runpy.run_path(str(batch / 'refresh.py'))
    tasks = json.loads((batch / 'task_states.json').read_bytes())
    return [
        dict(id=task, arm=arm, state=entry['execution'], verdict=entry['achieved'],
             receipt=entry['run_evidence'], delivery=entry['submission'], cost=entry['cost'])
        for task, record in tasks.items() if record['scope'] == '本地读出与采集'
        for arm, entry in record['actual'].items()
    ]


if __name__ == '__main__':
    summarize()
