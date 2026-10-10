from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_public_ci_has_no_secrets_or_untrusted_write_permissions() -> None:
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    for path in workflows:
        text = path.read_text()
        data = yaml.safe_load(text)
        assert "pull_request_target" not in data["on"]
        assert data["permissions"] == {"contents": "read"}
        assert "secrets." not in text
        assert "upload-artifact" not in text
        for job in data["jobs"].values():
            assert "permissions" not in job or job["permissions"] == {"contents": "read"}
            for step in job["steps"]:
                if "uses" in step:
                    _, revision = step["uses"].rsplit("@", 1)
                    assert len(revision) == 40
                    assert all(c in "0123456789abcdef" for c in revision)


def test_test_database_is_mandatory_in_ci() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    data = yaml.safe_load(text)
    assert data["jobs"]["validate"]["env"]["TEST_DATABASE_URL"]
    assert "postgres" in data["jobs"]["validate"]["services"]


def test_source_conversation_ignored_and_package_allowlisted() -> None:
    import tomllib

    patterns = (ROOT / ".gitignore").read_text().splitlines()
    assert "Analizar mercados deportivos.html" in patterns
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"] == [
        "src/",
        "migrations/",
        "config/",
        "pyproject.toml",
        "README.md",
    ]


def test_extension_package_is_deterministic_and_contains_only_assets(tmp_path) -> None:
    from zipfile import ZipFile

    from scripts.package_extension import ASSETS, build

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build(first)
    build(second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert set(archive.namelist()) == set(ASSETS)
        assert "Analizar mercados deportivos.html" not in archive.namelist()
        assert not any(name.startswith("sports-capture-") for name in archive.namelist())
