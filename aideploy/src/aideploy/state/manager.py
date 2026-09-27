"""Deployment state manager.

Maintains `.aideploy/state.json` to record provisioned infrastructure for safe inspection
and complete teardown. Never stores secrets or credentials.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aideploy.constants import STATE_DIR, STATE_FILE
from aideploy.exceptions import StateCorruptedError, StateNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class DeployedResource:
    """Record of a created AWS resource."""

    resource_type: str  # e.g. "apprunner_service", "ecr_repository", "iam_role"
    identifier: str  # ARN or Name
    name: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeploymentState:
    """Schema for local deployment state (.aideploy/state.json)."""

    project: str
    deployment_id: str
    status: str  # "PROVISIONING" | "RUNNING" | "FAILED" | "DESTROYED"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    endpoint: str | None = None
    region: str | None = None
    image_tag: str | None = None
    resources: list[DeployedResource] = field(default_factory=list)
    expires_at: str | None = None
    last_health_check: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert state to serializable dictionary without secrets."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeploymentState:
        """Create DeploymentState from dictionary."""
        resources_raw = data.get("resources", [])
        resources = [
            DeployedResource(
                resource_type=r["resource_type"],
                identifier=r["identifier"],
                name=r["name"],
                created_at=r.get("created_at", datetime.now(timezone.utc).isoformat()),
                metadata=r.get("metadata", {}),
            )
            for r in resources_raw
        ]
        return cls(
            project=data["project"],
            deployment_id=data["deployment_id"],
            status=data.get("status", "RUNNING"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            endpoint=data.get("endpoint"),
            region=data.get("region"),
            image_tag=data.get("image_tag"),
            resources=resources,
            expires_at=data.get("expires_at"),
            last_health_check=data.get("last_health_check"),
        )

    def add_resource(
        self,
        resource_type: str,
        identifier: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track a newly provisioned resource."""
        self.resources.append(
            DeployedResource(
                resource_type=resource_type,
                identifier=identifier,
                name=name,
                metadata=metadata or {},
            )
        )


class StateManager:
    """Manages reading, writing, and clearing .aideploy/state.json."""

    def __init__(self, project_dir: Path | None = None) -> None:
        self.directory = project_dir or Path.cwd()
        self.state_dir = self.directory / STATE_DIR
        self.state_file = self.state_dir / STATE_FILE

    def exists(self) -> bool:
        """Return True if a state file exists."""
        return self.state_file.exists()

    def load(self) -> DeploymentState:
        """Load and parse the deployment state.

        Raises:
            StateNotFoundError: If no state file exists.
            StateCorruptedError: If the state file is invalid JSON or malformed.
        """
        if not self.exists():
            raise StateNotFoundError()

        try:
            content = self.state_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("State file root must be a JSON object")
            state = DeploymentState.from_dict(data)
            logger.debug("Loaded state for project=%s deployment=%s", state.project, state.deployment_id)
            return state
        except json.JSONDecodeError as exc:
            raise StateCorruptedError(
                f"State file {self.state_file} contains invalid JSON: {exc}",
                hint="You may delete .aideploy/state.json manually if the deployment was already cleaned up.",
            ) from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise StateCorruptedError(
                f"State file {self.state_file} is malformed: {exc}",
                hint="Check .aideploy/state.json structure or delete it if invalid.",
            ) from exc

    def save(self, state: DeploymentState) -> Path:
        """Save the deployment state safely to disk."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = state.to_dict()
        tmp_file = self.state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_file.replace(self.state_file)
        logger.debug("State saved to %s", self.state_file)
        return self.state_file

    def clear(self) -> None:
        """Remove state file after complete teardown."""
        if self.state_file.exists():
            try:
                self.state_file.unlink()
                logger.debug("State file deleted: %s", self.state_file)
            except OSError as exc:
                logger.warning("Could not delete state file %s: %s", self.state_file, exc)
