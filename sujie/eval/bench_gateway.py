"""Paired local MCP latency, including Gateway work and optional SQLite Trace."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "control-plane-python")]

from bench_policy import percentile  # noqa: E402
from mcp import StdioServerParameters  # noqa: E402
from sujie_control.profiles import records  # noqa: E402
from sujie_gateway.contracts import TaskContract, TaskGrant  # noqa: E402
from sujie_gateway.m1_runtime import LOCAL_TOOL_CATALOG, M1Gateway, StdioMCPProxy  # noqa: E402


class CountingProxy(StdioMCPProxy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.invocations = Counter()

    async def invoke(self, qualified_name, arguments):
        self.invocations[qualified_name] += 1
        return await super().invoke(qualified_name, arguments)


def stats(values: list[int]) -> dict:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50_ms": percentile(ordered, 0.5) / 1_000_000,
        "p95_ms": percentile(ordered, 0.95) / 1_000_000,
        "p99_ms": percentile(ordered, 0.99) / 1_000_000,
    }


async def benchmark(samples: int = 100, repeats: int = 3, warmup: int = 10) -> dict:
    if not 100 <= samples <= 1000 or not 1 <= repeats <= 10 or not 0 <= warmup <= 100:
        raise ValueError("INVALID_BENCHMARK_SIZE")
    raw, memory, sqlite, baseline, blocked = [], [], [], [], []
    rounds = []
    text = "Synthetic alert facts: 8.8.8.8 and 1.1.1.1. No private content."
    with tempfile.TemporaryDirectory(prefix="sujie-gateway-bench-") as directory:
        root = Path(directory)
        evidence, workspace = root / "evidence", root / "workspace"
        evidence.mkdir()
        (workspace / "case-001").mkdir(parents=True)
        (evidence / "alert.txt").write_text(text, "utf-8")
        (workspace / "case-001/secret.txt").write_text("SYNTHETIC-PRIVATE-BENCH", "utf-8")
        params = {
            "evidence": StdioServerParameters(
                command=sys.executable,
                args=[str(ROOT / "mcp-servers/evidence-server/server.py")],
                env={"SUJIE_EVIDENCE_ROOT": str(evidence)},
            ),
            "operations": StdioServerParameters(
                command=sys.executable,
                args=[str(ROOT / "mcp-servers/operations-server/server.py")],
                env={
                    "SUJIE_WORKSPACE_ROOT": str(workspace),
                    "SUJIE_RECEIVER_URL": "http://127.0.0.1:9",
                },
            ),
        }
        async with CountingProxy(
            params, expected_tools={alias: LOCAL_TOOL_CATALOG[alias] for alias in params}
        ) as proxy:
            for repeat in range(repeats):
                contract, grant = records("report")
                c, g = contract.to_dict(), grant.to_dict()
                c["budgets"]["tool_calls"] = g["budgets"]["tool_calls"] = 4 * (samples + warmup)
                contract, grant = TaskContract(c), TaskGrant(g)
                mem = M1Gateway(proxy, contract, grant)
                disk = M1Gateway(
                    proxy, contract, grant, trace_db_path=root / f"trace-{repeat}.sqlite3"
                )
                previous = M1Gateway(
                    proxy, contract, grant, trace_db_path=root / f"baseline-{repeat}.sqlite3"
                )
                # Benchmark-only comparison recreates the former default DELETE/FULL mode.
                previous.trace._db.execute("PRAGMA journal_mode=DELETE")
                previous.trace._db.execute("PRAGMA synchronous=FULL")
                gateways = {"memory": mem, "sqlite": disk, "baseline": previous}
                times = {"raw": [], "memory": [], "sqlite": [], "baseline": [], "blocked": []}

                async def call(mode):
                    start = time.perf_counter_ns()
                    if mode == "raw":
                        result = await proxy.invoke("evidence.read_alert", {"alert_id": "alert"})
                        valid = result["content"] == text
                    elif mode == "blocked":
                        result = await mem.call(
                            "operations.read_file", {"resource": "case-001/secret.txt"}
                        )
                        valid = result["decision"] == "BLOCK" and not result["ok"]
                    else:
                        result = await gateways[mode].call(
                            "evidence.read_alert", {"alert_id": "alert"}
                        )
                        valid = result["decision"] == "ALLOW" and result["data"]["content"] == text
                    elapsed = time.perf_counter_ns() - start
                    if not valid:
                        raise RuntimeError("BENCHMARK_PRECONDITION_FAILED")
                    return elapsed

                try:
                    for index in range(samples + warmup):
                        modes = ["raw", "memory", "sqlite", "baseline"]
                        offset = (index + repeat) % 4
                        for mode in modes[offset:] + modes[:offset] + ["blocked"]:
                            elapsed = await call(mode)
                            if index >= warmup:
                                times[mode].append(elapsed)
                    raw.extend(times["raw"])
                    memory.extend(times["memory"])
                    sqlite.extend(times["sqlite"])
                    baseline.extend(times["baseline"])
                    blocked.extend(times["blocked"])
                    rounds.append(
                        {
                            "round": repeat + 1,
                            "sqlite_config": {
                                "journal_mode": disk.trace._db.execute(
                                    "PRAGMA journal_mode"
                                ).fetchone()[0],
                                "synchronous": disk.trace._db.execute(
                                    "PRAGMA synchronous"
                                ).fetchone()[0],
                            },
                            "baseline_config": {
                                "journal_mode": previous.trace._db.execute(
                                    "PRAGMA journal_mode"
                                ).fetchone()[0],
                                "synchronous": previous.trace._db.execute(
                                    "PRAGMA synchronous"
                                ).fetchone()[0],
                            },
                            "latency": {mode: stats(values) for mode, values in times.items()},
                            "memory_artifacts": len(mem.trace.artifacts),
                            "memory_events": len(mem.trace.events),
                            "sqlite_artifacts": len(disk.trace.artifacts),
                            "sqlite_events": len(disk.trace.events),
                            "baseline_artifacts": len(previous.trace.artifacts),
                            "baseline_events": len(previous.trace.events),
                            "sqlite_integrity": disk.trace._db.execute(
                                "PRAGMA integrity_check"
                            ).fetchone()[0],
                            "baseline_integrity": previous.trace._db.execute(
                                "PRAGMA integrity_check"
                            ).fetchone()[0],
                            "history": {
                                mode: {
                                    "first_20_p50_ms": stats(values[:20])["p50_ms"],
                                    "last_20_p50_ms": stats(values[-20:])["p50_ms"],
                                }
                                for mode, values in times.items()
                            },
                        }
                    )
                finally:
                    mem.trace.close()
                    disk.trace.close()
                    previous.trace.close()
            if proxy.invocations["operations.read_file"] != 0:
                raise RuntimeError("BLOCKED_TOOL_WAS_INVOKED")
            if proxy.invocations["evidence.read_alert"] != repeats * (samples + warmup) * 4:
                raise RuntimeError("READ_COUNT_MISMATCH")
            invocations = dict(proxy.invocations)
    return {
        "scope": "local-serial-real-stdio-mcp-no-model-no-http-operator-api",
        "method": "rotate raw/memory/sqlite/baseline order per index; blocked probe last; paired deltas per index; fresh gateways per round; retained trace and artifact history within round",
        "samples_per_round": samples,
        "repeats": repeats,
        "warmup_per_round": warmup,
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "policy_snapshot_hash": contract.to_dict()["policy_snapshot_hash"],
        "startup_and_catalog_registration_timed": False,
        "payload_utf8_bytes": len(text.encode()),
        "latency": {
            "raw_mcp_read": stats(raw),
            "gateway_read_memory": stats(memory),
            "gateway_read_sqlite": stats(sqlite),
            "gateway_read_sqlite_baseline": stats(baseline),
            "blocked_before_tool": stats(blocked),
        },
        "paired_delta": {
            "memory_minus_raw": stats([a - b for a, b in zip(memory, raw, strict=True)]),
            "sqlite_minus_raw": stats([a - b for a, b in zip(sqlite, raw, strict=True)]),
            "sqlite_minus_memory": stats([a - b for a, b in zip(sqlite, memory, strict=True)]),
            "baseline_minus_current_sqlite": stats(
                [a - b for a, b in zip(baseline, sqlite, strict=True)]
            ),
        },
        "rounds": rounds,
        "actual_mcp_invocations": invocations,
        "raw_samples_ns": {
            "raw_mcp_read": raw,
            "gateway_read_memory": memory,
            "gateway_read_sqlite": sqlite,
            "gateway_read_sqlite_baseline": baseline,
            "blocked_before_tool": blocked,
        },
        "limits": [
            "single synthetic read operation and payload; not representative of all tools",
            "paired subtraction estimates incremental wall time and includes scheduling noise",
            "trace/artifact history grows within each round",
            "no model calls, cloud latency, concurrency, operator HTTP, startup or container isolation measurement",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(benchmark(args.samples, args.repeats, args.warmup))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("scope", "latency", "paired_delta", "actual_mcp_invocations")
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
