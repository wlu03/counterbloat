import pytest

from backend.db import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_DIR", str(tmp_path / "objects"))
    return Store("sqlite://")
