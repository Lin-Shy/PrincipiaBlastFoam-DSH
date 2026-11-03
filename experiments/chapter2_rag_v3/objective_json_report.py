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
    page.write_text(page.read_text(encoding='utf-8').replace(
        'href="../../results/index.html"', 'href="../../../results/index.html"'), encoding='utf-8')


if __name__ == '__main__':
    main()
