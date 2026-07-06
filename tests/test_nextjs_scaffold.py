import json

import yaml

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.nextjs import NextJsScaffold


def context(db_enabled: bool = False) -> ScaffoldContext:
    return ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="nextjs",
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
    return {item.path: item.content for item in NextJsScaffold().generate(context(db_enabled))}


def test_nextjs_scaffold_without_db_generates_expected_files() -> None:
    files = generated_files()

    assert sorted(files) == [
        ".synology-site.json",
        "app/Dockerfile",
        "app/health-route.js",
        "docker-compose.yml",
        "docs/README.md",
    ]


def test_nextjs_dockerfile_scaffolds_real_create_next_app() -> None:
    dockerfile = generated_files()["app/Dockerfile"]

    assert "create-next-app@latest" in dockerfile
    assert "npm run build" in dockerfile
    assert '["npm", "start"]' in dockerfile
    assert "EXPOSE 3000" in dockerfile


def test_nextjs_health_route_is_minimal() -> None:
    health_route = generated_files()["app/health-route.js"]

    assert "demo-example-com" in health_route
    assert "demo.example.com" in health_route
    assert "nextjs" in health_route
    assert "/volume1/docker" not in health_route


def test_nextjs_scaffold_without_db_excludes_db_route_and_env() -> None:
    files = generated_files()

    assert "app/db-health-route.js" not in files
    assert "app/.env" not in files
    assert "docs/DATABASE.md" not in files
    assert "mysql2" not in files["app/Dockerfile"]


def test_nextjs_scaffold_with_db_includes_db_route_and_env() -> None:
    files = generated_files(db_enabled=True)

    assert "mysql2" in files["app/db-health-route.js"]
    assert "DATABASE_URL=mysql://demo_example_com_user:user_password_1234567890@" in files[
        "app/.env"
    ]
    assert "npm install mysql2" in files["app/Dockerfile"]
    assert "docs/DATABASE.md" in files


def test_nextjs_database_docs_contains_credentials() -> None:
    files = generated_files(db_enabled=True)

    assert "user_password_1234567890" in files["docs/DATABASE.md"]
    assert "root_password_1234567890" in files["docs/DATABASE.md"]
    assert "Next.js" in files["docs/DATABASE.md"]


def test_nextjs_project_readme_does_not_contain_credentials() -> None:
    files = generated_files(db_enabled=True)

    assert "user_password_1234567890" not in files["docs/README.md"]
    assert "root_password_1234567890" not in files["docs/README.md"]


def test_nextjs_marker_json_reports_framework() -> None:
    marker = json.loads(generated_files()[".synology-site.json"])

    assert marker["framework"] == "nextjs"
    assert marker["database"] == {"enabled": False, "mode": "none"}


def test_nextjs_compose_uses_internal_port_3000() -> None:
    compose = yaml.safe_load(generated_files()["docker-compose.yml"])

    service = compose["services"]["demo-example-com"]
    assert service["ports"] == ["5051:3000"]


def test_nextjs_compose_with_db_matches_flask_topology() -> None:
    compose = yaml.safe_load(generated_files(db_enabled=True)["docker-compose.yml"])

    app_service = compose["services"]["demo-example-com"]
    db_service = compose["services"]["demo-example-com-db"]
    assert app_service["depends_on"]["demo-example-com-db"]["condition"] == "service_healthy"
    assert db_service["image"] == "mariadb:11"
