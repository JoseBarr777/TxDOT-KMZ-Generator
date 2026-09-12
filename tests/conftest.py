import sys
from pathlib import Path

import pytest

# Allow `import txdot_overlay` without an editable install in CI-like environments.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from txdot_overlay.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def config():
    return load_config()
