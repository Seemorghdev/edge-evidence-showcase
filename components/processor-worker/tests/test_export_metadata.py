"""Self-consistency, privacy, vocabulary, and developer-experience checks."""

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
    ".venv",
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
    assert provenance["component"] == "processor-worker"
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


def test_processor_projection_closes_schema_and_security_boundary() -> None:
    assert (ROOT / "packages/database/migrations.py").is_file()
    assert (ROOT / "packages/database/replication_target_migration_v10.py").is_file()
    for forbidden in ("deploy", "infra", "acceptance"):
        assert not (ROOT / forbidden).exists()

    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (security, contributing, readme):
        normalized = " ".join(text.split())
        assert "GitHub Private Vulnerability Reporting" in normalized
        assert "GitHub Security Advisories" in normalized
    assert "No personal email address is published" in security
    assert "dedicated monitored" in security
    assert "public issue" in security


def test_build_backend_is_exact_and_runtime_dependency_free() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["build-system"] == {
        "requires": ["setuptools==82.0.1"],
        "build-backend": "setuptools.build_meta",
    }
    assert project["project"]["dependencies"] == []
    assert project["project"]["requires-python"] == ">=3.12"
    assert all(
        not item.lower().startswith("wheel")
        for item in project["build-system"]["requires"]
    )


def test_mit_license_is_exact_without_authorizing_publication() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert project["project"]["license"] == {"text": "MIT"}
    assert _provenance()["public_license"] == "MIT"
    assert license_text.startswith("MIT License\n\nCopyright (c) 2026 Seemorgh\n")
    assert "Permission is hereby granted, free of charge" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert "publish-check` remain fail-closed" in (
        ROOT / "README.md"
    ).read_text(encoding="utf-8")


def test_readme_freezes_product_role_and_reliability_proof() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Product role" in readme
    assert "MISSING" in readme
    assert "PREPARED" in readme
    assert "COMPLETE" in readme
    assert "standalone_synthetic_processing_reliability" in readme
    assert "schema version 10" in readme
    assert "Interruption and resume" in readme
    assert "Busy-lock behavior" in readme
    assert "Read-only ADK integration for inspecting and explaining processor state." in readme


def test_codespaces_make_and_setup_contract_is_present() -> None:
    required = {
        ".devcontainer/devcontainer.json",
        ".devcontainer/Dockerfile",
        ".dockerignore",
        ".gitignore",
        "Makefile",
        "scripts/setup.sh",
    }
    assert required.issubset(_candidate_files())
    assert stat.S_IMODE((ROOT / "scripts/setup.sh").stat().st_mode) & 0o111

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("demo", "test", "inspect", "clean"):
        assert re.search(rf"(?m)^{target}:\s*$", makefile)
    assert ".demo-output" in makefile

    container = json.loads(
        (ROOT / ".devcontainer/devcontainer.json").read_text(encoding="utf-8")
    )
    assert container["build"] == {"dockerfile": "Dockerfile", "context": ".."}
    assert container["postCreateCommand"] == "bash scripts/setup.sh"
    dockerfile = (ROOT / ".devcontainer/Dockerfile").read_text(encoding="utf-8")
    for tool in ("ffmpeg", "make", "sqlite3"):
        assert tool in dockerfile


def test_demo_uses_canonical_worker_checkpoint_and_lock_contracts() -> None:
    source = (ROOT / "demo/run_demo.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported.isdisjoint({"requests", "httpx", "urllib", "socket"})
    assert "apps.processor_worker.cli" in source
    assert "from apps.edge_agent import process" in source
    assert "from apps.edge_agent.lock import spool_lock" in source
    assert 'set_barrier("after_prepared_commit"' in source
    assert "os._exit(INTERRUPTED_EXIT)" in source


def test_generated_ci_covers_supported_versions_demo_and_image_build() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for expected in (
        'python-version: ["3.12", "3.14"]',
        "make test",
        "make demo",
        "make inspect",
        "docker build",
        ".devcontainer/Dockerfile",
        "actions/upload-artifact@v4",
        "Prove clean product installation",
        "Prove repeated deterministic output",
    ):
        assert expected in workflow
    assert ".demo-output/normal/receipt.json" in workflow
    assert ".demo-output/resume/receipt.json" in workflow
    assert ".demo-output/busy-lock/receipt.json" in workflow
