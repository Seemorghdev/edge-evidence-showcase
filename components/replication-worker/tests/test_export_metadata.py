"""Self-consistency, privacy, and vocabulary checks for generated metadata."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import stat
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "EXPORT_PROVENANCE.json"
ALLOWED_PROVENANCE_KEYS = {
    "schema_version",
    "exporter_version",
    "component",
    "product_policy",
    "public_source_label",
    "candidate_path_count",
    "candidate_content_tree_sha256",
    "public_license",
    "dependency_boundary",
    "verification_commands",
}
_PROGRAMME_PATTERNS = {
    "numbered-project-label": re.compile(r"\bproject" + r"[\s_-]*0?3\b", re.I),
    "private-milestone-label": re.compile(r"\bp" + r"03a(?:-r1)?\b", re.I),
    "private-wave-label": re.compile(r"\bwave" + r"[\s_-]+[abc]\b", re.I),
    "private-spec-label": re.compile(r"\bspec" + r"-\d{3,}\b", re.I),
}
_IGNORED_PARTS = {
    ".git",
    ".demo-output",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_digest(files: dict[str, tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        mode, data = files[path]
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(mode.encode())
        digest.update(b"\0")
        digest.update(_sha(data).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _candidate_files() -> dict[str, tuple[str, bytes]]:
    result: dict[str, tuple[str, bytes]] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(
            part in _IGNORED_PARTS or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        mode = "100755" if stat.S_IMODE(path.stat().st_mode) & 0o111 else "100644"
        result[relative.as_posix()] = (mode, path.read_bytes())
    return result


def _scan_text(text: str, relative: str, start_line: int = 1) -> list[str]:
    findings: list[str] = []
    for offset, line in enumerate(text.splitlines() or [text]):
        for rule, pattern in _PROGRAMME_PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{relative}:{start_line + offset}:{rule}")
    return findings


def _python_docstrings(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    result: list[tuple[int, str]] = []
    node_types = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, node_types) or not node.body:
            continue
        first = node.body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            result.append((getattr(first, "lineno", 1), value.value))
    return result


def _public_vocabulary_findings() -> list[str]:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(ROOT)
        if any(
            part in _IGNORED_PARTS or part.endswith(".egg-info")
            for part in relative_path.parts
        ):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = relative_path.as_posix()
        if path.suffix == ".py":
            for line_number, docstring in _python_docstrings(text):
                findings.extend(_scan_text(docstring, relative, line_number))
        else:
            findings.extend(_scan_text(text, relative))
    return findings


def _provenance() -> dict[str, object]:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def test_public_provenance_is_exact_and_source_redacted() -> None:
    provenance = _provenance()
    assert set(provenance) == ALLOWED_PROVENANCE_KEYS
    assert provenance["schema_version"] == 2
    assert provenance["exporter_version"] == 2
    assert provenance["component"] == "replication-worker"
    assert provenance["product_policy"] == "generated-product/upstream-first"
    assert provenance["public_source_label"] == (
        "private canonical source (identity withheld)"
    )
    assert provenance["public_license"] == "MIT"
    assert "canonical_repository" not in provenance
    assert "canonical_commit" not in provenance
    assert "descriptor" not in provenance
    assert "exporter" not in provenance
    assert "projected_files" not in provenance
    assert "generated_files" not in provenance
    assert "publication_authorized" not in provenance


def test_provenance_covers_exact_candidate_tree_and_boundary_digest() -> None:
    provenance = _provenance()
    files = _candidate_files()
    assert provenance["candidate_path_count"] == len(files)
    without_provenance = {
        path: value for path, value in files.items() if path != "EXPORT_PROVENANCE.json"
    }
    assert _tree_digest(without_provenance) == provenance[
        "candidate_content_tree_sha256"
    ]
    boundary = provenance["dependency_boundary"]
    assert boundary["path"] == "DEPENDENCY_BOUNDARY.md"
    assert boundary["sha256"] == _sha((ROOT / boundary["path"]).read_bytes())
    assert provenance["verification_commands"] == [
        "python -m compileall -q apps packages demo",
        "python -m pytest -q",
    ]


def test_public_candidate_uses_product_vocabulary() -> None:
    assert _public_vocabulary_findings() == []


def test_projection_closes_runtime_tests_demo_and_security_boundary() -> None:
    for required in (
        "apps/replication_worker/cli.py",
        "packages/database/migrations.py",
        "packages/database/replication_target_migration_v10.py",
        "packages/replication/core/worker.py",
        "packages/replication/adapters/nfs/target.py",
        "packages/replication/adapters/gcs/target.py",
        "packages/replication/model.py",
        "tests/unit/test_replication_gcs.py",
        "tests/unit/test_replication_target_config.py",
        "tests/unit/test_replication_target_contract.py",
        "README.md",
        "SECURITY.md",
        ".devcontainer/Dockerfile",
        ".devcontainer/devcontainer.json",
        "Makefile",
        "demo/run_demo.py",
        "scripts/setup.sh",
        "scripts/inspect_demo.py",
        "tests/test_demo_experience.py",
        "tests/test_export_metadata.py",
        "tests/test_exported_integration.py",
    ):
        assert (ROOT / required).is_file()
    for forbidden in ("deploy", "infra", "acceptance"):
        assert not (ROOT / forbidden).exists()
    assert not any("azure" in path.name.lower() for path in ROOT.rglob("*"))

    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (security, contributing, readme):
        assert "GitHub Private Vulnerability Reporting" in text
        assert "GitHub Security Advisories" in text
    assert "No personal email address is published" in security
    assert "dedicated monitored" in security
    assert "public issue" in security
    assert "Product role" in readme


def test_public_package_keeps_gcs_optional_and_exact() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "edge-evidence-replication-worker"
    assert config["project"]["requires-python"] == ">=3.11"
    assert config["project"]["dependencies"] == []
    assert config["project"]["optional-dependencies"]["gcs"] == [
        "google-cloud-storage==3.13.0"
    ]
    assert config["project"]["optional-dependencies"]["dev"] == [
        "pytest>=8,<9"
    ]
    assert config["project"]["scripts"]["replication-worker"] == (
        "apps.replication_worker.cli:main"
    )


def test_dependency_boundary_has_no_private_platform_roots() -> None:
    text = (ROOT / "DEPENDENCY_BOUNDARY.md").read_text(encoding="utf-8")
    forbidden = (
        "`deploy/",
        "`infra/",
        "`acceptance" + "/evidence/",
        "service" + "_account_file",
        "client" + "_secret",
        "private" + "_key",
        "azure",
    )
    for item in forbidden:
        assert item not in text.lower()


def test_mit_license_does_not_authorize_publication() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert config["project"]["license"] == {"text": "MIT"}
    assert _provenance()["public_license"] == "MIT"
    assert license_text.startswith("MIT License\n\nCopyright (c) 2026 Seemorgh\n")
    assert "publish-check` remain fail-closed" in (
        ROOT / "README.md"
    ).read_text(encoding="utf-8")
