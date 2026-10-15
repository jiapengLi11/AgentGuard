"""Shared, optionally durable request accounting for all guarded model roles.

Reservation units are a local cost estimate, not a bound on opaque cloud
tokenization or billing. A missing response keeps its full reservation charged.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path


class BudgetError(ValueError):
    """Constant codes only; never include request contents or credentials."""


class BudgetLedger:
    def __init__(self, path: Path | None = None):
        self._lock = threading.RLock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            str(path) if path is not None else ":memory:",
            timeout=5,
            isolation_level=None,
            check_same_thread=False,
        )
        self.durable = path is not None
        self.connection.execute("PRAGMA foreign_keys=ON")
        if self.durable:
            self.connection.execute("PRAGMA journal_mode=TRUNCATE")
            self.connection.execute("PRAGMA synchronous=EXTRA")
            if (
                self.connection.execute("PRAGMA journal_mode").fetchone()[0] != "truncate"
                or self.connection.execute("PRAGMA synchronous").fetchone()[0] != 3
            ):
                raise BudgetError("MODEL_BUDGET_STORAGE_INVALID")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS budget_scopes(
                id TEXT PRIMARY KEY, parent TEXT REFERENCES budget_scopes(id),
                max_requests INTEGER NOT NULL, max_units INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_reservations(
                id TEXT PRIMARY KEY, purpose TEXT NOT NULL, reserved INTEGER NOT NULL,
                status TEXT NOT NULL, reported_tokens INTEGER
            );
            CREATE TABLE IF NOT EXISTS budget_charges(
                ticket TEXT REFERENCES model_reservations(id),
                scope TEXT REFERENCES budget_scopes(id), units INTEGER NOT NULL,
                PRIMARY KEY(ticket, scope)
            );
            """
        )

    def close(self) -> None:
        with self._lock:
            self.connection.close()


