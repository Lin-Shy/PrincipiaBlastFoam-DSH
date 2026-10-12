import importlib.util
from pathlib import Path
import sys


MODULE = Path(__file__).parents[1] / "experiments/retrieval_method/leaderboard_review.py"
sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location("leaderboard_review_credentials", MODULE)
assert SPEC and SPEC.loader
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def test_read_secret_supports_project_settings_file(tmp_path):
    settings = tmp_path / "llm-setting.txt"
    settings.write_text("API_KEY = secret-value\nmodel = deepseek-flash\n")
    assert review.read_secret(None, settings) == "secret-value"


def test_read_secret_rejects_two_sources(tmp_path):
    key = tmp_path / "key"
    settings = tmp_path / "settings"
    key.write_text("a")
    settings.write_text("API_KEY=b")
    try:
        review.read_secret(key, settings)
    except ValueError as error:
        assert "either" in str(error)
    else:
        raise AssertionError("two credential sources accepted")
