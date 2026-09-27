"""Pytest configuration and shared fixtures for AIDeploy tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from aideploy.config.schema import AideployConfig, AppConfig, CostConfig, DeploymentConfig, HealthConfig, RuntimeConfig
from aideploy.state.manager import DeployedResource, DeploymentState


@pytest.fixture
def sample_config() -> AideployConfig:
    """Fixture providing a standard valid AideployConfig."""
    return AideployConfig(
        name="test-api",
        runtime=RuntimeConfig(python="3.12"),
        app=AppConfig(entrypoint="app.main:app", port=8000),
        health=HealthConfig(path="/health", timeout=5, retries=3, interval=5),
        environment=["OPENAI_API_KEY", "DB_URL"],
        deployment=DeploymentConfig(strategy="auto", region="us-east-1"),
        cost=CostConfig(max_monthly=0),
    )


@pytest.fixture
def sample_fastapi_project(tmp_path: Path) -> Path:
    """Fixture creating a realistic temporary FastAPI project on disk."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "import os\n"
        "app = FastAPI()\n"
        "api_key = os.getenv('OPENAI_API_KEY')\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("fastapi>=0.110.0\nuvicorn>=0.28.0\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def sample_deployment_state() -> DeploymentState:
    """Fixture providing a mock DeploymentState."""
    state = DeploymentState(
        project="test-api",
        deployment_id="dep-20260927-abc123",
        status="RUNNING",
        endpoint="https://xyz123.awsapprunner.com",
        region="us-east-1",
        image_tag="test-api:dep-20260927-abc123",
    )
    state.add_resource("iam_role", "arn:aws:iam::123456789012:role/aideploy-test-api-role", "aideploy-test-api-role")
    state.add_resource("ecr_repository", "123456789012.dkr.ecr.us-east-1.amazonaws.com/aideploy-test-api", "aideploy-test-api")
    state.add_resource("apprunner_service", "arn:aws:apprunner:us-east-1:123456789012:service/aideploy-test-api/abc", "aideploy-test-api")
    return state
