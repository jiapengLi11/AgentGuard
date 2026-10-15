"""Replay upstream tool descriptions through Sujie's real local MCP registration path.

Only this repository's inert fixture server runs. No upstream server or task is executed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "eval")]

from mcp import StdioServerParameters  # noqa: E402
from run_external_mcpsafety import (  # noqa: E402
    load_attacks,
    load_catalog_additions,
    load_original_tool_descriptions,
)
from sujie_gateway.detection import DETECTOR_VERSION, detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import StdioMCPProxy, new_id  # noqa: E402

FIXTURE = ROOT / "mcp-servers/eval-catalog-fixture/server.py"
BASE_DESCRIPTION = "Search for a query."


async def admission_status(description: str) -> str:
    """Submit text as actual tools/list metadata; never call the exposed tool."""
    with tempfile.TemporaryDirectory(prefix="sujie-mcp-catalog-") as directory:
        source = Path(directory) / "description.txt"
        source.write_text(description, "utf-8")
        params = {
            "fixture": StdioServerParameters(
                command=sys.executable,
                args=[str(FIXTURE)],
                env={"SUJIE_CATALOG_DESCRIPTION_FILE": str(source)},
            )
        }
        try:
            async with StdioMCPProxy(params) as proxy:
                if "fixture.search" not in proxy.registry:
                    return "PROTOCOL_ERROR"
                return "ADMITTED"
        except RuntimeError as exc:
            if str(exc) == "TOOL_METADATA_INJECTION":
                return "REJECTED_INJECTION"
            return "PROTOCOL_ERROR"
        except Exception:
            return "PROTOCOL_ERROR"


async def addition_status(name: str, description: str, *, pinned: bool) -> str:
    """Register one upstream added tool beside a known local tool."""
    with tempfile.TemporaryDirectory(prefix="sujie-mcp-addition-") as directory:
        baseline = Path(directory) / "baseline.txt"
        addition = Path(directory) / "addition.txt"
        baseline.write_text(BASE_DESCRIPTION, "utf-8")
        addition.write_text(description, "utf-8")
        params = {
            "fixture": StdioServerParameters(
                command=sys.executable,
                args=[str(FIXTURE)],
                env={
                    "SUJIE_CATALOG_DESCRIPTION_FILE": str(baseline),
                    "SUJIE_CATALOG_EXTRA_NAME": name,
                    "SUJIE_CATALOG_EXTRA_DESCRIPTION_FILE": str(addition),
                },
            )
        }
        expected = {"fixture": frozenset({"search"})} if pinned else None
        try:
            async with StdioMCPProxy(params, expected_tools=expected) as proxy:
                return "ADMITTED" if f"fixture.{name}" in proxy.registry else "PROTOCOL_ERROR"
        except RuntimeError as exc:
            if str(exc) == "TOOL_CATALOG_DRIFT":
                return "REJECTED_CATALOG"
            if str(exc) == "TOOL_METADATA_INJECTION":
                return "REJECTED_INJECTION"
            return "PROTOCOL_ERROR"
        except Exception:
            return "PROTOCOL_ERROR"


async def evaluate_additions(
    source_root: Path, *, limit: int = 0, expected_manifest_sha256: str | None = None
) -> dict:
    if limit < 0:
        raise ValueError("INVALID_LIMIT")
    additions, provenance = load_catalog_additions(source_root)
    if (
        expected_manifest_sha256
        and provenance["source_manifest_sha256"] != expected_manifest_sha256.lower()
    ):
        raise ValueError("UPSTREAM_MANIFEST_MISMATCH")
    if limit:
        additions = additions[:limit]
    rows = []
    for item in additions:
        baseline = await addition_status(item["tool_name"], item["description"], pinned=False)
        pinned = await addition_status(item["tool_name"], item["description"], pinned=True)
        rows.append(
            {key: value for key, value in item.items() if key != "description"}
            | {"unpinned_status": baseline, "pinned_status": pinned}
        )
    return {
        "kind": "mcp-safetybench-local-protocol-catalog-additions",
        "scope": "Only metadata of upstream added tools replayed on an inert local MCP server; implementation_code and upstream tasks are never executed.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "detector_version": DETECTOR_VERSION,
        **provenance,
        "summary": {
            "cases": len(rows),
            "unpinned_admitted": sum(row["unpinned_status"] == "ADMITTED" for row in rows),
            "unpinned_injection_rejected": sum(
                row["unpinned_status"] == "REJECTED_INJECTION" for row in rows
            ),
            "pinned_catalog_rejected": sum(
                row["pinned_status"] == "REJECTED_CATALOG" for row in rows
            ),
            "protocol_errors": sum(
                "PROTOCOL_ERROR" in (row["unpinned_status"], row["pinned_status"]) for row in rows
            ),
        },
        "rows": rows,
    }


async def evaluate(
    source_root: Path,
    *,
    max_attacks: int = 0,
    max_clean: int = 0,
    all_clean: bool = False,
    clean_only: bool = False,
    expected_manifest_sha256: str | None = None,
) -> dict:
    if max_attacks < 0 or max_clean < 0:
        raise ValueError("INVALID_LIMIT")
    tasks, provenance = load_attacks(source_root)
    if (
        expected_manifest_sha256
        and provenance["source_manifest_sha256"] != expected_manifest_sha256.lower()
    ):
        raise ValueError("UPSTREAM_MANIFEST_MISMATCH")
    attacks = [
        {
            "upstream_file": task["upstream_file"],
            "source_sha256": task["source_sha256"],
            "attack_category": task["attack_category"],
            "tool_name": item["tool_name"],
            "description": item["text"],
            "description_sha256": item["text_sha256"],
        }
        for task in tasks
        for item in task["surfaces"]
        if item["surface"] == "tool_metadata"
    ]
    targets = {item["tool_name"] for item in attacks if isinstance(item["tool_name"], str)}
    controls = load_original_tool_descriptions(
        source_root, None if all_clean else targets, include_text=True
    )
    if max_attacks:
        attacks = attacks[:max_attacks]
    if clean_only:
        attacks = []
    if max_clean:
        controls = controls[:max_clean]
    rows = []
    for label, group in (("ATTACK", attacks), ("CLEAN", controls)):
        for item in group:
            description = item["description"]
            _, finding = detect_indirect(description, new_id(), new_id())
            status = await admission_status(description)
            rows.append(
                {
                    "label": label,
                    "upstream_file": item["upstream_file"],
                    "source_sha256": item["source_sha256"],
                    "attack_category": item.get("attack_category"),
                    "tool_name": item["tool_name"],
                    "description_sha256": item["description_sha256"],
                    "offline_rule_detected": finding is not None,
                    "protocol_status": status,
                    "matches_offline_rule": status != "PROTOCOL_ERROR"
                    and ((status == "REJECTED_INJECTION") == (finding is not None)),
                }
            )
    counts = Counter((row["label"], row["protocol_status"]) for row in rows)
    return {
        "kind": "mcp-safetybench-local-protocol-metadata-admission",
        "scope": "Upstream text replayed as metadata of an inert local MCP server; no upstream tasks or tools executed.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "detector_version": DETECTOR_VERSION,
        "all_clean": all_clean,
        "clean_only": clean_only,
        **provenance,
        "selection_sha256": hashlib.sha256(
            json.dumps(
                [(row["label"], row["upstream_file"], row["description_sha256"]) for row in rows],
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "summary": {
            "attack_cases": len(attacks),
            "clean_controls": len(controls),
            "attack_rejected": counts["ATTACK", "REJECTED_INJECTION"],
            "attack_admitted": counts["ATTACK", "ADMITTED"],
            "clean_rejected": counts["CLEAN", "REJECTED_INJECTION"],
            "clean_admitted": counts["CLEAN", "ADMITTED"],
            "protocol_errors": sum(row["protocol_status"] == "PROTOCOL_ERROR" for row in rows),
            "offline_protocol_disagreements": sum(not row["matches_offline_rule"] for row in rows),
        },
        "rows": rows,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("description", "additions"), default="description")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--max-attacks", type=int, default=0, help="0 means all metadata attacks")
    parser.add_argument(
        "--max-clean", type=int, default=0, help="0 means all original descriptions"
    )
    parser.add_argument(
        "--all-clean", action="store_true", help="Use every upstream server tool docstring"
    )
    parser.add_argument("--clean-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Addition pairs; 0 means all")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.mode == "additions":
        report = await evaluate_additions(
            args.source_root,
            limit=args.limit,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
    else:
        report = await evaluate(
            args.source_root,
            max_attacks=args.max_attacks,
            max_clean=args.max_clean,
            all_clean=args.all_clean,
            clean_only=args.clean_only,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {"summary": report["summary"], "output": str(args.out) if args.out else None},
            ensure_ascii=False,
        )
    )
    return int(report["summary"]["protocol_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
