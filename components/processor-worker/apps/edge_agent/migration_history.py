"""Canonical migration-history helpers shared by legacy runtime gates.

Each command continues accepting the oldest schema generation it owns and every
canonical successor through the current head. Keeping the sequences in one place
prevents a new migration from silently making an older command reject a valid
newer database.
"""

from __future__ import annotations

import sqlite3

CANONICAL_HISTORY: tuple[tuple[int, str], ...] = (
    (1, "repository_foundation"),
    (2, "ledger_and_outbox"),
    (3, "crash_reconciliation"),
    (4, "derived_processing"),
    (5, "mobile_recording_import"),
    (6, "rtsp_capture"),
    (7, "multi_source_occurrence_assertions"),
    (8, "enforce_occurrence_assertion_cycle"),
    (9, "verified_replication"),
    (10, "provider_neutral_replication_targets"),
)


def recorded_history(connection: sqlite3.Connection) -> tuple[tuple[int, str], ...]:
    return tuple(
        (int(version), str(name))
        for version, name in connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    )


def accepts_from(
    connection: sqlite3.Connection,
    minimum_version: int,
) -> bool:
    """Return true for any exact canonical prefix from ``minimum_version`` to head."""

    recorded = recorded_history(connection)
    return any(
        recorded == CANONICAL_HISTORY[:version]
        for version in range(minimum_version, len(CANONICAL_HISTORY) + 1)
    )
