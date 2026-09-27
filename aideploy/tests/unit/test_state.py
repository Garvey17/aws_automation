"""Unit tests for state management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aideploy.constants import STATE_DIR, STATE_FILE
from aideploy.exceptions import StateCorruptedError, StateNotFoundError
from aideploy.state.manager import DeployedResource, DeploymentState, StateManager


@pytest.mark.unit
class TestStateManager:
    """Tests for saving, loading, and modifying deployment state."""

    def test_state_not_found(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path)
        assert mgr.exists() is False
        with pytest.raises(StateNotFoundError):
            mgr.load()

    def test_save_and_load_state(self, tmp_path: Path, sample_deployment_state: DeploymentState) -> None:
        mgr = StateManager(tmp_path)
        mgr.save(sample_deployment_state)
        assert mgr.exists() is True

        loaded = mgr.load()
        assert loaded.project == sample_deployment_state.project
        assert loaded.deployment_id == sample_deployment_state.deployment_id
        assert loaded.status == "RUNNING"
        assert loaded.endpoint == sample_deployment_state.endpoint
        assert len(loaded.resources) == 3

    def test_corrupted_json_state(self, tmp_path: Path) -> None:
        state_dir = tmp_path / STATE_DIR
        state_dir.mkdir(parents=True)
        (state_dir / STATE_FILE).write_text("{broken json...", encoding="utf-8")

        mgr = StateManager(tmp_path)
        with pytest.raises(StateCorruptedError):
            mgr.load()

    def test_malformed_fields_state(self, tmp_path: Path) -> None:
        state_dir = tmp_path / STATE_DIR
        state_dir.mkdir(parents=True)
        (state_dir / STATE_FILE).write_text('{"missing_project": true}', encoding="utf-8")

        mgr = StateManager(tmp_path)
        with pytest.raises(StateCorruptedError):
            mgr.load()

    def test_clear_state(self, tmp_path: Path, sample_deployment_state: DeploymentState) -> None:
        mgr = StateManager(tmp_path)
        mgr.save(sample_deployment_state)
        assert mgr.exists() is True
        mgr.clear()
        assert mgr.exists() is False

    def test_no_secrets_in_serialized_state(self, sample_deployment_state: DeploymentState) -> None:
        raw_dict = sample_deployment_state.to_dict()
        raw_str = json.dumps(raw_dict)
        assert "secret" not in raw_str.lower()
        assert "password" not in raw_str.lower()
        assert "key" not in raw_str.lower() or "image_tag" in raw_str
