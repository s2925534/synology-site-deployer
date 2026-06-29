from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, StrictUndefined

from synology_site import __version__
from synology_site.database.naming import database_name, database_user
from synology_site.naming import db_container_name, db_volume_name, network_name
from synology_site.scaffold.base import GeneratedFile, ScaffoldContext


class FlaskScaffold:
    framework = "flask"

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
        files_to_generate = [
            GeneratedFile("app/app.py", self._render("flask_app.py.j2", values)),
            GeneratedFile(
                "app/requirements.txt",
                self._render("flask_requirements.txt.j2", values),
            ),
            GeneratedFile("app/Dockerfile", self._render("flask_dockerfile.j2", values)),
            GeneratedFile("docker-compose.yml", self._render("flask_compose.yml.j2", values)),
            GeneratedFile("docs/README.md", self._render("project_readme.md.j2", values)),
            GeneratedFile(".synology-site.json", self._render("marker.json.j2", values)),
        ]
        if context.db_enabled:
            files_to_generate.append(
                GeneratedFile("app/.env", self._render("app_env.j2", values), secret=True)
            )
            files_to_generate.append(
                GeneratedFile(
                    "docs/DATABASE.md",
                    self._render("database_docs.md.j2", values),
                    secret=True,
                )
            )
        return files_to_generate

    def _render(self, template_name: str, values: dict[str, object]) -> str:
        template_text = self.template_root.joinpath(template_name).read_text(encoding="utf-8")
        return self.env.from_string(template_text).render(**values).rstrip() + "\n"

    def _values(self, context: ScaffoldContext) -> dict[str, object]:
        db_name = context.db_name or database_name(context.domain)
        db_user = context.db_user or database_user(context.domain)
        db_container = db_container_name(context.domain)
        return {
            "version": __version__,
            "domain": context.domain,
            "slug": context.slug,
            "framework": context.framework,
            "port": context.port,
            "project_path": context.project_path,
            "local_base_url_host": context.local_base_url_host,
            "local_url": f"http://{context.local_base_url_host}:{context.port}",
            "public_url": f"https://{context.domain}",
            "restart_policy": context.restart_policy,
            "db_enabled": context.db_enabled,
            "db_mode": context.db_mode,
            "db_type": context.db_type,
            "db_image": context.db_image,
            "db_container": db_container,
            "db_name": db_name,
            "db_user": db_user,
            "db_password": context.db_password or "",
            "db_root_password": context.db_root_password or "",
            "db_volume": db_volume_name(context.domain),
            "db_network": network_name(context.domain),
            "db_publish_port": context.db_publish_port,
            "db_host_port": context.db_host_port,
            "cloudflare_attempted": context.cloudflare_attempted,
            "cloudflare_configured": context.cloudflare_configured,
            "cloudflare_manual_required": context.cloudflare_manual_required,
        }
