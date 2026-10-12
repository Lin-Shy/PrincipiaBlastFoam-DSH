import importlib.util
from pathlib import Path
import sys


MODULE = Path(__file__).parents[1] / "experiments/retrieval_method/natural_index_free_leaderboard.py"
sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location("natural_index_free_leaderboard", MODULE)
assert SPEC and SPEC.loader
leaderboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(leaderboard)


def test_read_secret_supports_project_settings_file(tmp_path):
    settings = tmp_path / "llm-setting.txt"
    settings.write_text("API_KEY = secret-value\nmodel = deepseek-flash\n")
    assert leaderboard.read_secret(None, settings) == "secret-value"


def test_read_secret_rejects_two_credential_sources(tmp_path):
    first = tmp_path / "key"
    second = tmp_path / "settings"
    first.write_text("a")
    second.write_text("API_KEY=b")
    try:
        leaderboard.read_secret(first, second)
    except ValueError as error:
        assert "either" in str(error)
    else:
        raise AssertionError("two credential sources accepted")
