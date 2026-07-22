from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, StrictUndefined

from synology_site.scaffold.base import GeneratedFile, ScaffoldContext, common_template_values


class WordPressScaffold:
    framework = "wordpress"

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
        return [
            GeneratedFile("app/Dockerfile", self._render("wordpress_dockerfile.j2", values)),
            GeneratedFile("app/health.php", self._render("wordpress_health.php.j2", values)),
            GeneratedFile(
                "app/db-health.php", self._render("wordpress_db_health.php.j2", values)
            ),
            GeneratedFile("app/.env", self._render("wordpress_env.j2", values), secret=True),
            GeneratedFile(
                "docker-compose.yml", self._render("wordpress_compose.yml.j2", values)
            ),
            GeneratedFile("docs/README.md", self._render("project_readme.md.j2", values)),
            GeneratedFile(".synology-site.json", self._render("marker.json.j2", values)),
        ]

    def container_names(self, context: ScaffoldContext) -> list[str]:
        return [context.slug]

    def _render(self, template_name: str, values: dict[str, object]) -> str:
        template_text = self.template_root.joinpath(template_name).read_text(encoding="utf-8")
        return self.env.from_string(template_text).render(**values).rstrip() + "\n"

    def _values(self, context: ScaffoldContext) -> dict[str, object]:
        return common_template_values(context, internal_port=80)
