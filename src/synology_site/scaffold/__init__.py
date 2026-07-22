from __future__ import annotations

from synology_site.errors import SynologySiteError
from synology_site.scaffold.base import DECOUPLED_SPA_FRONTENDS, FRONTENDS
from synology_site.scaffold.fastapi import FastAPIScaffold
from synology_site.scaffold.flask import FlaskScaffold
from synology_site.scaffold.laravel import LaravelScaffold
from synology_site.scaffold.nextjs import NextJsScaffold
from synology_site.scaffold.wordpress import WordPressScaffold

FRAMEWORKS = {
    "flask": FlaskScaffold(),
    "laravel": LaravelScaffold(),
    "fastapi": FastAPIScaffold(),
    "nextjs": NextJsScaffold(),
    "wordpress": WordPressScaffold(),
}


def validate_wordpress_db_mode(framework: str, db_mode: str) -> None:
    if framework == "wordpress" and db_mode not in {"container", "external"}:
        msg = (
            "--framework wordpress requires --db-mode container or external "
            "(WordPress always needs a database)"
        )
        raise SynologySiteError(msg)


def validate_frontend(framework: str, frontend: str, php_server: str) -> None:
    if frontend not in FRONTENDS:
        msg = f"Unsupported frontend: {frontend}"
        raise SynologySiteError(msg)
    if frontend == "none":
        return
    if framework != "laravel":
        msg = "--frontend is only applicable to --framework laravel"
        raise SynologySiteError(msg)
    if frontend in DECOUPLED_SPA_FRONTENDS and php_server != "fpm-nginx":
        msg = (
            f"--frontend {frontend} requires --php-server fpm-nginx "
            "(nginx serves the built SPA and proxies /api to PHP-FPM)"
        )
        raise SynologySiteError(msg)


# "artisan" is Laravel's single-process dev server (php artisan serve) -- simplest, matches the
# one-container-per-site model, but not meant for production traffic. "fpm-nginx" is the
# production-grade topology: PHP-FPM + nginx in two containers behind the same published port.
PHP_SERVER_OPTIONS = {"artisan", "fpm-nginx"}
PRODUCTION_PHP_SERVERS = {"fpm-nginx"}


def validate_php_server(framework: str, php_server: str) -> None:
    if php_server not in PHP_SERVER_OPTIONS:
        msg = f"Unsupported --php-server: {php_server}"
        raise SynologySiteError(msg)
    if php_server != "artisan" and framework != "laravel":
        msg = "--php-server is only applicable to --framework laravel"
        raise SynologySiteError(msg)
