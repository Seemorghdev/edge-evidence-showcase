from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", ".demo-output", ".pytest_cache", "build", "dist"}
_PROGRAMME_PATTERNS = (
    re.compile(r"\bproject[\s_-]*0?3\b", re.I),
    re.compile(r"\bp03a(?:-r1)?\b", re.I),
    re.compile(r"\bwave[\s_-]+[abc]\b", re.I),
    re.compile(r"\bspec-\d{3,}\b", re.I),
)
_IDENTITY_PATH = Path(
    "components/replication-worker/packages/replication/action/implementation_identity.py"
)
_IDENTITY_NAMES = {
    "ACCEPTED_PLAN_COMMIT",
    "ACCEPTED_PLAN_TREE",
    "ACCEPTED_PLAN_DOCUMENT_BLOB_SHA",
}
_FORTY_HEX = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")


def _files() -> list[Path]:
    return [
        path
        for path in sorted(ROOT.rglob("*"))
        if path.is_file()
        and not any(
            part in IGNORED or part.endswith(".egg-info")
            for part in path.relative_to(ROOT).parts
        )
        and path.suffix not in {".pyc", ".pyo"}
    ]


def _approved_component_identity_shas() -> set[str]:
    path = ROOT / _IDENTITY_PATH
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id in _IDENTITY_NAMES
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            values[target.id] = node.value.value
    assert set(values) == _IDENTITY_NAMES
    assert all(_FORTY_HEX.fullmatch(value) for value in values.values())
    return set(values.values())


def test_public_bundle_has_no_private_coordinates_or_secrets() -> None:
    text_by_path: dict[Path, str] = {}
    for path in _files():
        try:
            text_by_path[path.relative_to(ROOT)] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    text = "\n".join(text_by_path.values())
    patterns = (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"AIza[0-9A-Za-z_-]{30,}",
        r"ya29\.[0-9A-Za-z_-]+",
        r"g" + r"s://[^\s`]+",
        r"https://" + r"storage\.googleapis\.com/[^\s`]+",
        r"(?<!\d)10(?:\.\d{1,3}){3}(?!\d)",
        r"(?<!\d)192\.168(?:\.\d{1,3}){2}(?!\d)",
        r"/(?:home|Users|mnt)/[A-Za-z0-9._-]+/",
        re.escape("Seemorghdev/" + "edge-evidence-platform"),
    )
    for pattern in patterns:
        assert re.search(pattern, text) is None, pattern

    approved_identity_shas = _approved_component_identity_shas()
    for relative, content in text_by_path.items():
        observed = set(_FORTY_HEX.findall(content))
        allowed = approved_identity_shas | {"0" * 40} if relative == _IDENTITY_PATH else {"0" * 40}
        assert observed <= allowed, f"{relative}: {sorted(observed - allowed)}"


def test_public_bundle_uses_product_vocabulary() -> None:
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path.suffix == ".py":
            tree = ast.parse(text)
            strings: list[str] = []
            node_types = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            for node in ast.walk(tree):
                if not isinstance(node, node_types) or not node.body:
                    continue
                first = node.body[0]
                if not isinstance(first, ast.Expr):
                    continue
                value = first.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    strings.append(value.value)
            text = "\n".join(strings)
        for pattern in _PROGRAMME_PATTERNS:
            assert pattern.search(text) is None, f"{path}: {pattern.pattern}"


def test_showcase_orchestrator_does_not_import_worker_modules() -> None:
    source = (ROOT / "demo" / "run_showcase.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any(name == "apps" or name.startswith("apps.") for name in imported)
    assert not any(name == "packages" or name.startswith("packages.") for name in imported)
    assert "socket" not in imported
    assert "requests" not in imported
    assert "urllib" not in imported
    assert "os.environ[" not in source
    assert "os.getenv" not in source
