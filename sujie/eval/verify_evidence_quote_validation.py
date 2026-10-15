"""Recompute Q quotation coverage and actual report hash from pinned development text."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / name)
    for name in ("gateway-python/src", "demo-agent", "control-plane-python", "sandbox")
]

from evidence_quote_calibration import COMMAND, TEXT  # noqa: E402
from sujie_gateway.m1_runtime import sha  # noqa: E402
from verify_runtime_validation import verify_directory  # noqa: E402


def verify_quote_witness(witness):
    original = witness["observed_original_hash"] == witness["source_file_hash"] == sha(TEXT)
    if witness["source_hash"] != sha(TEXT) or original != witness["original_unchanged"]:
        raise ValueError("QUOTE_SOURCE_WITNESS_MISMATCH")
    manifest = witness["quotation_manifest"]
    if manifest is None:
        return {"verified": False, "original_unchanged": original}
    quotes, spans = [], []
    for quote in manifest["quotes"]:
        start, end = quote["start"], quote["end"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(TEXT)
            or quote["artifact_id"] != witness["source_artifact_id"]
            or quote["text_sha256"] != sha(TEXT[start:end])
        ):
            raise ValueError("QUOTE_LITERAL_WITNESS_MISMATCH")
        spans.append((start, end))
        quotes.append(TEXT[start:end])
    if len(manifest["sources"]) != 1:
        raise ValueError("QUOTE_SOURCE_COUNT_MISMATCH")
    source = manifest["sources"][0]
    if (
        source["artifact_id"] != witness["source_artifact_id"]
        or source["content_hash"] != sha(TEXT)
        or source["characters"] != len(TEXT)
        or source["original_retained"] is not True
    ):
        raise ValueError("QUOTE_SOURCE_MANIFEST_MISMATCH")
    spans += [(item["start"], item["end"]) for item in source["unquoted_ranges"]]
    cursor = 0
    for start, end in sorted(spans):
        if (
            type(start) is not int
            or type(end) is not int
            or start != cursor
            or not start < end <= len(TEXT)
        ):
            raise ValueError("QUOTE_COVERAGE_MISMATCH")
        cursor = end
    if cursor != len(TEXT):
        raise ValueError("QUOTE_COVERAGE_MISMATCH")
    report = "Evidence quotations only, no execution:\n" + "\n".join(quotes)
    command, facts = COMMAND in report, all(ip in report for ip in ("8.8.8.8", "1.1.1.1"))
    if (
        sha(report) != witness["report_hash"]
        or command != witness["command_in_report"]
        or facts != witness["facts_in_report"]
    ):
        raise ValueError("QUOTE_REPORT_WITNESS_MISMATCH")
    return {
        "verified": True,
        "original_unchanged": original,
        "command_in_report": command,
        "facts_in_report": facts,
        "coverage": "quotations plus unquoted ranges partition the complete original",
    }


def analyze(directory):
    sources = verify_directory(directory)
    summary = json.loads((directory / "summary.json").read_bytes())
    row = summary["cases"][0]
    exported = json.loads((directory / "quoted-command-export.json").read_bytes())
    witness = exported["payload"]["evaluation_quote_witness"]
    if (
        witness != row["witness"]
        or summary["protocol_sha256"] != sha(summary["protocol"])
        or row["agent"] != exported["payload"]["task"]["agent"]
    ):
        raise ValueError("QUOTE_SUMMARY_MISMATCH")
    quotation = verify_quote_witness(witness)
    return {
        "ok": all(sources["m9_frozen_matches"].values()) and quotation["verified"],
        "current_sources_match": sources["current_sources_match"],
        "scope": "local source/export/quotation/report consistency; not signed authenticity or full-model ASR",
        "recorded_validation_passed": summary["passed"],
        "sources": sources,
        "quotation": quotation,
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.report_directory)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "sources"}))
    raise SystemExit(int(not result["ok"]))
