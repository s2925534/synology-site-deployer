import yaml

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.flask import FlaskScaffold


def generated_files(
    db_enabled: bool = False,
    db_publish_port: bool = False,
    db_mode: str | None = None,
    redis_enabled: bool = False,
) -> dict[str, str]:
    resolved_db_mode = db_mode if db_mode is not None else ("container" if db_enabled else "none")
    context = ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="flask",
        port=5051,
        project_path="/volume1/docker/demo-example-com",
        local_base_url_host="192.0.2.10",
        restart_policy="unless-stopped",
        db_enabled=db_enabled or resolved_db_mode != "none",
        db_mode=resolved_db_mode,
        db_name="demo_example_com",
        db_user="demo_example_com_user",
        db_password="user_password_1234567890",
        db_root_password="root_password_1234567890",
        db_publish_port=db_publish_port,
        db_host_port=3307 if db_publish_port else None,
        redis_enabled=redis_enabled,
    )
    return {item.path: item.content for item in FlaskScaffold().generate(context)}


def test_docker_compose_without_db() -> None:
    compose = yaml.safe_load(generated_files()["docker-compose.yml"])

    service = compose["services"]["demo-example-com"]
    assert service["build"]["context"] == "./app"
    assert service["container_name"] == "demo-example-com"
    assert service["restart"] == "unless-stopped"
    assert service["ports"] == ["5051:5000"]
    assert "demo-example-com-db" not in compose["services"]
    assert "volumes" not in compose
    assert "networks" not in compose


def test_mariadb_port_not_published_without_db() -> None:
    compose = yaml.safe_load(generated_files()["docker-compose.yml"])

    assert "demo-example-com-db" not in compose["services"]


def test_docker_compose_with_db() -> None:
    compose = yaml.safe_load(generated_files(db_enabled=True)["docker-compose.yml"])

    app = compose["services"]["demo-example-com"]
    db = compose["services"]["demo-example-com-db"]
    assert app["depends_on"]["demo-example-com-db"]["condition"] == "service_healthy"
    assert app["networks"] == ["demo-example-com-network"]
    assert db["image"] == "mariadb:11"
    assert db["restart"] == "unless-stopped"
    assert db["environment"]["MARIADB_DATABASE"] == "demo_example_com"
    assert db["volumes"] == ["demo-example-com-db-data:/var/lib/mysql"]
    assert db["networks"] == ["demo-example-com-network"]
    assert "healthcheck" in db
    assert "demo-example-com-db-data" in compose["volumes"]
    assert "demo-example-com-network" in compose["networks"]


def test_mariadb_port_not_published_by_default() -> None:
    compose = yaml.safe_load(generated_files(db_enabled=True)["docker-compose.yml"])

    assert "ports" not in compose["services"]["demo-example-com-db"]


def test_mariadb_port_published_only_when_explicitly_enabled() -> None:
    compose = yaml.safe_load(
        generated_files(db_enabled=True, db_publish_port=True)["docker-compose.yml"]
    )

    assert compose["services"]["demo-example-com-db"]["ports"] == ["3307:3306"]


def test_external_db_mode_has_no_dedicated_db_service() -> None:
    compose = yaml.safe_load(generated_files(db_mode="external")["docker-compose.yml"])

    assert "demo-example-com-db" not in compose["services"]
    assert "volumes" not in compose


def test_external_db_mode_joins_shared_network_only() -> None:
    compose = yaml.safe_load(generated_files(db_mode="external")["docker-compose.yml"])

    app = compose["services"]["demo-example-com"]
    assert app["networks"] == ["shared-mariadb-network"]
    assert "depends_on" not in app
    assert compose["networks"]["shared-mariadb-network"]["external"] is True
    assert "demo-example-com-network" not in compose["networks"]


def test_external_db_mode_app_env_points_at_shared_container() -> None:
    files = generated_files(db_mode="external")

    assert "DB_HOST=shared-mariadb" in files["app/.env"]
    assert "DB_NAME=demo_example_com" in files["app/.env"]
