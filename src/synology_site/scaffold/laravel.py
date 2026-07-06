from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, StrictUndefined

from synology_site.scaffold.base import (
    DECOUPLED_SPA_FRONTENDS,
    GeneratedFile,
    ScaffoldContext,
    common_template_values,
)


class LaravelScaffold:
    framework = "laravel"

    def __init__(self) -> None:
        template_root = files("synology_site.scaffold.templates")
        self.env = Environment(
            loader=None,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )
        self.template_root = template_root

    def generate(self, context: ScaffoldContext) -> list[GeneratedFile]:
        values = self._values(context)
        production = context.php_server == "fpm-nginx"
        files_to_generate = [
            GeneratedFile(
                "app/Dockerfile",
                self._render(
                    "laravel_fpm_dockerfile.j2" if production else "laravel_dockerfile.j2", values
                ),
            ),
            GeneratedFile(
                "app/routes-extra.php", self._render("laravel_health_routes.php.j2", values)
            ),
            GeneratedFile("app/.env", self._render("laravel_env.j2", values), secret=True),
            GeneratedFile(
                "docker-compose.yml",
                self._render(
                    "laravel_fpm_compose.yml.j2" if production else "compose.yml.j2", values
                ),
            ),
            GeneratedFile("docs/README.md", self._render("project_readme.md.j2", values)),
            GeneratedFile(".synology-site.json", self._render("marker.json.j2", values)),
        ]
        if production:
            spa = context.frontend in DECOUPLED_SPA_FRONTENDS
            nginx_template = "laravel_spa_nginx_conf.j2" if spa else "laravel_nginx_conf.j2"
            files_to_generate.append(
                GeneratedFile("app/nginx.conf", self._render(nginx_template, values))
            )
        if context.db_enabled:
            files_to_generate.append(
                GeneratedFile(
                    "docs/DATABASE.md",
                    self._render("laravel_database_docs.md.j2", values),
                    secret=True,
                )
            )
        return files_to_generate

    def container_names(self, context: ScaffoldContext) -> list[str]:
        names = (
            [context.slug, f"{context.slug}-web"]
            if context.php_server == "fpm-nginx"
            else [context.slug]
        )
        if context.queue_enabled:
            names.append(f"{context.slug}-queue")
        return names

    def _render(self, template_name: str, values: dict[str, object]) -> str:
        template_text = self.template_root.joinpath(template_name).read_text(encoding="utf-8")
        return self.env.from_string(template_text).render(**values).rstrip() + "\n"

    def _values(self, context: ScaffoldContext) -> dict[str, object]:
        values = common_template_values(context, internal_port=8000)
        values["frontend"] = context.frontend
        return values
