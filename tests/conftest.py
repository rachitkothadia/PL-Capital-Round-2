from pathlib import Path

import pytest

from pl_capital.config import Settings
from pl_capital.database import initialize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path):
    value = Settings(ROOT, tmp_path, "test-key", graph_backend="off")
    initialize(value.data_root, value.db_path)
    return value


@pytest.fixture
def db_path(settings):
    return settings.db_path
