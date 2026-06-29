import json

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.flask import FlaskScaffold


def context(db_enabled: bool = False) -> ScaffoldContext:
    return ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="flask",
        port=5051,
        project_path="/volume1/docker/demo-example-com",
        local_base_url_host="192.0.2.10",
        restart_policy="unless-stopped",
        db_enabled=db_enabled,
        db_mode="container" if db_enabled else "none",
    )


def generated_files(db_enabled: bool = False) -> dict[str, str]:
    return {item.path: item.content for item in FlaskScaffold().generate(context(db_enabled))}


def test_flask_scaffold_without_db_generates_expected_files() -> None:
    files = generated_files()

    assert sorted(files) == [
        ".synology-site.json",
        "app/Dockerfile",
        "app/app.py",
        "app/requirements.txt",
        "docker-compose.yml",
        "docs/README.md",
    ]


def test_flask_public_page_is_minimal() -> None:
    app_py = generated_files()["app/app.py"]

    assert "It works" in app_py
    assert "demo.example.com is running successfully" in app_py
    assert "/volume1/docker" not in app_py
    assert "192.0.2.10" not in app_py
    assert "DATABASE_URL" not in app_py


def test_flask_scaffold_without_db_excludes_db_route_and_dependencies() -> None:
    files = generated_files()

    assert "/db-health" not in files["app/app.py"]
    assert "SQLAlchemy" not in files["app/requirements.txt"]
    assert "PyMySQL" not in files["app/requirements.txt"]
    assert "Flask" in files["app/requirements.txt"]
    assert "gunicorn" in files["app/requirements.txt"]


def test_marker_json_without_db() -> None:
    marker = json.loads(generated_files()[".synology-site.json"])

    assert marker["tool"] == "synology-site-deployer"
    assert marker["domain"] == "demo.example.com"
    assert marker["slug"] == "demo-example-com"
    assert marker["port"] == 5051
    assert marker["database"] == {"enabled": False, "mode": "none"}
    assert marker["cloudflare"]["manual_required"] is True
