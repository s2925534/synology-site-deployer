from __future__ import annotations

from synology_site.lightsail.discovery import run_lightsail_discovery
from synology_site.ssh_client import RemoteCommandResult


class FakeSSH:
    def __init__(self, responses: dict[str, tuple[int, str]] | None = None) -> None:
        self.responses = responses or {}
        self.commands: list[str] = []

    def run(
        self, command: str, *, check: bool = False, timeout: int | None = None
    ) -> RemoteCommandResult:
        del check, timeout
        self.commands.append(command)
        exit_code, stdout = self.responses.get(command, (1, ""))
        return RemoteCommandResult(command, exit_code, stdout, "")


NGINX_CONF = """
server {
    server_name veloso.dev www.veloso.dev;
    root /var/www/html/veloso.dev/public;
}
"""

WP_CONFIG = """
define('DB_NAME', 'veloso_wp');
define('DB_USER', 'veloso_user');
define('DB_PASSWORD', 'super-secret');
define('DB_HOST', 'localhost');
"""


def test_run_lightsail_discovery_full_happy_path() -> None:
    doc_root = "/var/www/html/veloso.dev/public"
    fake = FakeSSH(
        {
            "test -d /opt/bitnami/wordpress": (1, ""),
            "grep -Rl veloso.dev /etc/nginx/sites-enabled /etc/nginx/sites-available 2>/dev/null": (
                0,
                "/etc/nginx/sites-enabled/veloso.dev\n",
            ),
            "cat /etc/nginx/sites-enabled/veloso.dev": (0, NGINX_CONF),
            "grep -h server_name /etc/nginx/sites-enabled/* 2>/dev/null": (
                0,
                "server_name veloso.dev www.veloso.dev;\nserver_name gumtree.dev;\n",
            ),
            "php -v": (0, "PHP 8.3.14 (cli) (built: ...)\n"),
            "command -v wp": (1, ""),
            f"cat {doc_root}/wp-includes/version.php 2>/dev/null": (
                0,
                "$wp_version = '6.5.2';\n",
            ),
            f"cat {doc_root}/wp-config.php 2>/dev/null": (0, WP_CONFIG),
            f"ls -1 {doc_root}/wp-content/plugins 2>/dev/null": (
                0,
                "akismet\nelementor\njetpack\n",
            ),
            f"ls -1 {doc_root}/wp-content/themes 2>/dev/null": (0, "twentytwentyfour\n"),
            f"du -sh {doc_root}/wp-content/uploads 2>/dev/null": (
                0,
                f"159M\t{doc_root}/wp-content/uploads\n",
            ),
            "crontab -l 2>/dev/null": (0, "# comment\n15 2 * * * /usr/bin/true\n"),
        }
    )

    result = run_lightsail_discovery(fake, "veloso.dev")

    assert result.is_bitnami is False
    assert result.nginx_config_path == "/etc/nginx/sites-enabled/veloso.dev"
    assert result.doc_root == doc_root
    assert result.other_server_names_on_box == ("gumtree.dev",)
    assert result.php_version == "8.3"
    assert result.wp_cli_present is False
    assert result.wordpress_version == "6.5.2"
    assert result.db_config is not None
    assert result.db_config.db_name == "veloso_wp"
    assert result.db_config.db_user == "veloso_user"
    assert result.db_config.db_host == "localhost"
    assert result.db_config.password_defined is True
    assert result.plugins == ("akismet", "elementor", "jetpack")
    assert result.themes == ("twentytwentyfour",)
    assert result.s3_offload_plugins == ()
    assert result.uploads_size and "159M" in result.uploads_size
    assert result.crontab_entries == ("15 2 * * * /usr/bin/true",)


def test_run_lightsail_discovery_detects_s3_offload_plugin() -> None:
    doc_root = "/var/www/html/example/public"
    grep_nginx = (
        "grep -Rl example.com /etc/nginx/sites-enabled /etc/nginx/sites-available 2>/dev/null"
    )
    fake = FakeSSH(
        {
            "test -d /opt/bitnami/wordpress": (1, ""),
            grep_nginx: (
                0,
                "/etc/nginx/sites-available/example.com\n",
            ),
            "cat /etc/nginx/sites-available/example.com": (
                0,
                f"server {{ server_name example.com; root {doc_root}; }}",
            ),
            "grep -h server_name /etc/nginx/sites-enabled/* 2>/dev/null": (0, ""),
            "php -v": (0, "PHP 8.1.2\n"),
            "command -v wp": (0, "/usr/local/bin/wp\n"),
            f"cat {doc_root}/wp-includes/version.php 2>/dev/null": (0, ""),
            f"cat {doc_root}/wp-config.php 2>/dev/null": (0, ""),
            f"ls -1 {doc_root}/wp-content/plugins 2>/dev/null": (
                0,
                "amazon-s3-and-cloudfront\nakismet\n",
            ),
            f"ls -1 {doc_root}/wp-content/themes 2>/dev/null": (0, ""),
            f"du -sh {doc_root}/wp-content/uploads 2>/dev/null": (0, ""),
            "crontab -l 2>/dev/null": (0, ""),
        }
    )

    result = run_lightsail_discovery(fake, "example.com")

    assert result.wp_cli_present is True
    assert result.s3_offload_plugins == ("amazon-s3-and-cloudfront",)
    assert result.db_config is None
    assert result.uploads_size is None


def test_run_lightsail_discovery_handles_missing_nginx_config_gracefully() -> None:
    grep_nginx = (
        "grep -Rl unknown.example /etc/nginx/sites-enabled /etc/nginx/sites-available 2>/dev/null"
    )
    fake = FakeSSH(
        {
            "test -d /opt/bitnami/wordpress": (1, ""),
            grep_nginx: (
                1,
                "",
            ),
            "grep -h server_name /etc/nginx/sites-enabled/* 2>/dev/null": (0, ""),
            "php -v": (1, ""),
            "/opt/bitnami/php/bin/php -v": (1, ""),
            "command -v wp": (1, ""),
            "crontab -l 2>/dev/null": (0, ""),
        }
    )

    result = run_lightsail_discovery(fake, "unknown.example")

    assert result.nginx_config_path is None
    assert result.doc_root is None
    assert result.php_version is None
    assert result.plugins == ()
    assert result.db_config is None
