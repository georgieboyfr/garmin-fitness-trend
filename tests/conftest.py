import pytest

from app.config import Config


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path / "data")
