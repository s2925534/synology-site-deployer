from typer.testing import CliRunner

from synology_site.cli import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Synology" in result.output
