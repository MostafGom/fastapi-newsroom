from typer.testing import CliRunner

from newsroom import cli
from newsroom.core.config import Environment, Settings


def test_seed_refuses_to_run_in_production(monkeypatch) -> None:
    production = Settings(environment=Environment.PRODUCTION)
    monkeypatch.setattr(cli, "get_settings", lambda: production)

    async def must_not_run(*_args: object) -> list[str]:
        raise AssertionError("demo data was seeded in production")

    monkeypatch.setattr(cli, "seed_demo", must_not_run)
    result = CliRunner().invoke(cli.app, ["seed"])
    assert result.exit_code == 1
    assert "newsroom bootstrap" in result.output


def test_bootstrap_is_offered_without_demo_data() -> None:
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "bootstrap" in result.output
