"""Committed-Git identity for the exact replication action implementation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import ClassVar

from packages.agent_contracts.canonical import canonical_sha256
from packages.replication.contracts.model import ReplicationError

CANONICAL_REPOSITORY_HOST = "github.com"
CANONICAL_REPOSITORY_ID = "1322525566"
CANONICAL_REPOSITORY_FULL_NAME = "private-redacted"
ACCEPTED_PLAN_COMMIT = "da587e63ca4e5669afe89fa7cf24601c41b37d4d"
ACCEPTED_PLAN_TREE = "bee049769fdadb2442d427cf9cac1ad218c88d6a"
ACCEPTED_PLAN_DOCUMENT_PATH = "docs/architecture/REPLICATION-ACTION-PLAN.md"
ACCEPTED_PLAN_DOCUMENT_BLOB_SHA = "96a2621f089f2b00a1583584b445c7e9f78a4cf5"

ACTION_ENTRYPOINTS = (
    "packages.replication.action.verifier.verify_exact_action",
    "packages.replication.action.workflow.run_exact_action",
)
IMPORT_CLOSURE_ROOTS = (
    "apps.replication_worker.target_config",
    "packages.replication.action.verifier",
    "packages.replication.action.workflow",
    "packages.replication.adapters.gcs.target",
    "packages.replication.adapters.nfs.target",
    "packages.replication.core.worker",
)
DECLARED_IMPORT_CLOSURE_PATHS = (
    "apps/__init__.py",
    "apps/replication_worker/__init__.py",
    "apps/replication_worker/target_config.py",
    "packages/__init__.py",
    "packages/agent_contracts/__init__.py",
    "packages/agent_contracts/canonical.py",
    "packages/agent_contracts/model.py",
    "packages/agent_contracts/policy.py",
    "packages/agent_contracts/processor.py",
    "packages/agent_contracts/replication.py",
    "packages/database/__init__.py",
    "packages/database/migrations.py",
    "packages/database/replication_target_migration_v10.py",
    "packages/replication/__init__.py",
    "packages/replication/action/__init__.py",
    "packages/replication/action/implementation_identity.py",
    "packages/replication/action/manifest.py",
    "packages/replication/action/projections.py",
    "packages/replication/action/receipt.py",
    "packages/replication/action/verifier.py",
    "packages/replication/action/worker_adapter.py",
    "packages/replication/action/workflow.py",
    "packages/replication/adapters/__init__.py",
    "packages/replication/adapters/gcs/__init__.py",
    "packages/replication/adapters/gcs/model.py",
    "packages/replication/adapters/gcs/target.py",
    "packages/replication/adapters/nfs/__init__.py",
    "packages/replication/adapters/nfs/filesystem.py",
    "packages/replication/adapters/nfs/inspection.py",
    "packages/replication/adapters/nfs/model.py",
    "packages/replication/adapters/nfs/target.py",
    "packages/replication/contracts/__init__.py",
    "packages/replication/contracts/model.py",
    "packages/replication/contracts/target.py",
    "packages/replication/core/__init__.py",
    "packages/replication/core/authority.py",
    "packages/replication/core/source.py",
    "packages/replication/core/worker.py",
    "packages/replication/model.py",
    "packages/replication/worker.py",
)
DECLARED_IMPORT_CLOSURE_PATH_SET_SHA256 = (
    "f9f37fd7ed2f6db83354381194f78a75d4cec5599c0ff5e226c82fef63a47885"
)
DEFERRED_IMPORT_ALLOWLIST_RECORD = {
    "schema": "replication-action-deferred-import-allowlist.v1",
    "records": ({
        "importing_path": "apps/replication_worker/target_config.py",
        "enclosing_function": "_gcs_target",
        "imported_module": "packages.replication.adapters.gcs.target",
        "resolved_target_path": "packages/replication/adapters/gcs/target.py",
        "reason": "preserve optional GCS SDK loading until a GCS target is requested while keeping base and mounted-NFS configuration imports SDK-free",
    },),
}
DEFERRED_IMPORT_ALLOWLIST_SHA256 = (
    "6983e6fedb3c2b4097479e779213f2080a0c1363b706917e1b1dbe629656e306"
)
PERMITTED_EXTERNAL_IMPORT_ROOTS = frozenset({
    "__future__", "ast", "dataclasses", "enum", "errno", "google", "hashlib",
    "json", "os", "pathlib", "re", "sqlite3", "stat", "subprocess", "tempfile",
    "threading", "tomllib", "typing",
})
EXACT_IMPORT_RECORD_COUNT = 215
EXACT_IMPORT_RECORD_SET_SHA256 = (
    "d4324307df06331e98c5cdd0e56264c46db6e8b0b8f530daca5516723fc631a4"
)
EXACT_PROCESS_CALL_RECORD_COUNT = 2
EXACT_PROCESS_CALL_RECORD_SET_SHA256 = (
    "e53e36c47b9946d5c80afdab64274c185ce896eab09dce815accaa2e99968fd5"
)
PROCESS_LAUNCH_NAMES = frozenset({
    "system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe", "execl", "execle",
    "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "Popen", "call", "check_call", "check_output", "posix_spawn",
    "posix_spawnp", "fork", "forkpty", "startfile", "getoutput",
    "getstatusoutput",
})


def _git(repository: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if check and completed.returncode != 0:
        raise ReplicationError("implementation_identity_unavailable", code=7)
    return completed.stdout.strip()


def _normalized_origin(value: str) -> str:
    value = value.removesuffix(".git").removesuffix("/")
    if value.startswith("git@github.com:"):
        return "https://github.com/" + value.removeprefix("git@github.com:")
    if value.startswith("ssh://git@github.com/"):
        return "https://github.com/" + value.removeprefix("ssh://git@github.com/")
    return value


def _module_index(paths: tuple[str, ...]) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in paths:
        if not path.endswith(".py"):
            continue
        module = path[:-3].replace("/", ".")
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        index[module] = path
    return index


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return None


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return None if left is None or right is None else left + right
    return None


def _absolute_from_module(path: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    current = path[:-3].replace("/", ".")
    package = current.removesuffix(".__init__") if current.endswith(".__init__") else current.rsplit(".", 1)[0]
    parts = package.split(".") if package else []
    ascend = node.level - 1
    if ascend > len(parts):
        return ""
    prefix = parts[: len(parts) - ascend]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _package_init_targets(module: str, index: dict[str, str]) -> set[str]:
    result: set[str] = set()
    parts = module.split(".")
    for length in range(1, len(parts)):
        target = index.get(".".join(parts[:length]))
        if target is not None:
            result.add(target)
    return result


def _import_targets(path: str, node: ast.Import | ast.ImportFrom, index: dict[str, str]) -> set[str]:
    modules: set[str] = set()
    if isinstance(node, ast.Import):
        modules.update(alias.name for alias in node.names)
    else:
        base = _absolute_from_module(path, node)
        if base:
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    targets: set[str] = set()
    for module in modules:
        if not module.startswith(("apps", "packages")):
            continue
        target = index.get(module)
        if target is not None:
            targets.add(target)
        targets.update(_package_init_targets(module, index))
    return targets


def _validate_exact_commit_import_policy(
    repository: Path,
    implementation_commit: str,
) -> None:
    if canonical_sha256({
        "schema": "replication-action-import-closure-paths.v1",
        "paths": DECLARED_IMPORT_CLOSURE_PATHS,
        "path_count": len(DECLARED_IMPORT_CLOSURE_PATHS),
    }) != DECLARED_IMPORT_CLOSURE_PATH_SET_SHA256:
        raise ReplicationError("implementation_drift", code=7)
    if canonical_sha256(DEFERRED_IMPORT_ALLOWLIST_RECORD) != DEFERRED_IMPORT_ALLOWLIST_SHA256:
        raise ReplicationError("implementation_drift", code=7)

    index = _module_index(DECLARED_IMPORT_CLOSURE_PATHS)
    edges: dict[str, set[str]] = {}
    deferred: set[tuple[str, str, str, str]] = set()
    exact_import_records = []
    exact_process_call_records = []
    dangerous_attributes = {
        "import_module", "run_module", "run_path", "find_spec", "spec_from_file_location",
        "module_from_spec", "create_module", "exec_module", "load_module", "walk_packages",
        "__dict__", "__globals__", "__getattribute__", "modules", "mro",
        "__subclasses__", "__class__", "__bases__", "f_globals", "gi_frame", "cr_frame",
        "__loader__", "__spec__", "__code__",
        "__self__",
        *PROCESS_LAUNCH_NAMES,
    }
    for path in DECLARED_IMPORT_CLOSURE_PATHS:
        source = _git(repository, "cat-file", "blob", f"{implementation_commit}:{path}")
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, UnicodeError) as exc:
            raise ReplicationError("implementation_drift", code=7) from exc
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        targets: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                exact_import_records.append((
                    path,
                    _enclosing_function(node, parents) or "",
                    "import" if isinstance(node, ast.Import) else "from",
                    "" if isinstance(node, ast.Import) else "." * node.level + (node.module or ""),
                    tuple((alias.name, alias.asname) for alias in node.names),
                ))
                imported = (
                    tuple(alias.name for alias in node.names)
                    if isinstance(node, ast.Import)
                    else ((_absolute_from_module(path, node),) if _absolute_from_module(path, node) else ())
                )
                external_roots = (
                    {alias.name.split(".", 1)[0] for alias in node.names}
                    if isinstance(node, ast.Import)
                    else (
                        {node.module.split(".", 1)[0]}
                        if node.level == 0 and node.module
                        else set()
                    )
                )
                if external_roots - PERMITTED_EXTERNAL_IMPORT_ROOTS - {"apps", "packages"}:
                    raise ReplicationError("dynamic_loading_forbidden", code=7)
                if (
                    isinstance(node, ast.Import)
                    and any(
                        alias.name in {"os", "subprocess"} and alias.asname is not None
                        for alias in node.names
                    )
                ) or (
                    isinstance(node, ast.ImportFrom)
                    and node.module in {"os", "subprocess"}
                    and any(
                        alias.name in PROCESS_LAUNCH_NAMES
                        or (node.module == "subprocess" and alias.name == "run")
                        for alias in node.names
                    )
                ):
                    raise ReplicationError("dynamic_loading_forbidden", code=7)
                imports_builtin_loader = (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "builtins"
                    and any(alias.name in {"__import__", "exec", "eval"} for alias in node.names)
                )
                if imports_builtin_loader or any(
                    name == "builtins"
                    or name == "importlib"
                    or name.startswith("importlib.")
                    or name in {"runpy", "pkgutil", "sys", "inspect", "types"}
                    for name in imported
                ):
                    raise ReplicationError("dynamic_loading_forbidden", code=7)
                resolved = _import_targets(path, node, index)
                targets.update(resolved)
                if resolved and node not in tree.body:
                    module = _absolute_from_module(path, node) if isinstance(node, ast.ImportFrom) else ""
                    symbol = node.names[0].name if len(node.names) == 1 else ""
                    target_path = index.get(module, "")
                    record = (path, _enclosing_function(node, parents) or "", module, target_path)
                    expected = (
                        "apps/replication_worker/target_config.py",
                        "_gcs_target",
                        "packages.replication.adapters.gcs.target",
                        "packages/replication/adapters/gcs/target.py",
                    )
                    parent = parents.get(node)
                    grandparent = parents.get(parent) if parent is not None else None
                    exact_ancestor_shape = (
                        isinstance(parent, ast.Try)
                        and parent.body == [node]
                        and isinstance(grandparent, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and grandparent.name == "_gcs_target"
                        and grandparent.body[0] is parent
                        and parents.get(grandparent) is tree
                    )
                    if (
                        record != expected
                        or symbol != "GcsTarget"
                        or node.names[0].asname is not None
                        or not exact_ancestor_shape
                    ):
                        raise ReplicationError("unapproved_deferred_repository_import", code=7)
                    deferred.add(record)
            if isinstance(node, ast.Name) and node.id in {
                "__builtins__", "__import__", "exec", "eval", "globals", "locals", "vars"
            }:
                raise ReplicationError("dynamic_loading_forbidden", code=7)
            if (
                isinstance(node, ast.Name)
                and node.id == "getattr"
                and not (
                    isinstance(parents.get(node), ast.Call)
                    and parents[node].func is node
                )
            ):
                raise ReplicationError("dynamic_loading_forbidden", code=7)
            if isinstance(node, ast.Attribute) and node.attr in {
                "__import__", "exec", "eval", *dangerous_attributes
            }:
                raise ReplicationError("dynamic_loading_forbidden", code=7)
            if isinstance(node, ast.Attribute) and node.attr == "run":
                parent = parents.get(node)
                if (
                    not isinstance(parent, ast.Call)
                    or parent.func is not node
                    or not isinstance(node.value, ast.Name)
                    or node.value.id != "subprocess"
                ):
                    raise ReplicationError("dynamic_loading_forbidden", code=7)
                if (
                    path != "packages/replication/action/implementation_identity.py"
                    or _enclosing_function(parent, parents)
                    not in {"_git", "reconstruct_implementation_identity"}
                    or not parent.args
                    or not isinstance(parent.args[0], ast.List)
                    or not parent.args[0].elts
                    or _static_string(parent.args[0].elts[0]) != "git"
                ):
                    raise ReplicationError("dynamic_loading_forbidden", code=7)
                exact_process_call_records.append((
                    path,
                    _enclosing_function(parent, parents) or "",
                    ast.dump(parent, include_attributes=False),
                ))
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and _static_string(node.args[1])
                    in {"__import__", "exec", "eval", *dangerous_attributes}
                ):
                    raise ReplicationError("dynamic_loading_forbidden", code=7)
        edges[path] = targets

    roots = {index[module] for module in IMPORT_CLOSURE_ROOTS}
    for module in IMPORT_CLOSURE_ROOTS:
        roots.update(_package_init_targets(module, index))
    observed: set[str] = set()
    pending = list(roots)
    while pending:
        path = pending.pop()
        if path in observed:
            continue
        observed.add(path)
        pending.extend(edges[path] - observed)
    expected_deferred = {(
        "apps/replication_worker/target_config.py",
        "_gcs_target",
        "packages.replication.adapters.gcs.target",
        "packages/replication/adapters/gcs/target.py",
    )}
    ordered_import_records = tuple(sorted(exact_import_records))
    if (
        len(ordered_import_records) != EXACT_IMPORT_RECORD_COUNT
        or canonical_sha256({
            "schema": "replication-action-exact-import-records.v1",
            "records": ordered_import_records,
            "record_count": len(ordered_import_records),
        }) != EXACT_IMPORT_RECORD_SET_SHA256
    ):
        raise ReplicationError("implementation_drift", code=7)
    ordered_process_call_records = tuple(sorted(exact_process_call_records))
    if (
        len(ordered_process_call_records) != EXACT_PROCESS_CALL_RECORD_COUNT
        or canonical_sha256({
            "schema": "replication-action-exact-process-call-records.v1",
            "records": ordered_process_call_records,
            "record_count": len(ordered_process_call_records),
        }) != EXACT_PROCESS_CALL_RECORD_SET_SHA256
    ):
        raise ReplicationError("dynamic_loading_forbidden", code=7)
    if observed != set(DECLARED_IMPORT_CLOSURE_PATHS) or deferred != expected_deferred:
        raise ReplicationError("implementation_drift", code=7)


@dataclass(frozen=True, order=True)
class ExecutionRelevantBlob:
    path: str
    mode: str
    blob_sha: str

    def __post_init__(self) -> None:
        if self.mode != "100644" or len(self.blob_sha) != 40:
            raise ReplicationError("implementation_identity_unavailable", code=7)


@dataclass(frozen=True)
class ImplementationIdentity:
    schema: ClassVar[str] = "replication-action-implementation-identity.v1"

    canonical_repository_host: str
    canonical_repository_id: str
    canonical_repository_full_name: str
    accepted_plan_commit: str
    accepted_plan_tree: str
    accepted_plan_document_path: str
    accepted_plan_document_blob_sha: str
    implementation_commit: str
    implementation_tree: str
    action_entrypoints: tuple[str, ...]
    import_closure_roots: tuple[str, ...]
    declared_import_closure_path_set_sha256: str
    execution_relevant_blob_count: int
    execution_relevant_blobs: tuple[ExecutionRelevantBlob, ...]
    execution_relevant_blob_set_sha256: str

    def __post_init__(self) -> None:
        if self.action_entrypoints != ACTION_ENTRYPOINTS:
            raise ReplicationError("implementation_drift", code=7)
        if self.import_closure_roots != IMPORT_CLOSURE_ROOTS:
            raise ReplicationError("implementation_drift", code=7)
        if self.execution_relevant_blob_count != 40:
            raise ReplicationError("implementation_drift", code=7)
        if tuple(sorted(self.execution_relevant_blobs)) != self.execution_relevant_blobs:
            raise ReplicationError("implementation_drift", code=7)
        if canonical_sha256(self.execution_relevant_blobs) != self.execution_relevant_blob_set_sha256:
            raise ReplicationError("implementation_drift", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


def reconstruct_implementation_identity(
    repository_root: Path,
    implementation_commit: str,
    *,
    trusted_repository_id: str,
) -> ImplementationIdentity:
    """Reconstruct identity exclusively from one exact committed Git tree."""

    repository = Path(repository_root).resolve()
    if trusted_repository_id != CANONICAL_REPOSITORY_ID:
        raise ReplicationError("implementation_repository_mismatch", code=7)
    origin = _normalized_origin(_git(repository, "remote", "get-url", "origin"))
    if origin != f"https://{CANONICAL_REPOSITORY_HOST}/{CANONICAL_REPOSITORY_FULL_NAME}":
        raise ReplicationError("implementation_repository_mismatch", code=7)
    if _git(repository, "cat-file", "-t", implementation_commit) != "commit":
        raise ReplicationError("implementation_identity_unavailable", code=7)
    implementation_tree = _git(repository, "rev-parse", f"{implementation_commit}^{{tree}}")
    if _git(repository, "rev-parse", f"{ACCEPTED_PLAN_COMMIT}^{{tree}}") != ACCEPTED_PLAN_TREE:
        raise ReplicationError("implementation_drift", code=7)
    if _git(repository, "rev-parse", f"{ACCEPTED_PLAN_COMMIT}:{ACCEPTED_PLAN_DOCUMENT_PATH}") != ACCEPTED_PLAN_DOCUMENT_BLOB_SHA:
        raise ReplicationError("implementation_drift", code=7)
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ACCEPTED_PLAN_COMMIT, implementation_commit],
        cwd=repository,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ancestry.returncode != 0:
        raise ReplicationError("implementation_drift", code=7)

    _validate_exact_commit_import_policy(repository, implementation_commit)

    blobs: list[ExecutionRelevantBlob] = []
    for path in DECLARED_IMPORT_CLOSURE_PATHS:
        record = _git(repository, "ls-tree", implementation_commit, "--", path)
        fields = record.split(None, 3)
        if len(fields) != 4 or fields[0] != "100644" or fields[1] != "blob":
            raise ReplicationError("implementation_identity_unavailable", code=7)
        blobs.append(ExecutionRelevantBlob(path=path, mode=fields[0], blob_sha=fields[2]))
    ordered = tuple(sorted(blobs))
    return ImplementationIdentity(
        canonical_repository_host=CANONICAL_REPOSITORY_HOST,
        canonical_repository_id=CANONICAL_REPOSITORY_ID,
        canonical_repository_full_name=CANONICAL_REPOSITORY_FULL_NAME,
        accepted_plan_commit=ACCEPTED_PLAN_COMMIT,
        accepted_plan_tree=ACCEPTED_PLAN_TREE,
        accepted_plan_document_path=ACCEPTED_PLAN_DOCUMENT_PATH,
        accepted_plan_document_blob_sha=ACCEPTED_PLAN_DOCUMENT_BLOB_SHA,
        implementation_commit=implementation_commit,
        implementation_tree=implementation_tree,
        action_entrypoints=ACTION_ENTRYPOINTS,
        import_closure_roots=IMPORT_CLOSURE_ROOTS,
        declared_import_closure_path_set_sha256=DECLARED_IMPORT_CLOSURE_PATH_SET_SHA256,
        execution_relevant_blob_count=len(ordered),
        execution_relevant_blobs=ordered,
        execution_relevant_blob_set_sha256=canonical_sha256(ordered),
    )
