import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_engine.models import Candidate, HistoricalDataMetadata, Horizon, ResearchSignal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalRepository:
    """SQLite repository for independent quant research records."""

    def __init__(self, database_path: str) -> None:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                horizon TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                signal_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS scan_candidates (
                scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                candidate_json TEXT NOT NULL,
                PRIMARY KEY (scan_id, symbol)
            );
            CREATE TABLE IF NOT EXISTS historical_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                bar_size TEXT NOT NULL,
                duration TEXT NOT NULL,
                use_rth INTEGER NOT NULL,
                bar_count INTEGER NOT NULL,
                start_time TEXT,
                end_time TEXT,
                UNIQUE (scan_id, symbol)
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                horizon TEXT NOT NULL,
                current_price REAL NOT NULL,
                direction TEXT NOT NULL,
                score INTEGER NOT NULL,
                explanation TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS signals_created_idx ON signals(created_at DESC);
            CREATE TABLE IF NOT EXISTS indicator_values (
                signal_id INTEGER NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                value_json TEXT NOT NULL,
                PRIMARY KEY (signal_id, name)
            );
            """
        )
        self._connection.commit()

    def healthy(self) -> bool:
        return self._connection.execute("SELECT 1").fetchone()[0] == 1

    def begin_scan(self, horizon: Horizon) -> int:
        cursor = self._connection.execute(
            "INSERT INTO scans (horizon, started_at, status) VALUES (?, ?, 'running')",
            (horizon.value, _now()),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def save_candidates(self, scan_id: int, candidates: list[Candidate]) -> None:
        self._connection.executemany(
            "INSERT OR REPLACE INTO scan_candidates (scan_id, symbol, candidate_json) VALUES (?, ?, ?)",
            [
                (scan_id, candidate.symbol, candidate.model_dump_json())
                for candidate in candidates
            ],
        )
        self._connection.commit()

    def save_result(
        self,
        scan_id: int,
        metadata: HistoricalDataMetadata,
        signal: ResearchSignal,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO historical_data
                    (scan_id, symbol, bar_size, duration, use_rth, bar_count, start_time, end_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    metadata.symbol,
                    metadata.bar_size,
                    metadata.duration,
                    int(metadata.use_rth),
                    metadata.bar_count,
                    metadata.start_time.isoformat() if metadata.start_time else None,
                    metadata.end_time.isoformat() if metadata.end_time else None,
                ),
            )
            cursor = self._connection.execute(
                """
                INSERT INTO signals
                    (scan_id, symbol, timestamp, horizon, current_price, direction,
                     score, explanation, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    signal.symbol,
                    signal.timestamp.isoformat(),
                    signal.horizon.value,
                    signal.current_price,
                    signal.direction,
                    signal.score,
                    signal.explanation,
                    _now(),
                ),
            )
            self._connection.executemany(
                "INSERT INTO indicator_values (signal_id, name, value_json) VALUES (?, ?, ?)",
                [
                    (cursor.lastrowid, name, json.dumps(value, allow_nan=False))
                    for name, value in signal.indicators.items()
                ],
            )

    def finish_scan(
        self,
        scan_id: int,
        *,
        status: str,
        candidate_count: int,
        signal_count: int,
        failure_count: int,
    ) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("Invalid scan status.")
        self._connection.execute(
            """
            UPDATE scans
            SET completed_at = ?, status = ?, candidate_count = ?,
                signal_count = ?, failure_count = ?
            WHERE id = ?
            """,
            (_now(), status, candidate_count, signal_count, failure_count, scan_id),
        )
        self._connection.commit()

    def list_signals(
        self, horizon: Horizon | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if horizon:
            rows = self._connection.execute(
                """
                SELECT signals.*, scans.id AS stored_scan_id
                FROM signals JOIN scans ON scans.id = signals.scan_id
                WHERE signals.horizon = ?
                ORDER BY signals.created_at DESC LIMIT ?
                """,
                (horizon.value, limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT signals.*, scans.id AS stored_scan_id
                FROM signals JOIN scans ON scans.id = signals.scan_id
                ORDER BY signals.created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            indicators = self._connection.execute(
                "SELECT name, value_json FROM indicator_values WHERE signal_id = ?",
                (row["id"],),
            ).fetchall()
            result.append(
                {
                    "scan_id": row["stored_scan_id"],
                    "symbol": row["symbol"],
                    "timestamp": row["timestamp"],
                    "horizon": row["horizon"],
                    "current_price": row["current_price"],
                    "indicators": {
                        item["name"]: json.loads(item["value_json"])
                        for item in indicators
                    },
                    "direction": row["direction"],
                    "score": row["score"],
                    "explanation": row["explanation"],
                    "created_at": row["created_at"],
                }
            )
        return result

    def close(self) -> None:
        self._connection.close()
