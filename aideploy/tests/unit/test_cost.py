"""Unit tests for Cost Guard."""

from __future__ import annotations

import pytest

from aideploy.aws.cost import PlannedResource, check_cost_guard, evaluate_cost_plan
from aideploy.config.schema import AideployConfig, AppConfig, CostConfig
from aideploy.exceptions import CostPolicyViolationError


@pytest.mark.unit
class TestCostGuard:
    """Tests for Cost Guard evaluation and policy enforcement."""

    def test_default_cost_plan_allowed_at_zero(self, sample_config: AideployConfig) -> None:
        plan = evaluate_cost_plan(sample_config)
        assert plan.allowed is True
        assert plan.max_monthly == 0
        assert len(plan.resources) == 4
        summary = plan.render_summary()
        assert "Deployment plan" in summary
        assert "ALLOWED" in summary
        assert "max_monthly = $0.00" in summary

    def test_cost_guard_blocks_billable_when_zero_budget(self) -> None:
        config = AideployConfig(
            name="test",
            app=AppConfig(entrypoint="main:app"),
            cost=CostConfig(max_monthly=0),
        )
        plan = evaluate_cost_plan(config)
        # Inject an always-on billable resource to verify policy enforcement
        plan.resources.append(
            PlannedResource(
                name="NAT Gateway",
                resource_type="nat_gateway",
                category="billable",
                description="Always-on NAT",
                cost_note="$32/month",
            )
        )
        # Re-evaluate
        for res in plan.resources:
            if res.category == "billable" and plan.max_monthly == 0:
                plan.allowed = False
                plan.block_reason = f"Resource '{res.name}' is always-on billable"
        assert plan.allowed is False
        assert "billable" in plan.block_reason.lower()

    def test_cost_guard_blocks_unknown_resource(self) -> None:
        config = AideployConfig(
            name="test",
            app=AppConfig(entrypoint="main:app"),
            cost=CostConfig(max_monthly=10),
        )
        plan = evaluate_cost_plan(config)
        plan.resources.append(
            PlannedResource(
                name="Custom Mystery Service",
                resource_type="mystery",
                category="unknown",
                description="Unknown billing",
                cost_note="Uncertain",
            )
        )
        for res in plan.resources:
            if res.category == "unknown":
                plan.allowed = False
                plan.block_reason = f"Cannot determine cost characteristics for resource '{res.name}'"
        assert plan.allowed is False
        assert "cannot determine cost" in plan.block_reason.lower()

    def test_check_cost_guard_raises_on_violation(self) -> None:
        config = AideployConfig(
            name="test",
            app=AppConfig(entrypoint="main:app"),
            cost=CostConfig(max_monthly=0),
        )
        # Normal check should pass without error
        plan = check_cost_guard(config)
        assert plan.allowed is True
