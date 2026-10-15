"""Cross-platform M0/M1 commands; invoke with the project's Python 3.12 venv."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "test",
            "schema",
            "unit",
            "lint",
            "format",
            "check",
            "demo",
            "eval-detection",
            "bench-policy",
            "bench-gateway",
            "console",
            "prepare-tokenizer",
        ],
    )
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("The frozen design requires Python 3.12.")
    if args.command == "console":
        return subprocess.run(
            [sys.executable, "control-plane-python/run_console.py"], cwd=ROOT, check=False
        ).returncode
    if args.command == "prepare-tokenizer":
        return subprocess.run(
            [sys.executable, "eval/prepare_tokenizer.py"], cwd=ROOT, check=False
        ).returncode
    if args.command == "demo":
        return subprocess.run(
            [sys.executable, "demo-agent/run_demo.py"], cwd=ROOT, check=False
        ).returncode
    if args.command == "eval-detection":
        return subprocess.run(
            [sys.executable, "eval/run_detection.py"], cwd=ROOT, check=False
        ).returncode
    if args.command == "bench-policy":
        return subprocess.run(
            [sys.executable, "eval/bench_policy.py"], cwd=ROOT, check=False
        ).returncode
    if args.command == "bench-gateway":
        return subprocess.run(
            [
                sys.executable,
                "eval/bench_gateway.py",
                "--out",
                "eval/reports/runs/gateway_latency.json",
            ],
            cwd=ROOT,
            check=False,
        ).returncode
    commands = {
        "test": [["pytest", "-q"]],
        "schema": [["pytest", "contracts/tests", "-q"]],
        "unit": [["pytest", "gateway-python/tests", "tests", "-q"]],
        "lint": [["ruff", "check", "."], ["ruff", "format", "--check", "."]],
        "format": [["ruff", "format", "."]],
    }
    commands["check"] = commands["lint"] + commands["test"]
    for command in commands[args.command]:
        result = subprocess.run([sys.executable, "-m", *command], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
