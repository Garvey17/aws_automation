"""AWS infrastructure management package for AIDeploy."""

from aideploy.aws.client import get_aws_session, get_default_region, verify_credentials
from aideploy.aws.cost import CostPlan, check_cost_guard, evaluate_cost_plan

__all__ = [
    "CostPlan",
    "check_cost_guard",
    "evaluate_cost_plan",
    "get_aws_session",
    "get_default_region",
    "verify_credentials",
]
