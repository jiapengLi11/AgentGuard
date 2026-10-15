"""Offline detection on InjecAgent tool responses; never run upstream agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from sujie_gateway.detection import DETECTOR_VERSION, detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import new_id  # noqa: E402

KINDS = ("dh", "ds")
SETTINGS = ("base", "enhanced")
MAX_FILE_BYTES = 2_000_000
MAX_RESPONSE_CHARS = 100_000
IDENTITY_FIELDS = ("User Instruction", "Attacker Instruction", "Attack Type", "User Tool")


def load_cases(source_root: Path) -> tuple[dict[tuple[str, str], list[dict]], str]:
    data_root = source_root.resolve() / "data"
    groups = {}
    manifest = []
    for kind in KINDS:
        for setting in SETTINGS:
            name = f"test_cases_{kind}_{setting}.json"
            path = data_root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("MISSING_INJECAGENT_DATA")
            raw = path.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("INJECAGENT_DATA_TOO_LARGE")
            manifest.append({"path": f"data/{name}", "sha256": hashlib.sha256(raw).hexdigest()})
            rows = json.loads(raw)
            if not isinstance(rows, list) or not rows:
                raise ValueError("INVALID_INJECAGENT_DATA")
            for row in rows:
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(field), str) or not row[field]
                    for field in (*IDENTITY_FIELDS, "Tool Response")
                ):
                    raise ValueError("INVALID_INJECAGENT_DATA")
                if len(row["Tool Response"]) > MAX_RESPONSE_CHARS:
                    raise ValueError("INJECAGENT_RESPONSE_TOO_LARGE")
            groups[kind, setting] = rows
        base, enhanced = groups[kind, "base"], groups[kind, "enhanced"]
        if len(base) != len(enhanced) or any(
            any(left[field] != right[field] for field in IDENTITY_FIELDS)
            for left, right in zip(base, enhanced, strict=True)
        ):
            raise ValueError("INJECAGENT_PAIR_MISMATCH")
    manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return groups, manifest_sha


def evaluate(source_root: Path) -> dict:
    groups, manifest_sha = load_cases(source_root)
    rows = []
    counts: Counter[tuple[str, str, str]] = Counter()
    attack_types: Counter[tuple[str, str, str, str]] = Counter()
    for kind in KINDS:
        for setting in SETTINGS:
            for index, case in enumerate(groups[kind, setting]):
                response = case["Tool Response"]
                _, finding = detect_indirect(response, new_id(), new_id())
                counts[kind, setting, "cases"] += 1
                counts[kind, setting, "hits"] += finding is not None
                attack_types[kind, setting, case["Attack Type"], "cases"] += 1
                attack_types[kind, setting, case["Attack Type"], "hits"] += finding is not None
                rows.append(
                    {
                        "kind": kind,
                        "setting": setting,
                        "index": index,
                        "attack_type": case["Attack Type"],
                        "case_identity_sha256": hashlib.sha256(
                            json.dumps(
                                [case[field] for field in IDENTITY_FIELDS],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest(),
                        "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                        "rule_detected": finding is not None,
                    }
                )
    return {
        "kind": "injecagent-offline-tool-response-detection",
        "scope": "Static tool-response text only; no agent execution or official attack success rate.",
        "upstream_repository": "https://github.com/uiuc-kang-lab/InjecAgent",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "detector_version": DETECTOR_VERSION,
        "source_manifest_sha256": manifest_sha,
        "summary": {
            f"{kind}_{setting}": {
                "cases": counts[kind, setting, "cases"],
                "rule_hits": counts[kind, setting, "hits"],
            }
            for kind in KINDS
            for setting in SETTINGS
        },
        "attack_type_summary": {
            f"{kind}_{setting}": {
                attack_type: {
                    "cases": attack_types[kind, setting, attack_type, "cases"],
                    "rule_hits": attack_types[kind, setting, attack_type, "hits"],
                }
                for attack_type in sorted({case["Attack Type"] for case in groups[kind, setting]})
            }
            for kind in KINDS
            for setting in SETTINGS
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = evaluate(args.source_root)
    if (
        args.expected_manifest_sha256
        and report["source_manifest_sha256"] != args.expected_manifest_sha256.lower()
    ):
        raise ValueError("INJECAGENT_MANIFEST_MISMATCH")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "source_manifest_sha256": report["source_manifest_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
