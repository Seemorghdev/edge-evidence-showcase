"""Public-safe replication target-composition contract tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from apps.replication_worker.cli import main as worker_main
from apps.replication_worker.target_config import load_target_config
from packages.replication.contracts.model import ReplicationError
from packages.replication.contracts.target import ReplicationTargetFactory

ROOT = Path(__file__).resolve().parents[2]


def _write_nfs_config(config: Path, root: Path) -> None:
    config.write_text(
        'adapter_kind = "mounted_nfs_v4"\n'
        'target_id = "nas-a"\n'
        f'target_root = "{root.as_posix()}"\n',
        encoding="utf-8",
    )


def _write_example_gcs_config(config: Path) -> None:
    config.write_text(
        'adapter_kind = "gcs"\n'
        'target_id = "gcs-example"\n'
        'bucket_name = "example-evidence-bucket"\n'
        'prefix = "example/prefix"\n',
        encoding="utf-8",
    )


def test_nfs_config_constructs_canonical_fresh_factory(tmp_path: Path) -> None:
    root = tmp_path / "replica"
    root.mkdir()
    config = tmp_path / "replication.toml"
    _write_nfs_config(config, root)

    selected = load_target_config(config)
    first = selected.factory.fresh()
    second = selected.factory.fresh()
    assert isinstance(selected.factory, ReplicationTargetFactory)
    assert selected.target_id == "nas-a"
    assert selected.composition.adapter_kind == "mounted_nfs_v4"
    assert selected.composition.location == {"root_realpath": root.resolve().as_posix()}
    assert len(selected.composition.sha256) == 64
    assert first is not second
    assert first.adapter_kind == "mounted_nfs_v4"
    assert first.root == root.resolve()
    assert selected.target is not selected.target


def test_nfs_composition_digest_is_stable(tmp_path: Path) -> None:
    root = tmp_path / "replica"
    root.mkdir()
    first_config = tmp_path / "a.toml"
    second_config = tmp_path / "b.toml"
    _write_nfs_config(first_config, root)
    _write_nfs_config(second_config, root)
    first = load_target_config(first_config)
    second = load_target_config(second_config)
    assert first.composition == second.composition
    assert first.composition.sha256 == second.composition.sha256


def test_public_safe_gcs_config_projects_deferred_adapter_without_provider_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "replication.toml"
    _write_example_gcs_config(config)

    provider_access_attempts: list[str] = []

    def reject_provider_access(*_args: object, **_kwargs: object) -> None:
        provider_access_attempts.append("attempted")
        raise AssertionError("provider access is forbidden during config projection")

    monkeypatch.setattr(os, "getenv", reject_provider_access)
    monkeypatch.setattr(Path, "home", reject_provider_access)
    monkeypatch.setattr(socket, "create_connection", reject_provider_access)
    monkeypatch.setattr(socket.socket, "connect", reject_provider_access)
    monkeypatch.setattr(subprocess, "Popen", reject_provider_access)

    google_modules_before = {
        name for name in sys.modules if name == "google" or name.startswith("google.")
    }
    selected = load_target_config(config)
    repeated = load_target_config(config)
    google_modules_after = {
        name for name in sys.modules if name == "google" or name.startswith("google.")
    }

    assert selected.target_id == "gcs-example"
    assert selected.composition.target_id == "gcs-example"
    assert selected.composition.adapter_kind == "gcs"
    assert selected.composition.location == {
        "bucket_name": "example-evidence-bucket",
        "prefix": "example/prefix",
    }
    assert set(selected.composition.location) == {"bucket_name", "prefix"}
    assert selected.composition == repeated.composition
    assert selected.composition.sha256 == repeated.composition.sha256
    assert len(selected.composition.sha256) == 64
    assert isinstance(selected.factory, ReplicationTargetFactory)
    assert callable(selected.factory.fresh)
    assert selected.factory.composition == selected.composition
    assert google_modules_after == google_modules_before
    assert provider_access_attempts == []


@pytest.mark.parametrize(
    "text",
    [
        'adapter_kind = "gcs"\ntarget_id = "gcs-example"\n'
        'bucket_name = "example-invalid-bucket"\n',
        'adapter_kind = "gcs"\ntarget_id = "gcs-example"\n'
        'bucket_name = "example-invalid-bucket"\nprefix = ""\n'
        'unexpected_field = "x"\n',
        'adapter_kind = "mounted_nfs_v4"\ntarget_id = "nas-a"\n'
        'target_root = "/srv/example"\nunexpected_field = "x"\n',
        'adapter_kind = "azure"\ntarget_id = "example"\n',
        'adapter_kind = "gcs"\ntarget_id = 7\n'
        'bucket_name = "example-invalid-bucket"\nprefix = ""\n',
        '[target]\nadapter_kind = "gcs"\ntarget_id = "gcs-example"\n'
        'bucket_name = "example-invalid-bucket"\nprefix = ""\n',
    ],
)
def test_unknown_missing_nested_or_unsupported_config_fails_closed(
    tmp_path: Path,
    text: str,
) -> None:
    config = tmp_path / "replication.toml"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ReplicationError) as exc:
        load_target_config(config)
    assert exc.value.finding == "target_config_invalid"
    assert exc.value.code == 2


@pytest.mark.parametrize("root_text", ("relative", "/tmp/../unsafe", "/tmp/./unsafe"))
def test_noncanonical_nfs_root_fails_closed(tmp_path: Path, root_text: str) -> None:
    config = tmp_path / "replication.toml"
    config.write_text(
        'adapter_kind = "mounted_nfs_v4"\n'
        'target_id = "nas-a"\n'
        f'target_root = "{root_text}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ReplicationError) as exc:
        load_target_config(config)
    assert exc.value.finding == "target_config_invalid"


def test_nfs_root_symlink_fails_closed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    config = tmp_path / "replication.toml"
    _write_nfs_config(config, link)
    with pytest.raises(ReplicationError) as exc:
        load_target_config(config)
    assert exc.value.finding == "target_config_invalid"


def test_malformed_config_cli_error_is_path_neutral(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "private-config-name.toml"
    config.write_text("not = [valid", encoding="utf-8")
    code = worker_main(
        [
            "verify",
            "--database",
            str(tmp_path / "db.sqlite3"),
            "--target-config",
            str(config),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert str(config) not in captured.out
    assert str(config) not in captured.err
    assert json.loads(captured.err) == {
        "finding": "target_config_invalid",
        "status": "error",
    }


def test_base_import_and_nfs_config_do_not_load_google_sdk(tmp_path: Path) -> None:
    root = tmp_path / "replica"
    root.mkdir()
    config = tmp_path / "replication.toml"
    _write_nfs_config(config, root)
    script = r"""
