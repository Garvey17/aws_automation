"""Configuration schema — Pydantic models for aideploy.yaml."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RuntimeConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(extra="forbid")

    python: str = "3.12"

    @field_validator("python")
    @classmethod
    def validate_python_version(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) < 2:
            raise ValueError(f"python version must be in 'MAJOR.MINOR' format, got: {v!r}")
        try:
            major, minor = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"python version must be numeric, got: {v!r}") from None
        if major != 3 or minor < 9:
            raise ValueError(
                f"AIDeploy requires Python 3.9+, got: {v!r}"
            )
        return v


class AppConfig(BaseModel):
    """Application configuration."""

    model_config = ConfigDict(extra="forbid")

    entrypoint: str = Field(
        ...,
        description=(
            "Python import path of the FastAPI application object. "
            "Format: 'module.path:attribute', e.g. 'app.main:app'."
        ),
    )
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(
                f"entrypoint must be in 'module:attribute' format, got: {v!r}\n"
                "Example: 'app.main:app'"
            )
        module, attr = v.split(":", 1)
        if not module or not attr:
            raise ValueError(
                f"entrypoint module and attribute must both be non-empty, got: {v!r}"
            )
        return v


class HealthConfig(BaseModel):
    """Health check configuration."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(default="/health", description="HTTP path for the health check.")
    timeout: int = Field(default=10, ge=1, le=120, description="Seconds per attempt.")
    retries: int = Field(default=10, ge=1, le=60, description="Number of retry attempts.")
    interval: int = Field(
        default=15, ge=5, le=300, description="Seconds between retries."
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"health.path must start with '/', got: {v!r}")
        return v


class CostConfig(BaseModel):
    """Cost policy configuration."""

    model_config = ConfigDict(extra="forbid")

    max_monthly: Annotated[float, Field(ge=0)] = Field(
        default=0,
        description=(
            "Maximum acceptable monthly cost in USD. "
            "Set to 0 to allow only free-tier/metered resources. "
            "Set to a positive value to allow always-on resources up to that amount."
        ),
    )


DeploymentStrategy = Literal["auto", "apprunner"]


class DeploymentConfig(BaseModel):
    """Deployment strategy configuration."""

    model_config = ConfigDict(extra="forbid")

    strategy: DeploymentStrategy = Field(
        default="auto",
        description=(
            "Deployment strategy. 'auto' selects the best available strategy. "
            "'apprunner' forces AWS App Runner."
        ),
    )
    region: str | None = Field(
        default=None,
        description="AWS region. Defaults to the AWS CLI / environment default.",
    )


class AideployConfig(BaseModel):
    """Root configuration model for aideploy.yaml.

    All fields are validated strictly — unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
        description=(
            "Project name. Used as a prefix for AWS resource names. "
            "Must start with a letter and contain only letters, numbers, hyphens, underscores."
        ),
    )
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    app: AppConfig
    health: HealthConfig = Field(default_factory=HealthConfig)
    environment: list[str] = Field(
        default_factory=list,
        description=(
            "Names of environment variables to inject into the container. "
            "Values are read from the local environment — never stored in this file."
        ),
    )
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    cost: CostConfig = Field(default_factory=CostConfig)

    @model_validator(mode="after")
    def validate_environment_names(self) -> "AideployConfig":
        for var in self.environment:
            if not var.replace("_", "").isalnum():
                raise ValueError(
                    f"environment variable name {var!r} contains invalid characters. "
                    "Only letters, digits, and underscores are allowed."
                )
        return self
