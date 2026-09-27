"""FastAPI project detector.

Inspects the current directory to determine whether it is a FastAPI project,
identify the application entrypoint, Python version, and environment variables.

Detection is purely deterministic — no LLM is used.
"""

from __future__ import annotations

import ast
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ProjectInfo:
    """Structured result from FastAPI project detection."""

    framework: str  # always "fastapi" for now
    python_version: str
    entrypoint: str | None
    entrypoint_file: Path | None
    detected_env_vars: list[str] = field(default_factory=list)
    has_dockerfile: bool = False
    has_requirements_txt: bool = False
    has_pyproject_toml: bool = False
    warnings: list[str] = field(default_factory=list)


def detect_project(project_dir: Path | None = None) -> ProjectInfo | None:
    """Detect whether *project_dir* contains a FastAPI project.

    Returns:
        ProjectInfo if FastAPI is detected, None otherwise.
    """
    directory = project_dir or Path.cwd()

    has_fastapi = _has_fastapi_dependency(directory)
    if not has_fastapi:
        logger.debug("FastAPI not found in dependencies")
        return None

    entrypoint, entrypoint_file = _find_entrypoint(directory)
    env_vars = _detect_env_vars(directory)
    python_ver = _detect_python_version(directory)

    info = ProjectInfo(
        framework="fastapi",
        python_version=python_ver,
        entrypoint=entrypoint,
        entrypoint_file=entrypoint_file,
        detected_env_vars=env_vars,
        has_dockerfile=(directory / "Dockerfile").exists(),
        has_requirements_txt=(directory / "requirements.txt").exists(),
        has_pyproject_toml=(directory / "pyproject.toml").exists(),
    )

    if entrypoint is None:
        info.warnings.append(
            "Could not auto-detect the FastAPI entrypoint. "
            "Set app.entrypoint manually in aideploy.yaml."
        )

    logger.debug("Detected project: %s", info)
    return info


# ── Dependency detection ───────────────────────────────────────────────────────


def _has_fastapi_dependency(directory: Path) -> bool:
    """Return True if FastAPI is declared as a dependency or imported."""
    if _check_requirements_txt(directory):
        return True
    if _check_pyproject_toml(directory):
        return True
    if _check_source_imports(directory):
        return True
    return False


def _check_requirements_txt(directory: Path) -> bool:
    req = directory / "requirements.txt"
    if not req.exists():
        return False
    text = req.read_text(encoding="utf-8", errors="replace").lower()
    return bool(re.search(r"^\s*fastapi\b", text, re.MULTILINE))


def _check_pyproject_toml(directory: Path) -> bool:
    pp = directory / "pyproject.toml"
    if not pp.exists():
        return False
    text = pp.read_text(encoding="utf-8", errors="replace").lower()
    return "fastapi" in text


def _check_source_imports(directory: Path) -> bool:
    """Scan Python source files for FastAPI imports (max depth 3)."""
    for py_file in _iter_python_files(directory, max_depth=3):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            if "fastapi" in source.lower():
                if _ast_imports_fastapi(source):
                    return True
        except OSError:
            continue
    return False


def _ast_imports_fastapi(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fall back to text search
        return bool(re.search(r"\bfrom\s+fastapi\b|\bimport\s+fastapi\b", source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "fastapi" or node.module.startswith("fastapi.")
            ):
                return True
    return False


# ── Entrypoint detection ───────────────────────────────────────────────────────


_COMMON_ENTRYPOINTS = [
    ("main", "app"),
    ("app", "app"),
    ("app.main", "app"),
    ("api.main", "app"),
    ("src.main", "app"),
    ("server", "app"),
    ("application", "app"),
    ("api", "app"),
]


def _find_entrypoint(directory: Path) -> tuple[str | None, Path | None]:
    """Try to find the FastAPI app object in common locations."""
    for module_path, attr in _COMMON_ENTRYPOINTS:
        file_path = _module_to_file(directory, module_path)
        if file_path and file_path.exists():
            if _file_has_fastapi_app(file_path, attr):
                entrypoint = f"{module_path}:{attr}"
                logger.debug("Found entrypoint: %s in %s", entrypoint, file_path)
                return entrypoint, file_path

    # Broader scan: any Python file that creates FastAPI()
    for py_file in _iter_python_files(directory, max_depth=3):
        if _file_has_fastapi_app(py_file, "app"):
            rel = py_file.relative_to(directory)
            module = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
            entrypoint = f"{module}:app"
            logger.debug("Found entrypoint via scan: %s", entrypoint)
            return entrypoint, py_file

    return None, None


def _module_to_file(directory: Path, module_path: str) -> Path | None:
    """Convert a dotted module path to a filesystem path."""
    relative = Path(module_path.replace(".", "/"))
    candidates = [
        directory / relative.with_suffix(".py"),
        directory / relative / "__init__.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _file_has_fastapi_app(file_path: Path, attr: str) -> bool:
    """Return True if *file_path* assigns a FastAPI() instance to *attr*."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    # Quick text filter before AST parsing
    if "FastAPI" not in source:
        return False

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fallback: regex
        return bool(
            re.search(
                rf"\b{re.escape(attr)}\s*=\s*FastAPI\s*\(",
                source,
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == attr:
                    if _is_fastapi_call(node.value):
                        return True
    return False


def _is_fastapi_call(node: ast.expr) -> bool:
    """Return True if the AST node represents a FastAPI() constructor call."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "FastAPI":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "FastAPI":
            return True
    return False


# ── Python version detection ───────────────────────────────────────────────────


def _detect_python_version(directory: Path) -> str:
    """Detect the Python version from project metadata or the running interpreter."""
    # Try .python-version file
    pv = directory / ".python-version"
    if pv.exists():
        version = pv.read_text(encoding="utf-8").strip()
        if re.match(r"^\d+\.\d+", version):
            return version.split(".")[:2]  # type: ignore[return-value]
            return ".".join(version.split(".")[:2])

    # Try pyproject.toml requires-python
    pp = directory / "pyproject.toml"
    if pp.exists():
        text = pp.read_text(encoding="utf-8")
        match = re.search(r'requires-python\s*=\s*">=?\s*(\d+\.\d+)', text)
        if match:
            return match.group(1)

    # Fall back to running interpreter
    return f"{sys.version_info.major}.{sys.version_info.minor}"


# ── Env var detection ──────────────────────────────────────────────────────────


def _detect_env_vars(directory: Path) -> list[str]:
    """Scan source for os.getenv / os.environ references to suggest env vars."""
    found: set[str] = set()
    pattern = re.compile(
        r'os\.(?:getenv|environ\.get)\s*\(\s*["\']([A-Z][A-Z0-9_]*)["\']'
    )
    for py_file in _iter_python_files(directory, max_depth=3):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            for match in pattern.finditer(source):
                found.add(match.group(1))
        except OSError:
            continue
    return sorted(found)


# ── Filesystem utilities ───────────────────────────────────────────────────────


_EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__",
    "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "dist", "build", ".aideploy",
}


def _iter_python_files(directory: Path, max_depth: int = 3) -> list[Path]:
    """Yield Python files up to *max_depth* levels deep, skipping excluded dirs."""
    results: list[Path] = []
    _collect(directory, results, 0, max_depth)
    return results


def _collect(path: Path, results: list[Path], depth: int, max_depth: int) -> None:
    if depth > max_depth:
        return
    try:
        for child in path.iterdir():
            if child.is_dir():
                if child.name not in _EXCLUDE_DIRS:
                    _collect(child, results, depth + 1, max_depth)
            elif child.suffix == ".py":
                results.append(child)
    except PermissionError:
        pass
