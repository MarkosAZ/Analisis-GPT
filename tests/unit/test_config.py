from pathlib import Path

import pytest

from sports_analysis.config import ConfigurationError, Secret, Settings


def test_secret_values_are_explicit_and_not_in_configuration_repr() -> None:
    password = "private-password"
    value = "postgresql://" + f"worker:{password}@localhost/sports"
    settings = Settings.from_env({"DATABASE_URL": value})
    assert settings.database_url is not None
    assert settings.database_url.reveal() == value
    assert "private-password" not in repr(settings)
    assert "private-password" not in repr(settings.database_url)
    assert "private-password" not in str(settings.database_url)
    assert str(Secret("value")) == "<redacted>"


def test_local_workflows_need_no_database_credentials() -> None:
    settings = Settings.from_env({})
    assert settings.database_url is None
    assert settings.object_root == Path(".local/object-storage")


@pytest.mark.parametrize(
    "value",
    [
        "invalid-private-value",
        "https://secret@example.com/db",
        "postgresql://" + "user:secret@host:bad/db",
        "postgresql://" + "user:secret@[invalid/db",
    ],
)
def test_invalid_database_configuration_never_echoes_values(value: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({"DATABASE_URL": value})
    assert value not in str(error.value)
    assert "secret" not in str(error.value)


def test_storage_config_rejects_credential_bearing_urls() -> None:
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({"SPORTS_OBJECT_ROOT": "https://user:secret@host/bucket"})
    assert "secret" not in str(error.value)