class ModelBudget:
    def __init__(
        self,
        *,
        max_requests: int = 12,
        max_units: int = 200_000,
        ledger: BudgetLedger | None = None,
        scope: str = "root",
        parent: ModelBudget | None = None,
    ):
        if (
            type(max_requests) is not int
            or not 1 <= max_requests <= 100_000
            or type(max_units) is not int
            or not 1 <= max_units <= 10_000_000_000
            or not isinstance(scope, str)
            or not 1 <= len(scope) <= 128
            or not scope.isascii()
        ):
            raise BudgetError("MODEL_BUDGET_CONFIG_INVALID")
        self.ledger = parent.ledger if parent else ledger or BudgetLedger()
        self.scope = scope
        self.chain = (scope, *parent.chain) if parent else (scope,)
        expected = (parent.scope if parent else None, max_requests, max_units)
        with self.ledger._lock:
            connection = self.ledger.connection
            connection.execute(
                "INSERT OR IGNORE INTO budget_scopes VALUES(?,?,?,?)", (scope, *expected)
            )
            actual = connection.execute(
                "SELECT parent,max_requests,max_units FROM budget_scopes WHERE id=?", (scope,)
            ).fetchone()
            if actual != expected:
                raise BudgetError("MODEL_BUDGET_CONFIG_MISMATCH")

    def child(self, identifier: str, *, max_requests: int = 12, max_units: int = 200_000):
        return ModelBudget(
            scope=identifier, parent=self, max_requests=max_requests, max_units=max_units
        )

    def reserve(self, purpose: str, units: int) -> str:
        if purpose not in {"MAIN", "CLASSIFY", "ISOLATED_ANALYSIS", "SUBAGENT", "RECOVERY"}:
            raise BudgetError("MODEL_BUDGET_PURPOSE_INVALID")
        if type(units) is not int or units <= 0:
            raise BudgetError("MODEL_BUDGET_RESERVATION_INVALID")
        with self.ledger._lock:
            connection = self.ledger.connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                for scope in self.chain:
                    count, charged = connection.execute(
                        "SELECT count(*),coalesce(sum(units),0) FROM budget_charges WHERE scope=?",
                        (scope,),
                    ).fetchone()
                    max_requests, max_units = connection.execute(
                        "SELECT max_requests,max_units FROM budget_scopes WHERE id=?", (scope,)
                    ).fetchone()
                    if count >= max_requests:
                        raise BudgetError("MODEL_BUDGET_REQUESTS_EXHAUSTED")
                    if charged + units > max_units:
                        raise BudgetError("MODEL_BUDGET_UNITS_EXHAUSTED")
                ticket = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO model_reservations VALUES(?,?,?,'PENDING',NULL)",
                    (ticket, purpose, units),
                )
                connection.executemany(
                    "INSERT INTO budget_charges VALUES(?,?,?)",
                    [(ticket, scope, units) for scope in self.chain],
                )
                connection.execute("COMMIT")
                return ticket
            except (BudgetError, sqlite3.Error) as error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(error, BudgetError):
                    raise
                raise BudgetError("MODEL_BUDGET_STORAGE_FAILED") from None

    def settle(self, ticket: str, *, status: str, reported_tokens: int | None) -> None:
        if status not in {"RETURNED", "FAILED", "CANCELLED"} or (
            reported_tokens is not None
            and (type(reported_tokens) is not int or not 0 <= reported_tokens <= 1_000_000_000)
        ):
            raise BudgetError("MODEL_BUDGET_SETTLEMENT_INVALID")
        with self.ledger._lock:
            connection = self.ledger.connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT r.status FROM model_reservations r JOIN budget_charges c "
                    "ON c.ticket=r.id WHERE r.id=? AND c.scope=?",
                    (ticket, self.scope),
                ).fetchone()
                if row != ("PENDING",):
                    raise BudgetError("MODEL_BUDGET_SETTLEMENT_INVALID")
                connection.execute(
                    "UPDATE model_reservations SET status=?,reported_tokens=? WHERE id=?",
                    (status, reported_tokens, ticket),
                )
                # Unknown/cancelled/error usage is not silently refunded. Known usage
                # may exceed the estimate; charge it and reject subsequent requests.
                if reported_tokens is not None:
                    connection.execute(
                        "UPDATE budget_charges SET units=? WHERE ticket=?",
                        (reported_tokens, ticket),
                    )
                connection.execute("COMMIT")
            except (BudgetError, sqlite3.Error) as error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(error, BudgetError):
                    raise
                raise BudgetError("MODEL_BUDGET_STORAGE_FAILED") from None

    def view(self) -> dict:
        with self.ledger._lock:
            connection = self.ledger.connection
            max_requests, max_units = connection.execute(
                "SELECT max_requests,max_units FROM budget_scopes WHERE id=?", (self.scope,)
            ).fetchone()
            rows = connection.execute(
                "SELECT r.purpose,r.status,r.reported_tokens,c.units "
                "FROM model_reservations r JOIN budget_charges c ON c.ticket=r.id "
                "WHERE c.scope=?",
                (self.scope,),
            ).fetchall()
        charged = sum(row[3] for row in rows)
        return {
            "durable": self.ledger.durable,
            "max_requests": max_requests,
            "requests_reserved": len(rows),
            "remaining_requests": max(0, max_requests - len(rows)),
            "max_reservation_units": max_units,
            "charged_units": charged,
            "remaining_units": max(0, max_units - charged),
            "reported_tokens": sum(row[2] for row in rows if row[2] is not None),
            "unknown_usage_requests": sum(row[2] is None for row in rows),
            "pending_requests": sum(row[1] == "PENDING" for row in rows),
            "estimate_exceeded": charged > max_units,
            "accounting": "LOCAL_ESTIMATE_WITH_PROVIDER_REPORTED_USAGE",
            "billing_bound": "NOT_GUARANTEED",
            "roles": {
                role: sum(row[0] == role for row in rows)
                for role in sorted({row[0] for row in rows})
            },
        }
