"""Archive one no-tool Q calibration, with exactly one optional cloud analysis attempt."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / name)
    for name in ("gateway-python/src", "demo-agent", "control-plane-python", "sandbox")
]

from evidence_quote_calibration import TEXT, QuotationModel, run_quote_task  # noqa: E402
from runtime_source_archive import archive_runtime  # noqa: E402
from sujie_demo_agent.bailian_agent import BailianChatModel, BailianCredentials  # noqa: E402
from sujie_gateway.m1_runtime import sha  # noqa: E402
from verify_operator_export import verify  # noqa: E402
from verify_sequence_export import recompute  # noqa: E402


async def evaluate(out, credentials_path=None):
    if out.exists():
        raise ValueError("REPORT_ALREADY_EXISTS")
    credentials = BailianCredentials.from_csv(credentials_path) if credentials_path else None
    protocol_path = ROOT / "eval/protocols/evidence_quote_development_v1.json"
    protocol = json.loads(protocol_path.read_bytes())
    out.mkdir(parents=True)
    source_hash = archive_runtime(
        out,
        (
            "eval/run_evidence_quote_validation.py",
            "eval/evidence_quote_calibration.py",
            "eval/runtime_source_archive.py",
            "eval/verify_runtime_validation.py",
            "eval/verify_operator_export.py",
            "eval/verify_evidence_quote_validation.py",
            "eval/verify_sequence_export.py",
            "eval/protocols/evidence_quote_development_v1.json",
            "tests/test_evidence_analysis.py",
        ),
    )
    report = {
        "kind": "no-tool-quote-development-validation-v1",
        "protocol": protocol,
        "protocol_sha256": sha(protocol),
        "runtime_archive_sha256": source_hash,
        "mode": "scripted-main/cloud-analysis"
        if credentials
        else "scripted-main/scripted-analysis",
        "source_hash": sha(TEXT),
        "run_status": "RUNNING",
        "planned_cells": ["quoted-command"],
        "cases": [],
        "passed": False,
    }
    path = out / "summary.json"

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")

    save()
    try:
        row = await run_quote_task(
            (
                lambda: BailianChatModel(
                    credentials,
                    model=protocol["model"],
                    max_tokens=protocol["max_tokens"],
                    timeout=protocol["timeout_seconds"],
                )
            )
            if credentials
            else QuotationModel
        )
        exported = row.pop("export")
        verify(exported)
        recompute(exported)
        row.update(
            case="quoted-command",
            task_id=exported["payload"]["task"]["id"],
            metrics=exported["payload"]["task"]["metrics"],
            export_hash=exported["export_hash"],
        )
        (out / "quoted-command-export.json").write_text(
            json.dumps(exported, ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
        report.update(
            run_status="FINISHED",
            cases=[row],
            passed=row["passed"],
            cloud_calls=row["cloud_calls"],
            reported_tokens=row["reported_tokens"],
        )
    except Exception as error:
        report.update(run_status="FAILED", error_type=type(error).__name__)
        raise
    finally:
        save()
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "mode",
                    "passed",
                    "cloud_calls",
                    "reported_tokens",
                    "runtime_archive_sha256",
                )
            }
        )
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--credentials-file", type=Path)
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.out_dir, args.credentials_file))
    raise SystemExit(int(not result["passed"]))
