"""Standalone integration proof for the real shared-lock defer/catch-up boundary."""

from __future__ import annotations

import hashlib
import multiprocessing
import sqlite3
from pathlib import Path

import pytest

from apps.edge_agent import finalize, verification
from apps.processor_worker import worker
from packages.database.migrations import MIGRATIONS, migrate

_START = "2026-08-11T10:00:00Z"
_END = "2026-08-11T10:00:10Z"


def test_fresh_export_database_reaches_schema_v10(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    result = migrate(database)
    assert result.current_version == 10
    assert max(item.version for item in MIGRATIONS) == 10
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone() == (10,)


def _hold_shared_lock(spool_root: str, ready, release) -> None:
    from apps.edge_agent.lock import spool_lock

    with spool_lock(Path(spool_root), mode="shared"):
        ready.set()
        release.wait(20)


def _seed_fake_raw(database: Path, spool: Path) -> None:
    media = b"public-export-shared-lock-fixture"
    digest = hashlib.sha256(media).hexdigest()
    artifact_id = f"sha256:{digest}"
    source_id = "public-lock"
    media_path = spool / finalize.media_relative_path(digest)
    manifest_path = spool / finalize.manifest_relative_path(digest)
    media_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(media)
    manifest = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "source_id": source_id,
        "artifact_kind": "raw_media",
        "media_type": "video/mp4",
        "byte_size": len(media),
        "digest": {"algorithm": "sha256", "value": digest},
        "storage_uri": finalize.storage_uri(digest),
        "finalized_at": _END,
    }
    manifest_bytes = finalize.serialize_manifest(manifest)
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO artifacts (artifact_id, source_id, artifact_kind, media_type, "
            "byte_size, digest_algorithm, digest_value, storage_uri, manifest_uri, "
            "manifest_sha256, finalized_at) VALUES (?, ?, 'raw_media', 'video/mp4', ?, "
            "'sha256', ?, ?, ?, ?, ?)",
            (
                artifact_id,
                source_id,
                len(media),
                digest,
                finalize.storage_uri(digest),
                f"file:manifests/sha256/{digest[:2]}/{digest}.json",
                manifest_sha,
                _END,
            ),
        )
        connection.execute(
            "INSERT INTO expected_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, expected_started_at, expected_ended_at, state, artifact_id, "
            "terminal_at) VALUES ('occ-public-lock', ?, 'sess-public-lock', 1, ?, ?, "
            "'COMPLETE', ?, ?)",
            (source_id, _START, _END, artifact_id, _END),
        )
        connection.execute(
            "INSERT INTO capture_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, capture_started_at, capture_ended_at, artifact_id) "
            "VALUES ('occ-public-lock', ?, 'sess-public-lock', 1, ?, ?, ?)",
            (source_id, _START, _END, artifact_id),
        )
        connection.execute(
            "INSERT INTO capture_occurrence_assertions (occurrence_id, source_id, "
            "artifact_id, manifest_layout, manifest_uri, manifest_sha256, finalized_at) "
            "VALUES ('occ-public-lock', ?, ?, 'legacy_digest_v1', ?, ?, ?)",
            (
                source_id,
                artifact_id,
                f"file:manifests/sha256/{digest[:2]}/{digest}.json",
                manifest_sha,
                _END,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_real_shared_lock_defers_then_catches_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "authority.sqlite3"
    migrate(database)
    spool = tmp_path / "spool"
    spool.mkdir()
    _seed_fake_raw(database, spool)
    monkeypatch.setattr(verification, "require_tool", lambda name: None)
    monkeypatch.setattr(verification, "ffprobe_duration_seconds", lambda path: 10.0)

    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_shared_lock, args=(str(spool), ready, release))
    holder.start()
    try:
        assert ready.wait(5)
        blocked = worker.run(database, spool)
        assert blocked.status == "deferred"
        assert blocked.deferred == 1
        assert blocked.remaining == 1
    finally:
        release.set()
        holder.join(10)
        if holder.is_alive():
            holder.terminate()
            holder.join(5)
    assert holder.exitcode == 0

    caught_up = worker.run(database, spool)
    assert caught_up.status == "pass"
    assert caught_up.newly_completed == 1
    assert caught_up.remaining == 0
