import ast
import json

import yaml

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.fastapi import FastAPIScaffold


def context(db_enabled: bool = False) -> ScaffoldContext:
    return ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="fastapi",
        port=5051,
        project_path="/volume1/docker/demo-example-com",
        local_base_url_host="192.0.2.10",
        restart_policy="unless-stopped",
        db_enabled=db_enabled,
        db_mode="container" if db_enabled else "none",
        db_name="demo_example_com",
        db_user="demo_example_com_user",
        db_password="user_password_1234567890",
        db_root_password="root_password_1234567890",
    )


def generated_files(db_enabled: bool = False) -> dict[str, str]:
    return {item.path: item.content for item in FastAPIScaffold().generate(context(db_enabled))}


def test_fastapi_scaffold_without_db_generates_expected_files() -> None:
    files = generated_files()

    assert sorted(files) == [
        ".synology-site.json",
        "app/Dockerfile",
        "app/main.py",
        "app/requirements.txt",
        "docker-compose.yml",
        "docs/README.md",
    ]


def test_fastapi_public_page_is_minimal_and_valid_python() -> None:
    main_py = generated_files()["app/main.py"]

    assert "It works" in main_py
    assert "demo.example.com is running successfully" in main_py
    assert "/volume1/docker" not in main_py
    assert "192.0.2.10" not in main_py
    assert "DATABASE_URL" not in main_py
    ast.parse(main_py)


def test_fastapi_scaffold_without_db_excludes_db_route_and_dependencies() -> None:
    files = generated_files()

    assert "/db-health" not in files["app/main.py"]
    assert "SQLAlchemy" not in files["app/requirements.txt"]
    assert "PyMySQL" not in files["app/requirements.txt"]
    assert "fastapi" in files["app/requirements.txt"]
    assert "uvicorn" in files["app/requirements.txt"]
    assert "gunicorn" in files["app/requirements.txt"]


def test_fastapi_dockerfile_runs_gunicorn_with_uvicorn_workers() -> None:
    dockerfile = generated_files()["app/Dockerfile"]

    assert "gunicorn" in dockerfile
    assert "uvicorn.workers.UvicornWorker" in dockerfile
    assert "8000" in dockerfile


def test_fastapi_scaffold_with_db_includes_db_route_and_dependencies() -> None:
    files = generated_files(db_enabled=True)

    main_py = files["app/main.py"]
    assert "/db-health" in main_py
    ast.parse(main_py)
    assert "SQLAlchemy" in files["app/requirements.txt"]
    assert "PyMySQL" in files["app/requirements.txt"]
    assert "DATABASE_URL" in files["app/.env"]
    assert "docs/DATABASE.md" in files


def test_fastapi_database_docs_contains_credentials() -> None:
    files = generated_files(db_enabled=True)

    assert "user_password_1234567890" in files["docs/DATABASE.md"]
    assert "root_password_1234567890" in files["docs/DATABASE.md"]
    assert "FastAPI" in files["docs/DATABASE.md"]


def test_fastapi_project_readme_does_not_contain_credentials() -> None:
    files = generated_files(db_enabled=True)

    assert "user_password_1234567890" not in files["docs/README.md"]
    assert "root_password_1234567890" not in files["docs/README.md"]


def test_fastapi_marker_json_reports_framework() -> None:
    marker = json.loads(generated_files()[".synology-site.json"])

    assert marker["framework"] == "fastapi"
    assert marker["database"] == {"enabled": False, "mode": "none"}


def test_fastapi_compose_uses_internal_port_8000() -> None:
    compose = yaml.safe_load(generated_files()["docker-compose.yml"])

    service = compose["services"]["demo-example-com"]
    assert service["ports"] == ["5051:8000"]


def test_fastapi_compose_with_db_matches_flask_topology() -> None:
    compose = yaml.safe_load(generated_files(db_enabled=True)["docker-compose.yml"])

    app_service = compose["services"]["demo-example-com"]
    db_service = compose["services"]["demo-example-com-db"]
    assert app_service["depends_on"]["demo-example-com-db"]["condition"] == "service_healthy"
    assert db_service["image"] == "mariadb:11"
