"""Unit tests for Dockerfile generation and builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aideploy.config.schema import AideployConfig, AppConfig
from aideploy.constants import DOCKER_IMAGE_LABEL
from aideploy.docker.builder import (
    build_image,
    check_docker_available,
    generate_dockerfile,
    make_ecr_image_uri,
    make_image_tag,
    write_dockerfile,
)
from aideploy.exceptions import DockerBuildError, DockerNotAvailableError


@pytest.mark.unit
class TestDockerBuilder:
    """Tests for Docker packaging utilities."""

    def test_generate_dockerfile_with_requirements(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        config = AideployConfig(name="test", app=AppConfig(entrypoint="main:app", port=8000))
        content = generate_dockerfile(config, tmp_path)
        assert "FROM python:3.12-slim" in content
        assert "requirements.txt" in content
        assert "uvicorn" in content
        assert "main:app" in content
        assert "8000" in content
        assert "appuser" in content

    def test_generate_dockerfile_with_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
        config = AideployConfig(name="test", app=AppConfig(entrypoint="app.server:app", port=8080))
        content = generate_dockerfile(config, tmp_path)
        assert "pyproject.toml" in content
        assert "app.server:app" in content
        assert "8080" in content

    def test_write_dockerfile_preserve_existing(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM custom-base:latest\n", encoding="utf-8")
        config = AideployConfig(name="test", app=AppConfig(entrypoint="main:app"))
        path, created = write_dockerfile(config, tmp_path, force=False)
        assert created is False
        assert path.read_text(encoding="utf-8") == "FROM custom-base:latest\n"

    def test_write_dockerfile_overwrite_with_force(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM custom-base:latest\n", encoding="utf-8")
        config = AideployConfig(name="test", app=AppConfig(entrypoint="main:app"))
        path, created = write_dockerfile(config, tmp_path, force=True)
        assert created is True
        assert "python:3.12-slim" in path.read_text(encoding="utf-8")

    def test_make_image_tag_deterministic(self) -> None:
        tag = make_image_tag("My-Project_App", "dep-20260927-123456")
        assert tag == "my-project-app:dep-20260927-123456"

    def test_make_ecr_image_uri(self) -> None:
        uri = make_ecr_image_uri("123.dkr.ecr.us-east-1.amazonaws.com/repo", "dep-123")
        assert uri == "123.dkr.ecr.us-east-1.amazonaws.com/repo:dep-123"

    @patch("subprocess.run")
    def test_check_docker_available_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="25.0.0\n")
        check_docker_available()  # Should not raise

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_check_docker_available_failure(self, mock_run: MagicMock) -> None:
        with pytest.raises(DockerNotAvailableError):
            check_docker_available()

    @patch("aideploy.docker.builder.check_docker_available")
    @patch("subprocess.Popen")
    def test_build_image_success(
        self,
        mock_popen: MagicMock,
        mock_check: MagicMock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
        proc = MagicMock()
        proc.stdout = ["Step 1/5 : FROM python:3.12-slim\n", "Successfully built 12345\n"]
        proc.returncode = 0
        proc.wait.return_value = None
        mock_popen.return_value = proc

        tag = build_image("test-app:dep-123", project_dir=tmp_path)
        assert tag == "test-app:dep-123"
