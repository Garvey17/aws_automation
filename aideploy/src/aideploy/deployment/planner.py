"""Deployment planner.

Validates configuration, checks environment variables, generates deployment IDs,
and creates an execution plan before any infrastructure is touched.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aideploy.aws.cost import CostPlan, check_cost_guard, evaluate_cost_plan
from aideploy.config.schema import AideployConfig
from aideploy.constants import DEPLOYMENT_ID_PREFIX
from aideploy.docker.builder import make_image_tag
from aideploy.exceptions import ConfigError

logger = logging.getLogger(__name__)


def generate_deployment_id() -> str:
    """Generate a unique, deterministic deployment identifier.

    Format: ``dep-YYYYMMDD-xxxxxx``
    """
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique_suffix = uuid.uuid4().hex[:6]
    return f"{DEPLOYMENT_ID_PREFIX}-{date_str}-{unique_suffix}"


@dataclass
class DeploymentPlan:
    """Complete plan for executing a deployment."""

    project_name: str
    deployment_id: str
    config: AideployConfig
    local_image_tag: str
    cost_plan: CostPlan
    environment_variables: dict[str, str] = field(default_factory=dict)
    missing_env_vars: list[str] = field(default_factory=list)


def create_deployment_plan(
    config: AideployConfig,
    project_dir: Path | None = None,
    deployment_id: str | None = None,
) -> DeploymentPlan:
    """Create a validated deployment plan.

    Args:
        config: Validated AideployConfig.
        project_dir: Project directory root.
        deployment_id: Optional existing deployment ID to reuse.

    Returns:
        DeploymentPlan ready for execution.

    Raises:
        ConfigError: If required environment variables are not found in the local environment.
        CostPolicyViolationError: If deployment violates the configured cost policy.
    """
    dep_id = deployment_id or generate_deployment_id()
    local_tag = make_image_tag(config.name, dep_id)

    # Resolve environment variables from host OS
    env_vars: dict[str, str] = {}
    missing_vars: list[str] = []

    for var_name in config.environment:
        val = os.environ.get(var_name)
        if val is None:
            missing_vars.append(var_name)
        else:
            env_vars[var_name] = val

    if missing_vars:
        missing_list = ", ".join(missing_vars)
        raise ConfigError(
            f"Required environment variable(s) not found in local environment: {missing_list}",
            hint=(
                f"Set the missing variables before deploying:\n"
                f"  export {missing_vars[0]}=...\n"
                "or remove them from the 'environment' list in aideploy.yaml."
            ),
        )

    # Evaluate cost plan
    cost_plan = check_cost_guard(config)

    plan = DeploymentPlan(
        project_name=config.name,
        deployment_id=dep_id,
        config=config,
        local_image_tag=local_tag,
        cost_plan=cost_plan,
        environment_variables=env_vars,
        missing_env_vars=missing_vars,
    )

    logger.debug("Deployment plan created: %s", plan)
    return plan
