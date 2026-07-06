from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, StrictUndefined

from synology_site.scaffold.base import GeneratedFile, ScaffoldContext, common_template_values


class FastAPIScaffold:
    framework = "fastapi"

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
            GeneratedFile("app/main.py", self._render("fastapi_app.py.j2", values)),
            GeneratedFile(
                "app/requirements.txt",
                self._render("fastapi_requirements.txt.j2", values),
            ),
            GeneratedFile("app/Dockerfile", self._render("fastapi_dockerfile.j2", values)),
            GeneratedFile("docker-compose.yml", self._render("compose.yml.j2", values)),
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
                    self._render("fastapi_database_docs.md.j2", values),
                    secret=True,
                )
            )
        return files_to_generate

    def container_names(self, context: ScaffoldContext) -> list[str]:
        return [context.slug]

    def _render(self, template_name: str, values: dict[str, object]) -> str:
        template_text = self.template_root.joinpath(template_name).read_text(encoding="utf-8")
        return self.env.from_string(template_text).render(**values).rstrip() + "\n"

    def _values(self, context: ScaffoldContext) -> dict[str, object]:
        return common_template_values(context, internal_port=8000)
