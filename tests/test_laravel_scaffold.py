import json

import pytest
import yaml

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.laravel import LaravelScaffold


def context(
    db_enabled: bool = False,
    php_server: str = "artisan",
    frontend: str = "none",
    redis_enabled: bool = False,
    queue_enabled: bool = False,
) -> ScaffoldContext:
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
        frontend=frontend,
        redis_enabled=redis_enabled,
        queue_enabled=queue_enabled,
    )


def generated_files(
    db_enabled: bool = False,
    php_server: str = "artisan",
    frontend: str = "none",
    redis_enabled: bool = False,
    queue_enabled: bool = False,
) -> dict[str, str]:
    return {
        item.path: item.content
        for item in LaravelScaffold().generate(
            context(db_enabled, php_server, frontend, redis_enabled, queue_enabled)
        )
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


def test_livewire_frontend_adds_package_no_frontend_build_stage() -> None:
    dockerfile = generated_files(frontend="livewire")["app/Dockerfile"]

    assert "composer require --no-interaction livewire/livewire" in dockerfile
    assert "npm" not in dockerfile


def test_inertia_vue_frontend_uses_breeze_and_builds_assets() -> None:
    dockerfile = generated_files(frontend="inertia-vue")["app/Dockerfile"]

    assert "composer require --no-interaction laravel/breeze --dev" in dockerfile
    assert "breeze:install vue --no-interaction" in dockerfile
    assert "apk add --no-cache nodejs npm" in dockerfile
    assert "npm ci && npm run build" in dockerfile


def test_inertia_react_frontend_uses_breeze_react_stack() -> None:
    dockerfile = generated_files(frontend="inertia-react")["app/Dockerfile"]

    assert "breeze:install react --no-interaction" in dockerfile


@pytest.mark.parametrize("frontend", ["vue", "react", "angular"])
def test_decoupled_spa_frontends_add_frontend_build_stage_and_api_backend(
    frontend: str,
) -> None:
    files = generated_files(php_server="fpm-nginx", frontend=frontend)
    dockerfile = files["app/Dockerfile"]

    assert "breeze:install api --no-interaction" in dockerfile
    assert "FROM node:20-alpine AS frontend-build" in dockerfile
    assert "COPY --from=frontend-build /frontend-dist /usr/share/nginx/html" in dockerfile
    assert "COPY --from=build /app/public /usr/share/nginx/html" not in dockerfile

    nginx_conf = files["app/nginx.conf"]
    assert "location ~ ^/(api|health|db-health)" in nginx_conf
    assert "try_files $uri $uri/ /index.html" in nginx_conf


def test_decoupled_spa_vue_uses_vite_scaffold() -> None:
    dockerfile = generated_files(php_server="fpm-nginx", frontend="vue")["app/Dockerfile"]

    assert "npm create vite@latest . -- --template vue" in dockerfile


def test_decoupled_spa_react_uses_vite_scaffold() -> None:
    dockerfile = generated_files(php_server="fpm-nginx", frontend="react")["app/Dockerfile"]

    assert "npm create vite@latest . -- --template react" in dockerfile


def test_decoupled_spa_angular_uses_angular_cli() -> None:
    dockerfile = generated_files(php_server="fpm-nginx", frontend="angular")["app/Dockerfile"]

    assert "npm install -g @angular/cli" in dockerfile
    assert "ng new ." in dockerfile


def test_non_decoupled_frontends_keep_serving_laravel_public_via_nginx() -> None:
    for frontend in ("none", "livewire", "inertia-vue", "inertia-react"):
        dockerfile = generated_files(php_server="fpm-nginx", frontend=frontend)["app/Dockerfile"]
        assert "COPY --from=build /app/public /usr/share/nginx/html" in dockerfile
        assert "frontend-build" not in dockerfile


def test_redis_disabled_by_default_uses_file_session_and_cache() -> None:
    env = generated_files()["app/.env"]

    assert "SESSION_DRIVER=file" in env
    assert "CACHE_STORE=file" in env
    assert "QUEUE_CONNECTION=sync" in env
    assert "REDIS_HOST" not in env


def test_redis_enabled_switches_drivers_and_adds_extension() -> None:
    files = generated_files(redis_enabled=True)

    env = files["app/.env"]
    assert "SESSION_DRIVER=redis" in env
    assert "CACHE_STORE=redis" in env
    assert "QUEUE_CONNECTION=redis" in env
    assert "REDIS_HOST=demo-example-com-redis" in env

    assert "install-php-extensions pdo_mysql pdo_sqlite mbstring redis" in files["app/Dockerfile"]


def test_redis_enabled_adds_independent_compose_service() -> None:
    compose = yaml.safe_load(generated_files(redis_enabled=True)["docker-compose.yml"])

    assert "demo-example-com-redis" in compose["services"]
    redis_service = compose["services"]["demo-example-com-redis"]
    assert redis_service["image"] == "redis:7-alpine"
    assert redis_service["volumes"] == ["demo-example-com-redis-data:/data"]
    assert "demo-example-com-db" not in compose["services"]


def test_redis_and_db_both_enabled_coexist() -> None:
    compose = yaml.safe_load(
        generated_files(db_enabled=True, redis_enabled=True)["docker-compose.yml"]
    )

    assert {"demo-example-com", "demo-example-com-db", "demo-example-com-redis"} == set(
        compose["services"]
    )
    app_depends_on = compose["services"]["demo-example-com"]["depends_on"]
    assert app_depends_on["demo-example-com-db"]["condition"] == "service_healthy"
    assert app_depends_on["demo-example-com-redis"]["condition"] == "service_healthy"


def test_redis_with_fpm_nginx_topology() -> None:
    compose = yaml.safe_load(
        generated_files(php_server="fpm-nginx", redis_enabled=True)["docker-compose.yml"]
    )

    assert sorted(compose["services"]) == [
        "demo-example-com",
        "demo-example-com-redis",
        "demo-example-com-web",
    ]


def test_queue_worker_disabled_by_default() -> None:
    compose = yaml.safe_load(generated_files(redis_enabled=True)["docker-compose.yml"])

    assert "demo-example-com-queue" not in compose["services"]


def test_queue_worker_adds_service_depending_on_redis() -> None:
    compose = yaml.safe_load(
        generated_files(redis_enabled=True, queue_enabled=True)["docker-compose.yml"]
    )

    queue_service = compose["services"]["demo-example-com-queue"]
    assert queue_service["command"] == [
        "php",
        "artisan",
        "queue:work",
        "--sleep=3",
        "--tries=3",
        "--max-time=3600",
    ]
    assert queue_service["depends_on"] == {
        "demo-example-com-redis": {"condition": "service_healthy"}
    }


def test_queue_worker_also_depends_on_db_when_both_enabled() -> None:
    compose = yaml.safe_load(
        generated_files(db_enabled=True, redis_enabled=True, queue_enabled=True)[
            "docker-compose.yml"
        ]
    )

    queue_depends_on = compose["services"]["demo-example-com-queue"]["depends_on"]
    assert queue_depends_on["demo-example-com-db"]["condition"] == "service_healthy"
    assert queue_depends_on["demo-example-com-redis"]["condition"] == "service_healthy"


def test_queue_worker_with_fpm_nginx_uses_php_fpm_target() -> None:
    compose = yaml.safe_load(
        generated_files(php_server="fpm-nginx", redis_enabled=True, queue_enabled=True)[
            "docker-compose.yml"
        ]
    )

    assert compose["services"]["demo-example-com-queue"]["build"]["target"] == "php-fpm"


def test_queue_worker_container_name_included_in_container_names() -> None:
    names = LaravelScaffold().container_names(
        context(redis_enabled=True, queue_enabled=True)
    )

    assert names == ["demo-example-com", "demo-example-com-queue"]
