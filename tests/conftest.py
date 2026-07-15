import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point OVERNIGHT_HOME at a temp dir so tests never touch ~/.overnight."""
    monkeypatch.setenv("OVERNIGHT_HOME", str(tmp_path / "overnight"))
    return tmp_path
