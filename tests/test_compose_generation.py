import yaml

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.flask import FlaskScaffold


def generated_files() -> dict[str, str]:
    context = ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="flask",
        port=5051,
        project_path="/volume1/docker/demo-example-com",
        local_base_url_host="192.0.2.10",
        restart_policy="unless-stopped",
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
