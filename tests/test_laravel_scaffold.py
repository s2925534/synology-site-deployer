import json

import yaml

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.laravel import LaravelScaffold


def context(db_enabled: bool = False, php_server: str = "artisan") -> ScaffoldContext:
    return ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="laravel",
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
        php_server=php_server,
    )


def generated_files(db_enabled: bool = False, php_server: str = "artisan") -> dict[str, str]:
    return {
        item.path: item.content
        for item in LaravelScaffold().generate(context(db_enabled, php_server))
    }


def test_laravel_scaffold_without_db_generates_expected_files() -> None:
    files = generated_files()

    assert sorted(files) == [
        ".synology-site.json",
        "app/.env",
        "app/Dockerfile",
        "app/routes-extra.php",
        "docker-compose.yml",
        "docs/README.md",
    ]


def test_laravel_dockerfile_builds_a_real_laravel_project() -> None:
    dockerfile = generated_files()["app/Dockerfile"]

    assert "composer create-project" in dockerfile
    assert "laravel/laravel" in dockerfile
    assert '"php", "artisan", "serve"' in dockerfile
    assert "8000" in dockerfile


def test_laravel_scaffold_without_db_uses_sqlite_and_excludes_db_route() -> None:
    files = generated_files()

    assert "DB_CONNECTION=sqlite" in files["app/.env"]
    assert "/db-health" not in files["app/routes-extra.php"]
    assert "docs/DATABASE.md" not in files


def test_laravel_scaffold_with_db_includes_db_route_and_env() -> None:
    files = generated_files(db_enabled=True)

    assert "/db-health" in files["app/routes-extra.php"]
    assert "DB_CONNECTION=mysql" in files["app/.env"]
    assert "DB_HOST=demo-example-com-db" in files["app/.env"]
    assert "docs/DATABASE.md" in files


def test_laravel_database_docs_contains_credentials() -> None:
    files = generated_files(db_enabled=True)

    assert "user_password_1234567890" in files["docs/DATABASE.md"]
    assert "root_password_1234567890" in files["docs/DATABASE.md"]


def test_laravel_project_readme_does_not_contain_credentials() -> None:
    files = generated_files(db_enabled=True)

    assert "user_password_1234567890" not in files["docs/README.md"]
    assert "root_password_1234567890" not in files["docs/README.md"]


def test_laravel_marker_json_reports_framework() -> None:
    marker = json.loads(generated_files()[".synology-site.json"])

    assert marker["framework"] == "laravel"
    assert marker["database"] == {"enabled": False, "mode": "none"}


def test_laravel_compose_uses_internal_port_8000() -> None:
    compose = yaml.safe_load(generated_files()["docker-compose.yml"])

    service = compose["services"]["demo-example-com"]
    assert service["ports"] == ["5051:8000"]


def test_laravel_compose_with_db_matches_flask_topology() -> None:
    compose = yaml.safe_load(generated_files(db_enabled=True)["docker-compose.yml"])

    app_service = compose["services"]["demo-example-com"]
    db_service = compose["services"]["demo-example-com-db"]
    assert app_service["depends_on"]["demo-example-com-db"]["condition"] == "service_healthy"
    assert db_service["image"] == "mariadb:11"


def test_laravel_fpm_nginx_generates_two_container_topology() -> None:
    files = generated_files(php_server="fpm-nginx")

    assert sorted(files) == [
        ".synology-site.json",
        "app/.env",
        "app/Dockerfile",
        "app/nginx.conf",
        "app/routes-extra.php",
        "docker-compose.yml",
        "docs/README.md",
    ]

    dockerfile = files["app/Dockerfile"]
    assert "FROM php:8.3-fpm AS php-fpm" in dockerfile
    assert "FROM nginx:alpine AS nginx" in dockerfile
    assert '"php", "artisan", "serve"' not in dockerfile

    compose = yaml.safe_load(files["docker-compose.yml"])
    assert sorted(compose["services"]) == ["demo-example-com", "demo-example-com-web"]
    assert compose["services"]["demo-example-com"]["build"]["target"] == "php-fpm"
    assert compose["services"]["demo-example-com-web"]["build"]["target"] == "nginx"
    assert compose["services"]["demo-example-com-web"]["ports"] == ["5051:80"]
    assert "ports" not in compose["services"]["demo-example-com"]

    assert "demo-example-com:9000" in files["app/nginx.conf"]


def test_laravel_fpm_nginx_container_names_include_web_container() -> None:
    names = LaravelScaffold().container_names(context(php_server="fpm-nginx"))

    assert names == ["demo-example-com", "demo-example-com-web"]


def test_laravel_artisan_container_names_is_single_container() -> None:
    names = LaravelScaffold().container_names(context())

    assert names == ["demo-example-com"]


def test_laravel_fpm_nginx_with_db_joins_both_app_services_to_default_network() -> None:
    compose = yaml.safe_load(
        generated_files(db_enabled=True, php_server="fpm-nginx")["docker-compose.yml"]
    )

    app_service = compose["services"]["demo-example-com"]
    web_service = compose["services"]["demo-example-com-web"]
    db_service = compose["services"]["demo-example-com-db"]
    assert set(app_service["networks"]) == {"demo-example-com-network", "default"}
    assert web_service["networks"] == ["default"]
    assert db_service["networks"] == ["demo-example-com-network"]
