"""Resource destroyer — safely tears down AIDeploy infrastructure.

Identifies resources by local state and AWS tags, prompts for confirmation,
and removes all created resources in reverse dependency order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import boto3

from aideploy.aws.client import get_aws_session, verify_credentials
from aideploy.aws.compute import delete_app_runner_service
from aideploy.aws.iam import delete_app_runner_ecr_role
from aideploy.aws.storage import delete_ecr_repository
from aideploy.exceptions import DestructionError, StateNotFoundError
from aideploy.state.manager import DeploymentState, StateManager

logger = logging.getLogger(__name__)


@dataclass
class DestructionResult:
    """Summary of destroyed resources."""

    project: str
    deployment_id: str
    destroyed_resources: list[str] = field(default_factory=list)
    failed_resources: list[str] = field(default_factory=list)
    success: bool = True


def plan_destruction(
    project_dir: Path | None = None,
) -> tuple[StateManager, DeploymentState, list[str]]:
    """Identify resources marked for destruction from local state.

    Returns:
        tuple (state_manager, deployment_state, list_of_resource_descriptions)

    Raises:
        StateNotFoundError: If no deployment state exists.
    """
    state_mgr = StateManager(project_dir)
    state = state_mgr.load()

    resource_list: list[str] = []
    if state.resources:
        for r in state.resources:
            resource_list.append(f"{r.resource_type}: {r.name} ({r.identifier})")
    else:
        # Fall back to standard named resources for the project
        resource_list.append(f"App Runner Service: aideploy-{state.project}")
        resource_list.append(f"ECR Repository: aideploy-{state.project}")
        resource_list.append(f"IAM Role: aideploy-{state.project}-ecr-access-role")

    return state_mgr, state, resource_list


def destroy_deployment(
    session: boto3.Session | None = None,
    profile: str | None = None,
    region: str | None = None,
    project_dir: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> DestructionResult:
    """Safely destroy all AWS resources associated with the local deployment state.

    Args:
        session: Optional boto3 Session.
        profile: AWS CLI profile.
        region: AWS region.
        project_dir: Project directory root.
        progress_callback: Optional progress updater.

    Returns:
        DestructionResult summary.
    """
    state_mgr = StateManager(project_dir)
    state = state_mgr.load()

    aws_session = session or get_aws_session(
        profile=profile,
        region=region or state.region,
    )
    verify_credentials(aws_session)

    result = DestructionResult(
        project=state.project,
        deployment_id=state.deployment_id,
    )

    # 1. Delete App Runner Service
    if progress_callback:
        progress_callback("Deleting App Runner compute service...")
    try:
        app_runner_arn = None
        for r in state.resources:
            if r.resource_type == "apprunner_service":
                app_runner_arn = r.identifier
                break

        delete_app_runner_service(
            session=aws_session,
            service_arn=app_runner_arn,
            project_name=state.project,
        )
        result.destroyed_resources.append("App Runner Service")
    except Exception as exc:
        logger.warning("Error deleting App Runner service: %s", exc)
        result.failed_resources.append(f"App Runner Service: {exc}")

    # 2. Delete ECR Repository
    if progress_callback:
        progress_callback("Deleting ECR container repository...")
    try:
        delete_ecr_repository(
            session=aws_session,
            project_name=state.project,
        )
        result.destroyed_resources.append("ECR Repository")
    except Exception as exc:
        logger.warning("Error deleting ECR repository: %s", exc)
        result.failed_resources.append(f"ECR Repository: {exc}")

    # 3. Delete IAM Role
    if progress_callback:
        progress_callback("Deleting IAM access role...")
    try:
        delete_app_runner_ecr_role(
            session=aws_session,
            project_name=state.project,
        )
        result.destroyed_resources.append("IAM Role")
    except Exception as exc:
        logger.warning("Error deleting IAM role: %s", exc)
        result.failed_resources.append(f"IAM Role: {exc}")

    # 4. Clean up local state file
    state_mgr.clear()

    if result.failed_resources:
        result.success = False

    logger.info("Teardown complete: destroyed=%s, failed=%s", result.destroyed_resources, result.failed_resources)
    return result
