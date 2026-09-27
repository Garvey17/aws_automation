"""AIDeploy exception hierarchy.

All exceptions raised by AIDeploy are subclasses of AideployError.
This allows callers to catch all AIDeploy errors in a single except clause
while still being able to distinguish between error types.
"""

from __future__ import annotations


class AideployError(Exception):
    """Base exception for all AIDeploy errors."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\n\nHint: {self.hint}"
        return self.message


# ── Configuration ──────────────────────────────────────────────────────────────


class ConfigError(AideployError):
    """Configuration file is missing, invalid, or contains unknown fields."""


class ConfigNotFoundError(ConfigError):
    """aideploy.yaml was not found in the current directory."""

    def __init__(self) -> None:
        super().__init__(
            "No aideploy.yaml found in the current directory.",
            hint="Run `aideploy init` to create one.",
        )


# ── Project Detection ──────────────────────────────────────────────────────────


class DetectionError(AideployError):
    """FastAPI project could not be detected."""


class EntrypointNotFoundError(DetectionError):
    """The configured entrypoint module/attribute was not found."""


# ── Docker ─────────────────────────────────────────────────────────────────────


class DockerError(AideployError):
    """Docker is unavailable or a Docker operation failed."""


class DockerNotAvailableError(DockerError):
    """Docker daemon is not running or not installed."""

    def __init__(self) -> None:
        super().__init__(
            "Docker is not available.",
            hint=(
                "Ensure Docker Desktop (or Docker Engine) is installed and running.\n"
                "Test with: docker info"
            ),
        )


class DockerBuildError(DockerError):
    """Docker image build failed."""


# ── AWS ────────────────────────────────────────────────────────────────────────


class AWSError(AideployError):
    """An AWS API call failed."""


class AWSCredentialsError(AWSError):
    """AWS credentials could not be resolved."""

    def __init__(self, detail: str = "") -> None:
        base = "AWS authentication failed. AIDeploy could not obtain valid AWS credentials."
        if detail:
            base = f"{base}\n\nDetail: {detail}"
        super().__init__(
            base,
            hint=(
                "Check:\n"
                "  1. Run `aws sts get-caller-identity` to verify credentials.\n"
                "  2. Set AWS_PROFILE to an existing profile.\n"
                "  3. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.\n"
                "  4. Review ~/.aws/credentials."
            ),
        )


class AWSPermissionError(AWSError):
    """The AWS caller lacks required IAM permissions."""

    def __init__(self, action: str, resource: str = "*") -> None:
        super().__init__(
            f"Insufficient AWS permissions: {action} on {resource}.",
            hint=(
                "Review the required IAM permissions in the README.\n"
                "Attach the AIDeploy IAM policy to your user or role."
            ),
        )


class AWSResourceNotFoundError(AWSError):
    """An expected AWS resource does not exist."""


class AWSTimeoutError(AWSError):
    """An AWS operation timed out waiting for a resource state."""


# ── Cost Guard ─────────────────────────────────────────────────────────────────


class CostGuardError(AideployError):
    """Deployment blocked by cost policy."""


class CostPolicyViolationError(CostGuardError):
    """A required resource violates the configured cost policy."""

    def __init__(self, resource: str, reason: str) -> None:
        super().__init__(
            f"Cost policy violation: {resource} — {reason}",
            hint=(
                "Update cost.max_monthly in aideploy.yaml to allow billable resources,\n"
                "or choose a deployment strategy that avoids this resource."
            ),
        )


# ── State ──────────────────────────────────────────────────────────────────────


class StateError(AideployError):
    """Local deployment state is missing, corrupted, or inconsistent."""


class StateNotFoundError(StateError):
    """No deployment state found — nothing has been deployed yet."""

    def __init__(self) -> None:
        super().__init__(
            "No deployment state found.",
            hint="Run `aideploy up` to deploy the application.",
        )


class StateCorruptedError(StateError):
    """The state file exists but cannot be parsed."""


# ── Deployment ─────────────────────────────────────────────────────────────────


class DeploymentError(AideployError):
    """A deployment phase failed."""


class HealthCheckError(DeploymentError):
    """The application did not become healthy within the configured timeout."""

    def __init__(self, url: str, retries: int) -> None:
        super().__init__(
            f"Health check failed after {retries} attempts: {url}",
            hint=(
                "Check:\n"
                "  1. The application starts correctly (docker run locally).\n"
                "  2. The health path in aideploy.yaml is correct.\n"
                "  3. `aideploy logs` for application errors."
            ),
        )


class DestructionError(AideployError):
    """Resource destruction failed or was aborted."""
