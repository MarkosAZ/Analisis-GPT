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
        is_pages = path.name == "pages.yml"
        if is_pages:
            assert set(data["on"]) == {"push", "workflow_dispatch"}
            assert data["on"]["push"]["branches"] == ["main"]
        for job_name, job in data["jobs"].items():
            if is_pages:
                assert "github.ref == 'refs/heads/main'" in job["if"]
                assert "github.event.repository.fork == false" in job["if"]
            if is_pages and job_name == "deploy":
                assert job["permissions"] == {"pages": "write", "id-token": "write"}
            else:
                assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}
            for step in job["steps"]:
                if "uses" in step:
                    _, revision = step["uses"].rsplit("@", 1)
                    assert len(revision) == 40
                    assert all(c in "0123456789abcdef" for c in revision)
                    if "upload-pages-artifact" in step["uses"]:
                        assert is_pages and job_name == "build"
                        assert step["with"]["path"] == ".local/pages"
        if is_pages:
            assert data["jobs"]["deploy"]["needs"] == "build"
            assert data["jobs"]["deploy"]["environment"]["name"] == "github-pages"


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
