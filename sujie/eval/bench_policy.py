"""Measure pure in-process policy latency; excludes schema construction and MCP I/O."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from sujie_gateway.contracts import SemanticAction, TaskContract, TaskGrant  # noqa: E402
from sujie_gateway.m1_runtime import M1Policy  # noqa: E402

FIXTURES = ROOT / "contracts/fixtures/valid"


def percentile(sorted_values: list[int], percent: float) -> int:
    index = (len(sorted_values) - 1) * percent
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    return round(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low))


def benchmark(samples: int = 5000) -> dict:
    if samples < 100:
        raise ValueError("AT_LEAST_100_SAMPLES_REQUIRED")

    def fixture(name: str) -> dict:
        return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))

    policy = M1Policy()
    contract_body = fixture("task-contract")
    contract_body["expires_at"] = "2099-01-01T00:00:00Z"
    contract_body["policy_snapshot_hash"] = policy.snapshot_hash
    grant_body = fixture("task-grant")
    grant_body["expires_at"] = "2099-01-01T00:00:00Z"
    action = SemanticAction(fixture("semantic-action"))
    contract, grant = TaskContract(contract_body), TaskGrant(grant_body)
    for _ in range(100):
        if policy.decide(action, contract, grant).decision != "ALLOW":
            raise RuntimeError("BENCHMARK_PRECONDITION_FAILED")
    durations = []
    for _ in range(samples):
        start = time.perf_counter_ns()
        decision = policy.decide(action, contract, grant)
        durations.append(time.perf_counter_ns() - start)
        if decision.decision != "ALLOW":
            raise RuntimeError("BENCHMARK_DECISION_CHANGED")
    durations.sort()
    return {
        "scope": "pure_M1Policy_decide_in_process_no_mcp_no_model",
        "samples": samples,
        "policy_snapshot_hash": policy.snapshot_hash,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "p50_ms": percentile(durations, 0.5) / 1_000_000,
        "p95_ms": percentile(durations, 0.95) / 1_000_000,
        "p99_ms": percentile(durations, 0.99) / 1_000_000,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    output = json.dumps(benchmark(args.samples), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, "utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
