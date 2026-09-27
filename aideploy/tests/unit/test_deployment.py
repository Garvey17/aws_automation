"""Unit tests for deployment orchestrator, planner, and destroyer."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aideploy.config.loader import write_config
from aideploy.config.schema import AideployConfig, AppConfig, CostConfig
from aideploy.deployment.deployer import Deployer
from aideploy.deployment.destroyer import destroy_deployment, plan_destruction
from aideploy.deployment.planner import create_deployment_plan, generate_deployment_id
from aideploy.exceptions import ConfigError, DetectionError, StateNotFoundError
from aideploy.state.manager import DeploymentState, StateManager


@pytest.mark.unit
class TestDeploymentPlanner:
    """Tests for deployment planner."""

    def test_generate_deployment_id_format(self) -> None:
        dep_id = generate_deployment_id()
        assert dep_id.startswith("dep-")
        parts = dep_id.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD

    def test_create_deployment_plan_resolves_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_config: AideployConfig,
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-12345")
        monkeypatch.setenv("DB_URL", "postgresql://user:pass@host/db")

        plan = create_deployment_plan(sample_config)
        assert plan.project_name == "test-api"
        assert plan.environment_variables["OPENAI_API_KEY"] == "sk-mock-12345"
        assert plan.environment_variables["DB_URL"] == "postgresql://user:pass@host/db"
        assert plan.cost_plan.allowed is True

    def test_create_deployment_plan_missing_env_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_config: AideployConfig,
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DB_URL", raising=False)

        with pytest.raises(ConfigError) as exc_info:
            create_deployment_plan(sample_config)
        assert "OPENAI_API_KEY" in str(exc_info.value)


@pytest.mark.unit
class TestDeploymentLifecycle:
    """Tests for Deployer lifecycle execution."""

    @patch("aideploy.deployment.deployer.check_health")
    @patch("aideploy.deployment.deployer.wait_for_app_runner_service")
    @patch("aideploy.deployment.deployer.create_or_update_app_runner_service")
    @patch("aideploy.deployment.deployer.push_image_to_ecr")
    @patch("aideploy.deployment.deployer.ensure_ecr_repository")
    @patch("aideploy.deployment.deployer.ensure_app_runner_ecr_role")
    @patch("aideploy.deployment.deployer.build_image")
    @patch("aideploy.deployment.deployer.check_docker_available")
    @patch("aideploy.deployment.deployer.verify_credentials")
    @patch("aideploy.deployment.deployer.get_aws_session")
    def test_deployer_full_success(
        self,
        mock_get_sess: MagicMock,
        mock_verify: MagicMock,
        mock_docker_avail: MagicMock,
        mock_build: MagicMock,
        mock_iam: MagicMock,
        mock_ecr: MagicMock,
        mock_push: MagicMock,
        mock_apprunner: MagicMock,
        mock_wait: MagicMock,
        mock_health: MagicMock,
        sample_fastapi_project: Path,
        sample_config: AideployConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Setup env vars
        monkeypatch.setenv("OPENAI_API_KEY", "sk-mock")
        monkeypatch.setenv("DB_URL", "sqlite:///test.db")

        # Write config to disk
        write_config(sample_config, sample_fastapi_project)

        # Mock returns
        mock_sess = MagicMock()
        mock_sess.region_name = "us-east-1"
        mock_get_sess.return_value = mock_sess
        mock_verify.return_value = {"account": "123456789012", "arn": "arn:aws:iam::123:user/test"}
        mock_iam.return_value = "arn:aws:iam::123:role/test-role"
        mock_ecr.return_value = "123.dkr.ecr.us-east-1.amazonaws.com/test-api"
        mock_push.return_value = "123.dkr.ecr.us-east-1.amazonaws.com/test-api:dep-1"
        mock_apprunner.return_value = {
            "service_arn": "arn:aws:apprunner:us-east-1:123:service/test/abc",
            "service_url": "https://xyz.awsapprunner.com",
            "service_name": "aideploy-test-api",
        }
        mock_wait.return_value = {"ServiceUrl": "https://xyz.awsapprunner.com", "Status": "RUNNING"}
        mock_health.return_value = True

        deployer = Deployer(project_dir=sample_fastapi_project)
        result = deployer.run()

        assert result.status == "SUCCESS"
        assert result.endpoint == "https://xyz.awsapprunner.com"
        assert len(result.resources) == 3

        # Verify state written
        state_mgr = StateManager(sample_fastapi_project)
        assert state_mgr.exists() is True
        saved_state = state_mgr.load()
        assert saved_state.status == "RUNNING"
        assert saved_state.endpoint == "https://xyz.awsapprunner.com"


@pytest.mark.unit
class TestDeploymentDestroyer:
    """Tests for infrastructure teardown."""

    def test_plan_destruction_missing_state(self, tmp_path: Path) -> None:
        with pytest.raises(StateNotFoundError):
            plan_destruction(tmp_path)

    @patch("aideploy.deployment.destroyer.verify_credentials")
    @patch("aideploy.deployment.destroyer.get_aws_session")
    @patch("aideploy.deployment.destroyer.delete_app_runner_service")
    @patch("aideploy.deployment.destroyer.delete_ecr_repository")
    @patch("aideploy.deployment.destroyer.delete_app_runner_ecr_role")
    def test_destroy_deployment_success(
        self,
        mock_del_iam: MagicMock,
        mock_del_ecr: MagicMock,
        mock_del_apprunner: MagicMock,
        mock_get_sess: MagicMock,
        mock_verify: MagicMock,
        tmp_path: Path,
        sample_deployment_state: DeploymentState,
    ) -> None:
        state_mgr = StateManager(tmp_path)
        state_mgr.save(sample_deployment_state)

        result = destroy_deployment(project_dir=tmp_path)
        assert result.success is True
        assert len(result.destroyed_resources) == 3
        assert state_mgr.exists() is False
        mock_del_apprunner.assert_called_once()
        mock_del_ecr.assert_called_once()
        mock_del_iam.assert_called_once()
