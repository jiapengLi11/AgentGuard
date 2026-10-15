"""Recompute finite validation exports, source integrity and current-source correspondence."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from verify_operator_export import verify
from verify_sequence_export import recompute

ROOT = Path(__file__).resolve().parents[1]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_directory(directory: Path) -> dict:
    summary = json.loads((directory / "summary.json").read_bytes())
    raw = (directory / "runtime-sources.json").read_bytes()
    if sha(raw) != summary["runtime_archive_sha256"]:
        raise ValueError("SOURCE_ARCHIVE_HASH_MISMATCH")
    archive = json.loads(raw)
    if archive["schema_version"] != "sujie-runtime-source-archive-v1":
        raise ValueError("SOURCE_ARCHIVE_UNSUPPORTED")
    changed = []
    for name, source in archive["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("SOURCE_PATH_INVALID")
        if sha(source["utf8"].encode("utf-8")) != source["sha256"]:
            raise ValueError("SOURCE_CONTENT_HASH_MISMATCH")
        current = ROOT / name
        if not current.is_file() or sha(current.read_bytes()) != source["sha256"]:
            changed.append(name)
    frozen = json.loads((ROOT / "eval/protocols/task_aware_holdout_v1.json").read_bytes())[
        "implementation_sha256"
    ]
    frozen_matches = {
        name: sha((ROOT / name).read_bytes()) == expected for name, expected in frozen.items()
    }
    exports = []
    for case in summary["cases"]:
        name = case["case"] + "-export.json"
        if Path(name).name != name or "/" in name or "\\" in name or ":" in name:
            raise ValueError("EXPORT_PATH_INVALID")
        document = json.loads((directory / name).read_bytes())
        result = verify(document)
        if result["export_hash"] != case["export_hash"] or result["task_id"] != case["task_id"]:
            raise ValueError("SUMMARY_EXPORT_MISMATCH")
        if result["oracle"] != case["oracle"] or result["metrics"] != case["metrics"]:
            raise ValueError("SUMMARY_OBSERVATION_MISMATCH")
        exports.append({"case": case["case"], "integrity": result, "sequence": recompute(document)})
    return {
        "ok": not changed and all(frozen_matches.values()),
        "scope": "LOCAL_ARCHIVE_EXPORT_CONSISTENCY_NOT_SIGNED_AUTHENTICITY_OR_ASR",
        "verifier_sha256": sha(Path(__file__).read_bytes()),
        "runtime_archive_sha256": sha(raw),
        "source_files": len(archive["files"]),
        "current_sources_match": not changed,
        "current_source_mismatches": changed,
        "m9_frozen_matches": frozen_matches,
        "recorded_validation_passed": summary["passed"],
        "exports": exports,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument(
        "--out", type=Path, help="New verification JSON; an existing file is refused"
    )
    args = parser.parse_args()
    result = verify_directory(args.report_directory)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(json.dumps({key: value for key, value in result.items() if key != "exports"}))
    raise SystemExit(int(not result["ok"]))
