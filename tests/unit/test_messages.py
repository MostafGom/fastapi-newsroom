import json
from pathlib import Path

MESSAGES = Path(__file__).resolve().parents[2] / "src" / "newsroom" / "messages"


def test_ui_catalogs_have_the_same_keys() -> None:
    english = json.loads((MESSAGES / "en.json").read_text(encoding="utf-8"))
    arabic = json.loads((MESSAGES / "ar.json").read_text(encoding="utf-8"))
    assert set(english) == set(arabic)
