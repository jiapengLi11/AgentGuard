"""Cross-platform development commands; invoke with the project's Python 3.12 venv."""

import argparse
import subprocess
import sys
from datetime import UTC, datetime
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
            "deliver",
            "verify-delivery",
            "provenance-demo",
        ],
    )
    parser.add_argument(
        "--output", type=Path, help="New delivery directory, or directory to verify."
    )
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("The frozen design requires Python 3.12.")
    if args.output is not None and args.command not in {
        "deliver",
        "verify-delivery",
        "provenance-demo",
    }:
        parser.error("--output is only valid for deliver, verify-delivery and provenance-demo.")
    if args.command == "verify-delivery":
        if args.output is None:
            parser.error("verify-delivery requires --output.")
        sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent")]
        from sujie_demo_agent.delivery import verify_delivery

        try:
            document = verify_delivery(args.output)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"Delivery verification failed: {error}", file=sys.stderr)
            return 1
        passed = all(document["checks"].values())
        print(f"Integrity OK; scenario checks: {'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1
    if args.command in {"demo", "deliver"}:
        command = [sys.executable, "demo-agent/run_demo.py"]
        if args.command == "deliver":
            output = args.output or ROOT.parent / "artifacts" / "delivery" / datetime.now(
                UTC
            ).strftime("%Y%m%dT%H%M%S%fZ")
            command.extend(["--output", str(output.resolve())])
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    if args.command == "provenance-demo":
        command = [sys.executable, "demo-agent/run_provenance_demo.py"]
        if args.output:
            command.extend(["--output", str(args.output.resolve())])
        return subprocess.run(command, cwd=ROOT, check=False).returncode
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
