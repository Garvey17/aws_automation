"""Cost Guard — validates deployment against cost policies.

Enforces budget limits, identifies billable/metered AWS resources, and
generates transparent deployment cost summaries before any infrastructure is created.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aideploy.config.schema import AideployConfig
from aideploy.constants import COST_RESOURCE_CATEGORIES
from aideploy.exceptions import CostPolicyViolationError

logger = logging.getLogger(__name__)


@dataclass
class PlannedResource:
    """A planned AWS resource and its cost classification."""

    name: str
    resource_type: str
    category: str  # "free_tier" | "metered" | "billable" | "unknown"
    description: str
    cost_note: str

    @property
    def status_symbol(self) -> str:
        if self.category == "free_tier":
            return "✓"
        elif self.category == "metered":
            return "✓"
        elif self.category == "billable":
            return "⚠"
        return "✗"


@dataclass
class CostPlan:
    """Full evaluation of a deployment plan against the cost policy."""

    project_name: str
    max_monthly: float
    resources: list[PlannedResource] = field(default_factory=list)
    potentially_billable_notes: list[str] = field(default_factory=list)
    allowed: bool = True
    block_reason: str | None = None

    def render_summary(self) -> str:
        """Render human-friendly cost plan summary matching the specification."""
        lines = [
            "Deployment plan",
            "────────────────────────────",
            f"Project: {self.project_name}",
            "",
            "Resources:",
        ]
        for r in self.resources:
            lines.append(f" {r.status_symbol} {r.name:<25} ({r.category}) - {r.description}")

        if self.potentially_billable_notes:
            lines.append("")
            lines.append("Potentially billable:")
            for note in self.potentially_billable_notes:
                lines.append(f" • {note}")

        lines.append("")
        lines.append("Cost policy:")
        lines.append(f"  max_monthly = ${self.max_monthly:.2f}")

        lines.append("")
        status_str = "ALLOWED" if self.allowed else f"BLOCKED ({self.block_reason})"
        lines.append(f"Deployment:\n  {status_str}")

        return "\n".join(lines)


def evaluate_cost_plan(config: AideployConfig) -> CostPlan:
    """Evaluate planned resources against the project cost policy.

    Raises:
        CostPolicyViolationError: If deployment violates the cost policy and cannot proceed.
    """
    max_monthly = config.cost.max_monthly

    planned_resources = [
        PlannedResource(
            name="IAM Role",
            resource_type="iam_role",
            category=COST_RESOURCE_CATEGORIES.get("iam_role", "free_tier"),
            description="ECR access role for App Runner",
            cost_note="Always free (AWS IAM)",
        ),
        PlannedResource(
            name="ECR Repository",
            resource_type="ecr_repository",
            category=COST_RESOURCE_CATEGORIES.get("ecr_repository", "free_tier"),
            description="Container registry (5 images kept)",
            cost_note="500 MB/month free tier, then $0.10/GB",
        ),
        PlannedResource(
            name="App Runner Service",
            resource_type="app_runner_service",
            category=COST_RESOURCE_CATEGORIES.get("app_runner_service", "metered"),
            description="Container runtime (0.25 vCPU, 0.5 GB)",
            cost_note="$0.064/vCPU-hour active, automatically pauses when idle",
        ),
        PlannedResource(
            name="CloudWatch Logs",
            resource_type="cloudwatch_logs",
            category=COST_RESOURCE_CATEGORIES.get("cloudwatch_logs", "free_tier"),
            description="Application and service logs",
            cost_note="5 GB/month free tier ingestion",
        ),
    ]

    potentially_billable: list[str] = [
        "App Runner active compute: $0.064/vCPU-hr during active requests (idle compute is not charged)",
        "ECR storage beyond 500 MB ($0.10/GB-month) — pruned to last 5 images",
        "Data transfer out: first 100 GB/month free globally",
    ]

    plan = CostPlan(
        project_name=config.name,
        max_monthly=max_monthly,
        resources=planned_resources,
        potentially_billable_notes=potentially_billable,
        allowed=True,
    )

    # Validate each resource against policy
    for res in planned_resources:
        if res.category == "unknown":
            plan.allowed = False
            plan.block_reason = f"Cannot determine cost characteristics for resource '{res.name}'"
            break
        elif res.category == "billable" and max_monthly == 0:
            plan.allowed = False
            plan.block_reason = (
                f"Resource '{res.name}' is always-on billable, which violates max_monthly = $0"
            )
            break

    logger.debug("Cost plan evaluated: allowed=%s, max_monthly=%s", plan.allowed, max_monthly)
    return plan


def check_cost_guard(config: AideployConfig) -> CostPlan:
    """Enforce the Cost Guard check, raising an exception if blocked."""
    plan = evaluate_cost_plan(config)
    if not plan.allowed:
        raise CostPolicyViolationError(
            resource=plan.block_reason or "Unknown resource",
            reason=f"violates cost policy max_monthly=${config.cost.max_monthly:.2f}",
        )
    return plan
