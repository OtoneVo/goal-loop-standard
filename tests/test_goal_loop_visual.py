"""pytest から図の構図契約を収集するための薄いラッパ。

実体は同ディレクトリの `validate_goal_loop_visual.py`。
pytest は `test_*.py` しか収集しないため、このファイルが無いと図の検証が
CI から丸ごと抜け落ちる。ロジックはここに持たせない。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_goal_loop_visual import main as validate_visual  # noqa: E402


def test_goal_loop_visual() -> None:
    validate_visual()


if __name__ == "__main__":
    validate_visual()
