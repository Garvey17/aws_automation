"""Unit tests for FastAPI project detector."""

from __future__ import annotations

from pathlib import Path

import pytest

from aideploy.detector.fastapi import detect_project


@pytest.mark.unit
class TestFastAPIDetector:
    """Tests for deterministic project detection."""

    def test_detect_project_with_requirements_txt(self, sample_fastapi_project: Path) -> None:
        info = detect_project(sample_fastapi_project)
        assert info is not None
        assert info.framework == "fastapi"
        assert info.entrypoint == "app.main:app"
        assert "OPENAI_API_KEY" in info.detected_env_vars
        assert info.has_requirements_txt is True

    def test_detect_project_with_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myapi"\ndependencies = ["fastapi>=0.100"]\n',
            encoding="utf-8",
        )
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n",
            encoding="utf-8",
        )
        info = detect_project(tmp_path)
        assert info is not None
        assert info.framework == "fastapi"
        assert info.entrypoint == "main:app"
        assert info.has_pyproject_toml is True

    def test_detect_project_without_fastapi(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
        info = detect_project(tmp_path)
        assert info is None

    def test_detect_project_ast_import_fallback(self, tmp_path: Path) -> None:
        # No requirements.txt or pyproject.toml, but source imports FastAPI
        (tmp_path / "server.py").write_text(
            "import fastapi\napp = fastapi.FastAPI()\n",
            encoding="utf-8",
        )
        info = detect_project(tmp_path)
        assert info is not None
        assert info.framework == "fastapi"
        assert info.entrypoint == "server:app"

    def test_detect_python_version_file(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        (tmp_path / ".python-version").write_text("3.11.5\n", encoding="utf-8")
        info = detect_project(tmp_path)
        assert info is not None
        assert info.python_version == "3.11"
