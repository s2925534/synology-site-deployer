from typer.testing import CliRunner

from synology_site.cli import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Synology" in result.output
    assert "health" in result.output
    assert "update" in result.output
    assert "bootstrap-n8n" in result.output
    assert "bootstrap-umami" in result.output
    assert "bootstrap-vaultwarden" in result.output
    assert "backup-plan" in result.output
    assert "doctor" in result.output
    assert "restart-all" in result.output
