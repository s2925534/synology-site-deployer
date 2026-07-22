from __future__ import annotations

from synology_site.scaffold.base import ScaffoldContext
from synology_site.scaffold.wordpress import WordPressScaffold


def context(
    db_mode: str = "external", wordpress_image_tag: str = "apache"
) -> ScaffoldContext:
    return ScaffoldContext(
        domain="demo.example.com",
        slug="demo-example-com",
        framework="wordpress",
        port=5051,
        project_path="/volume1/docker/demo-example-com",
        local_base_url_host="192.0.2.10",
        restart_policy="unless-stopped",
        db_enabled=True,
        db_mode=db_mode,
        db_name="demo_example_com",
        db_user="demo_example_com_user",
        db_password="user_password_1234567890",
        db_root_password="root_password_1234567890" if db_mode == "container" else None,
        wp_table_prefix="wp_",
        wordpress_image_tag=wordpress_image_tag,
    )


def generated_files(db_mode: str = "external") -> dict[str, str]:
    return {item.path: item.content for item in WordPressScaffold().generate(context(db_mode))}


def test_wordpress_scaffold_generates_expected_files() -> None:
    files = generated_files()

    assert sorted(files) == [
        ".synology-site.json",
        "app/.env",
        "app/Dockerfile",
        "app/db-health.php",
        "app/health.php",
        "docker-compose.yml",
        "docs/README.md",
    ]


def test_wordpress_env_has_native_wordpress_vars() -> None:
    env = generated_files()["app/.env"]

    assert "WORDPRESS_DB_HOST=shared-mariadb" in env
    assert "WORDPRESS_DB_NAME=demo_example_com" in env
    assert "WORDPRESS_DB_USER=demo_example_com_user" in env
    assert "WORDPRESS_DB_PASSWORD=user_password_1234567890" in env
    assert "WORDPRESS_TABLE_PREFIX=wp_" in env


def test_wordpress_compose_bind_mounts_wp_content_not_a_named_volume() -> None:
    compose = generated_files("external")["docker-compose.yml"]

    assert "./wp-content:/var/www/html/wp-content" in compose
    volumes_section = compose.split("\nvolumes:", 1)
    if len(volumes_section) > 1:
        assert "wp-content" not in volumes_section[1]


def test_wordpress_compose_container_mode_includes_db_service() -> None:
    compose = generated_files("container")["docker-compose.yml"]

    assert "demo-example-com-db" in compose or "MARIADB_DATABASE: demo_example_com" in compose
    assert "external: true" not in compose


def test_wordpress_compose_external_mode_joins_shared_network() -> None:
    compose = generated_files("external")["docker-compose.yml"]

    assert "shared-mariadb-network" in compose
    assert "external: true" in compose


def test_wordpress_dockerfile_reflects_image_tag() -> None:
    dockerfile = generated_files()["app/Dockerfile"]

    assert "FROM wordpress:apache" in dockerfile

    custom = {
        item.path: item.content
        for item in WordPressScaffold().generate(
            context("external", wordpress_image_tag="php8.3-apache")
        )
    }
    assert "FROM wordpress:php8.3-apache" in custom["app/Dockerfile"]


def test_wordpress_container_names_is_single_container() -> None:
    assert WordPressScaffold().container_names(context()) == ["demo-example-com"]
