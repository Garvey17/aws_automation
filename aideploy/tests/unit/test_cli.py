"""Unit tests for AIDeploy CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from aideploy.cli.main import app
from aideploy.config.loader import load_config
from aideploy.constants import CONFIG_FILE
from aideploy.deployment.deployer import DeploymentResult
from aideploy.deployment.destroyer import DestructionResult
from aideploy.state.manager import DeploymentState, StateManager

runner = CliRunner()


@pytest.mark.unit
class TestCLIInit:
    """Tests for `aideploy init` command."""

    def test_init_success(self, sample_fastapi_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(sample_fastapi_project)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "FastAPI project detected" in result.output
        assert "Generated aideploy.yaml" in result.output
        assert (sample_fastapi_project / CONFIG_FILE).exists()
        assert (sample_fastapi_project / "Dockerfile").exists()

        config = load_config(sample_fastapi_project)
        assert config.app.entrypoint == "app.main:app"

    def test_init_non_fastapi_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 1
        assert "FastAPI project not detected" in result.output

    def test_init_already_exists_fails_without_force(
        self, sample_fastapi_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(sample_fastapi_project)
        (sample_fastapi_project / CONFIG_FILE).write_text("name: test\n", encoding="utf-8")
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 1
        assert "Found existing aideploy.yaml" in result.output


@pytest.mark.unit
class TestCLIUp:
    """Tests for `aideploy up` command."""

    @patch("aideploy.cli.main.Deployer.run")
    def test_up_success(
        self,
        mock_run: MagicMock,
        sample_fastapi_project: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(sample_fastapi_project)
        mock_run.return_value = DeploymentResult(
            project="test-api",
            deployment_id="dep-123",
            endpoint="https://xyz.awsapprunner.com",
            status="SUCCESS",
            region="us-east-1",
        )

        result = runner.invoke(app, ["up"])
        assert result.exit_code == 0
        assert "Deployment successful." in result.output
        assert "https://xyz.awsapprunner.com" in result.output


@pytest.mark.unit
class TestCLIDown:
    """Tests for `aideploy down` command."""

    @patch("aideploy.cli.main.destroy_deployment")
    def test_down_with_yes_flag(
        self,
        mock_destroy: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_deployment_state: DeploymentState,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        state_mgr = StateManager(tmp_path)
        state_mgr.save(sample_deployment_state)

        mock_destroy.return_value = DestructionResult(
            project="test-api",
            deployment_id="dep-123",
            destroyed_resources=["App Runner Service", "ECR Repository", "IAM Role"],
            success=True,
        )

        result = runner.invoke(app, ["down", "--yes"])
        assert result.exit_code == 0
        assert "Cleanup complete" in result.output

    def test_down_when_not_deployed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["down", "--yes"])
        assert result.exit_code == 0
        assert "No active deployment found" in result.output


@pytest.mark.unit
class TestCLIStatus:
    """Tests for `aideploy status` command."""

    def test_status_not_deployed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "NOT DEPLOYED" in result.output

    def test_status_running(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_deployment_state: DeploymentState,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        state_mgr = StateManager(tmp_path)
        state_mgr.save(sample_deployment_state)

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "RUNNING" in result.output
        assert "https://xyz123.awsapprunner.com" in result.output
        assert "test-api" in result.output


@pytest.mark.unit
class TestCLILogs:
    """Tests for `aideploy logs` command."""

    @patch("aideploy.cli.main.get_app_runner_logs")
    @patch("aideploy.cli.main.get_aws_session")
    def test_logs_retrieval(
        self,
        mock_sess: MagicMock,
        mock_logs: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_deployment_state: DeploymentState,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        state_mgr = StateManager(tmp_path)
        state_mgr.save(sample_deployment_state)

        mock_logs.return_value = ["INFO: Uvicorn running on http://0.0.0.0:8000", "INFO: Application startup complete."]

        result = runner.invoke(app, ["logs"])
        assert result.exit_code == 0
        assert "Application startup complete" in result.output
