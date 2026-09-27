"""Unit tests for configuration schema and loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aideploy.config.loader import load_config, write_config
from aideploy.config.schema import (
    AideployConfig,
    AppConfig,
    CostConfig,
    DeploymentConfig,
    HealthConfig,
    RuntimeConfig,
)
from aideploy.constants import CONFIG_FILE
from aideploy.exceptions import ConfigError, ConfigNotFoundError


@pytest.mark.unit
class TestConfigSchema:
    """Tests for Pydantic configuration schema validation."""

    def test_valid_minimal_config(self) -> None:
        config = AideployConfig(
            name="my-api",
            app=AppConfig(entrypoint="main:app"),
        )
        assert config.name == "my-api"
        assert config.runtime.python == "3.12"
        assert config.app.entrypoint == "main:app"
        assert config.app.port == 8000
        assert config.health.path == "/health"
        assert config.cost.max_monthly == 0
        assert config.deployment.strategy == "auto"

    def test_invalid_project_name(self) -> None:
        with pytest.raises(ValidationError):
            AideployConfig(
                name="123-invalid-start",
                app=AppConfig(entrypoint="main:app"),
            )

    def test_invalid_entrypoint_format(self) -> None:
        with pytest.raises(ValidationError):
            AideployConfig(
                name="my-api",
                app=AppConfig(entrypoint="main_no_colon"),
            )

    def test_invalid_python_version(self) -> None:
        with pytest.raises(ValidationError):
            AideployConfig(
                name="my-api",
                runtime=RuntimeConfig(python="2.7"),
                app=AppConfig(entrypoint="main:app"),
            )

    def test_invalid_health_path(self) -> None:
        with pytest.raises(ValidationError):
            AideployConfig(
                name="my-api",
                app=AppConfig(entrypoint="main:app"),
                health=HealthConfig(path="health_without_slash"),
            )

    def test_invalid_env_var_name(self) -> None:
        with pytest.raises(ValidationError):
            AideployConfig(
                name="my-api",
                app=AppConfig(entrypoint="main:app"),
                environment=["INVALID-NAME-WITH-DASHES!"],
            )

    def test_extra_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AideployConfig.model_validate(
                {
                    "name": "my-api",
                    "app": {"entrypoint": "main:app"},
                    "unknown_field": 123,
                }
            )


@pytest.mark.unit
class TestConfigLoader:
    """Tests for loading and saving aideploy.yaml."""

    def test_load_config_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigNotFoundError):
            load_config(tmp_path)

    def test_load_valid_config(self, tmp_path: Path, sample_config: AideployConfig) -> None:
        write_config(sample_config, tmp_path)
        loaded = load_config(tmp_path)
        assert loaded.name == sample_config.name
        assert loaded.app.entrypoint == sample_config.app.entrypoint
        assert loaded.environment == ["OPENAI_API_KEY", "DB_URL"]

    def test_load_malformed_yaml(self, tmp_path: Path) -> None:
        (tmp_path / CONFIG_FILE).write_text("name: [unclosed list", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(tmp_path)

    def test_load_non_mapping_yaml(self, tmp_path: Path) -> None:
        (tmp_path / CONFIG_FILE).write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(tmp_path)

    def test_load_invalid_schema(self, tmp_path: Path) -> None:
        (tmp_path / CONFIG_FILE).write_text(
            "name: my-api\napp:\n  entrypoint: invalid\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            load_config(tmp_path)
