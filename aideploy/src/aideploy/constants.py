"""AIDeploy constants — centralised so they're easy to audit and update."""

from __future__ import annotations

# ── Resource tagging ───────────────────────────────────────────────────────────

TAG_MANAGED_BY = "ManagedBy"
TAG_MANAGED_BY_VALUE = "AIDeploy"

TAG_PROJECT = "Project"
TAG_DEPLOYMENT_ID = "DeploymentId"
TAG_ENVIRONMENT = "Environment"
TAG_ENVIRONMENT_VALUE = "portfolio"

# ── State ──────────────────────────────────────────────────────────────────────

STATE_DIR = ".aideploy"
STATE_FILE = "state.json"
CONFIG_FILE = "aideploy.yaml"

# ── Docker ─────────────────────────────────────────────────────────────────────

DEFAULT_APP_PORT = 8000
DOCKERFILE_NAME = "Dockerfile"
DOCKER_IMAGE_LABEL = "aideploy.managed"

# ── Deployment ─────────────────────────────────────────────────────────────────

DEPLOYMENT_ID_PREFIX = "dep"
DEFAULT_HEALTH_PATH = "/health"
DEFAULT_HEALTH_TIMEOUT = 10
DEFAULT_HEALTH_RETRIES = 10
DEFAULT_HEALTH_INTERVAL = 15  # seconds between retries

# ── AWS ────────────────────────────────────────────────────────────────────────

APP_RUNNER_CPU = "0.25 vCPU"
APP_RUNNER_MEMORY = "0.5 GB"
APP_RUNNER_PORT = 8000
ECR_LIFECYCLE_KEEP_COUNT = 5  # keep last 5 images per repo

# ── Cost ───────────────────────────────────────────────────────────────────────

# Resources categorised by billing behaviour for the Cost Guard.
# "free_tier"   — covered by AWS free tier (subject to limits)
# "metered"     — pay-per-use, can be $0 with no traffic
# "billable"    — incurs cost even with no traffic (always-on resources)

COST_RESOURCE_CATEGORIES: dict[str, str] = {
    "ecr_repository": "free_tier",  # 500 MB free / month
    "ecr_image_push": "metered",    # $0.10/GB beyond free tier
    "app_runner_service": "metered",  # $0.064/vCPU-h active; auto-pause when idle
    "app_runner_build": "metered",   # ~$0.005/build-min
    "cloudwatch_logs": "free_tier",  # 5 GB ingestion free / month
    "iam_role": "free_tier",         # IAM is always free
}
