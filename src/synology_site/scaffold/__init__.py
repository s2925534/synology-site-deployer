from __future__ import annotations

from synology_site.errors import SynologySiteError
from synology_site.scaffold.flask import FlaskScaffold
from synology_site.scaffold.laravel import LaravelScaffold

FRAMEWORKS = {
    "flask": FlaskScaffold(),
    "laravel": LaravelScaffold(),
}

# Recognized in the CLI but not implemented yet -- see docs/laravel-scaffold-options.md for the
# design rationale (Inertia vs. a fully decoupled SPA vs. Livewire).
PLANNED_FRONTENDS = {"vue", "react", "angular", "inertia-vue", "inertia-react", "livewire"}


def validate_frontend(frontend: str) -> None:
    if frontend == "none":
        return
    if frontend in PLANNED_FRONTENDS:
        msg = (
            f"--frontend {frontend} is planned but not implemented yet. "
            "See docs/laravel-scaffold-options.md for the roadmap."
        )
        raise SynologySiteError(msg)
    msg = f"Unsupported frontend: {frontend}"
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