import importlib.abc
import sys
from pathlib import Path

class BlockGoogle(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "google" or fullname.startswith("google."):
            raise ModuleNotFoundError("blocked optional Google SDK", name=fullname)
        return None

sys.meta_path.insert(0, BlockGoogle())
from apps.replication_worker.target_config import load_target_config
selected = load_target_config(Path(sys.argv[1]))
assert selected.target_id == "nas-a"
assert selected.factory.fresh().adapter_kind == "mounted_nfs_v4"
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(config)],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_gcs_config_parses_without_sdk_and_fresh_reports_adapter_absence(
    tmp_path: Path,
) -> None:
    config = tmp_path / "replication.toml"
    _write_example_gcs_config(config)
    script = r"""
import importlib.abc
import sys
from pathlib import Path

class BlockGoogle(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "google" or fullname.startswith("google."):
            raise ModuleNotFoundError("blocked optional Google SDK", name=fullname)
        return None

sys.meta_path.insert(0, BlockGoogle())
from apps.replication_worker.target_config import load_target_config
from packages.replication.contracts.model import ReplicationError

selected = load_target_config(Path(sys.argv[1]))
assert selected.composition.location["bucket_name"] == "example-evidence-bucket"
try:
    selected.factory.fresh()
except ReplicationError as exc:
    assert exc.finding == "target_adapter_unavailable"
    assert exc.code == 2
else:
    raise AssertionError("fresh GCS target unexpectedly loaded without its optional SDK")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(config)],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
