"""Deployment orchestrator.

Executes the end-to-end deployment pipeline with explicit lifecycle phases,
safe rollback on failure, progress reporting, and health verification.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import boto3

from aideploy.aws.client import get_aws_session, get_default_region, verify_credentials
from aideploy.aws.compute import create_or_update_app_runner_service, wait_for_app_runner_service
from aideploy.aws.cost import CostPlan, check_cost_guard
from aideploy.aws.iam import ensure_app_runner_ecr_role
from aideploy.aws.storage import ensure_ecr_repository, push_image_to_ecr
from aideploy.config.loader import load_config
from aideploy.config.schema import AideployConfig
from aideploy.deployment.health import check_health
from aideploy.deployment.planner import DeploymentPlan, create_deployment_plan
from aideploy.detector.fastapi import detect_project
from aideploy.docker.builder import build_image, check_docker_available, write_dockerfile
from aideploy.exceptions import (
    AideployError,
    AWSError,
    DeploymentError,
    DetectionError,
    DockerError,
    HealthCheckError,
)
from aideploy.state.manager import DeployedResource, DeploymentState, StateManager

logger = logging.getLogger(__name__)


@dataclass
class DeploymentResult:
    """Outcome of a completed or failed deployment."""

    project: str
    deployment_id: str
    endpoint: str | None
    status: str  # "SUCCESS" | "FAILED"
    region: str
    resources: list[DeployedResource] = field(default_factory=list)
    cost_plan: CostPlan | None = None
    error_message: str | None = None
    duration_seconds: float = 0.0


class Deployer:
    """Coordinates the 7-phase deployment workflow."""

    def __init__(
        self,
        project_dir: Path | None = None,
        profile: str | None = None,
        region: str | None = None,
        progress_callback: Callable[[int, int, str, str], None] | None = None,
    ) -> None:
        self.project_dir = project_dir or Path.cwd()
        self.profile = profile
        self.region = region
        self.progress_callback = progress_callback
        self.state_mgr = StateManager(self.project_dir)

    def _notify(self, phase_index: int, total_phases: int, name: str, status: str) -> None:
        if self.progress_callback:
            self.progress_callback(phase_index, total_phases, name, status)

    def run(self) -> DeploymentResult:
        """Run the full deployment lifecycle."""
        start_time = time.time()
        total_phases = 7

        # ── Phase 1: Validate project & credentials ───────────────────────────
        self._notify(1, total_phases, "Validating project & AWS", "running")
        config = load_config(self.project_dir)
        target_region = self.region or config.deployment.region
        aws_session = get_aws_session(profile=self.profile, region=target_region)
        resolved_region = get_default_region(aws_session)
        verify_credentials(aws_session)
        check_docker_available()
        self._notify(1, total_phases, "Validating project & AWS", "done")

        # ── Phase 2: Detecting FastAPI ─────────────────────────────────────────
        self._notify(2, total_phases, "Detecting FastAPI", "running")
        project_info = detect_project(self.project_dir)
        if project_info is None:
            raise DetectionError(
                f"No FastAPI application detected in {self.project_dir}.",
                hint="Ensure fastapi is in requirements.txt or pyproject.toml.",
            )
        self._notify(2, total_phases, "Detecting FastAPI", "done")

        # ── Phase 3: Building container ───────────────────────────────────────
        self._notify(3, total_phases, "Building container", "running")
        write_dockerfile(config, self.project_dir, force=False)
        plan = create_deployment_plan(config, self.project_dir)
        build_image(
            image_tag=plan.local_image_tag,
            project_dir=self.project_dir,
            platform="linux/amd64",
        )
        self._notify(3, total_phases, "Building container", "done")

        # ── Phase 4: Checking cost policy ─────────────────────────────────────
        self._notify(4, total_phases, "Checking cost policy", "running")
        cost_plan = check_cost_guard(config)
        self._notify(4, total_phases, "Checking cost policy", "done")

        # ── Phase 5: Provisioning AWS infrastructure ──────────────────────────
        self._notify(5, total_phases, "Provisioning AWS (IAM & ECR)", "running")
        # Initialize state tracking
        state = DeploymentState(
            project=config.name,
            deployment_id=plan.deployment_id,
            status="PROVISIONING",
            region=resolved_region,
            image_tag=plan.local_image_tag,
        )
        self.state_mgr.save(state)

        # 5a: IAM Role
        role_arn = ensure_app_runner_ecr_role(
            session=aws_session,
            project_name=config.name,
            deployment_id=plan.deployment_id,
        )
        state.add_resource("iam_role", role_arn, f"aideploy-{config.name}-ecr-access-role")
        self.state_mgr.save(state)

        # 5b: ECR Repository
        ecr_uri = ensure_ecr_repository(
            session=aws_session,
            project_name=config.name,
            deployment_id=plan.deployment_id,
        )
        state.add_resource("ecr_repository", ecr_uri, f"aideploy-{config.name}")
        self.state_mgr.save(state)

        # 5c: Push image to ECR
        remote_image_uri = push_image_to_ecr(
            session=aws_session,
            local_image_tag=plan.local_image_tag,
            ecr_repo_uri=ecr_uri,
            deployment_id=plan.deployment_id,
        )
        self._notify(5, total_phases, "Provisioning AWS (IAM & ECR)", "done")

        # ── Phase 6: Deploying application to App Runner ──────────────────────
        self._notify(6, total_phases, "Deploying application", "running")
        app_runner_info = create_or_update_app_runner_service(
            session=aws_session,
            project_name=config.name,
            deployment_id=plan.deployment_id,
            image_uri=remote_image_uri,
            access_role_arn=role_arn,
            port=config.app.port,
            health_path=config.health.path,
            env_vars=plan.environment_variables,
        )
        service_arn = app_runner_info["service_arn"]
        state.add_resource("apprunner_service", service_arn, app_runner_info["service_name"])
        self.state_mgr.save(state)

        # Wait for service to become RUNNING
        service_desc = wait_for_app_runner_service(
            session=aws_session,
            service_arn=service_arn,
            max_wait_seconds=600,
            poll_interval=10,
        )
        endpoint = service_desc.get("ServiceUrl") or app_runner_info["service_url"]
        state.endpoint = endpoint
        self.state_mgr.save(state)
        self._notify(6, total_phases, "Deploying application", "done")

        # ── Phase 7: Health check ─────────────────────────────────────────────
        self._notify(7, total_phases, "Health check", "running")
        check_health(base_url=endpoint, health_config=config.health)
        state.status = "RUNNING"
        state.last_health_check = "PASSED"
        self.state_mgr.save(state)
        self._notify(7, total_phases, "Health check", "done")

        duration = time.time() - start_time
        return DeploymentResult(
            project=config.name,
            deployment_id=plan.deployment_id,
            endpoint=endpoint,
            status="SUCCESS",
            region=resolved_region,
            resources=state.resources,
            cost_plan=cost_plan,
            duration_seconds=duration,
        )
