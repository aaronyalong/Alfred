from pathlib import Path

import pytest

from alfred.config import Settings


@pytest.fixture(autouse=True)
def no_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test in an empty directory so a developer's real .env is never read."""
    monkeypatch.chdir(tmp_path)


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    monkeypatch.setenv("ALFRED_MODEL", "claude-haiku-5-5")

    settings = Settings()

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "test-key-123"
    assert settings.alfred_model == "claude-haiku-5-5"


def test_api_key_is_masked_when_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")

    settings = Settings()

    assert "test-key-123" not in repr(settings)
    assert "test-key-123" not in str(settings.model_dump())


def test_defaults_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ALFRED_MODEL", raising=False)

    settings = Settings()

    assert settings.anthropic_api_key is None
    assert settings.alfred_model == "claude-opus-5-5"
