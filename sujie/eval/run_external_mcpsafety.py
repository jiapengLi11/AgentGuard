"""Offline attack-text coverage check against an unpacked MCP-SafetyBench checkout.

This does not execute the upstream tasks or reproduce its ASR/TSR metrics.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from sujie_gateway.detection import DETECTOR_VERSION, detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import new_id  # noqa: E402

UPSTREAM_PATH = Path("mcpuniverse/benchmark/configs/test")
DOMAINS = frozenset(
    {
        "browser_automation",
        "financial_analysis",
        "location_navigation",
        "repository_management",
        "web_search",
    }
)
SURFACES = {"modification_description": "tool_metadata", "modification_return": "tool_return"}
MAX_SOURCE_BYTES = 256_000
MAX_SERVER_BYTES = 1_000_000
TOOL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    raise ValueError("INVALID_MODIFICATION_CONTENT")


def _return_payload(value: Any) -> tuple[str, str]:
    """Extract an appended literal without evaluating upstream Python expressions."""
    if not isinstance(value, str):
        return _content(value), "json_value"
    try:
        expression = ast.parse(value, mode="eval").body
    except SyntaxError:
        return value, "source_text"
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add):
        if isinstance(expression.right, ast.Constant) and isinstance(expression.right.value, str):
            return expression.right.value, "literal_suffix"
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value, "string_literal"
    return value, "source_text"


def load_attacks(source_root: Path) -> tuple[list[dict], dict]:
    """Read upstream JSON as data; never import or execute benchmark modules."""
    task_root = source_root.resolve() / UPSTREAM_PATH
    if not task_root.is_dir():
        raise ValueError("MISSING_UPSTREAM_TASKS")
    files = sorted(task_root.glob("*/*.json"))
    if not files:
        raise ValueError("EMPTY_UPSTREAM_TASKS")
    tasks: list[dict] = []
    manifest: list[dict] = []
    for path in files:
        if path.is_symlink() or path.parent.name not in DOMAINS:
            raise ValueError("INVALID_UPSTREAM_PATH")
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("UPSTREAM_TASK_TOO_LARGE")
        relative = path.relative_to(task_root).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        manifest.append({"path": relative, "sha256": digest})
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("attack_category"), str):
            raise ValueError("INVALID_UPSTREAM_TASK")
        modifications = data.get("mcp_server_modifications", [])
        if modifications is None:
            modifications = []
        if not isinstance(modifications, list):
            raise ValueError("INVALID_UPSTREAM_MODIFICATIONS")
        surfaces: list[dict] = []
        for modification in modifications:
            if not isinstance(modification, dict):
                raise ValueError("INVALID_UPSTREAM_MODIFICATIONS")
            for field, surface in SURFACES.items():
                if field in modification:
                    if surface == "tool_return":
                        content, extraction = _return_payload(modification[field])
                    else:
                        content, extraction = _content(modification[field]), "direct_text"
                    surfaces.append(
                        {
                            "surface": surface,
                            "extraction": extraction,
                            "tool_name": modification.get("tool_name"),
                            "text": content,
                            "text_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        }
                    )
        tasks.append(
            {
                "upstream_file": relative,
                "source_sha256": digest,
                "domain": path.parent.name,
                "attack_category": data["attack_category"],
                "surfaces": surfaces,
            }
        )
    source_manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return tasks, {"source_manifest_sha256": source_manifest_sha256, "source_files": len(files)}


def load_original_tool_descriptions(
    source_root: Path, tool_names: set[str] | None, *, include_text: bool = False
) -> list[dict]:
    """Parse original server docstrings as normal controls without importing code."""
    server_root = source_root.resolve() / "mcpuniverse/mcp/servers"
    if not server_root.is_dir():
        raise ValueError("MISSING_UPSTREAM_SERVERS")
    controls = []
    for path in sorted(server_root.glob("*/server.py")):
        if path.is_symlink():
            raise ValueError("INVALID_UPSTREAM_PATH")
        raw = path.read_bytes()
        if len(raw) > MAX_SERVER_BYTES:
            raise ValueError("UPSTREAM_SERVER_TOO_LARGE")
        source_file = path.relative_to(source_root.resolve()).as_posix()
        tree = ast.parse(raw, filename=source_file)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if tool_names is None:
                selected = any(
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "tool"
                    for decorator in node.decorator_list
                )
            else:
                selected = node.name in tool_names
            if selected:
                description = ast.get_docstring(node)
                if not description:
                    continue
                _, finding = detect_indirect(description, new_id(), new_id())
                control = {
                    "upstream_file": source_file,
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "tool_name": node.name,
                    "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
                    "rule_detected": finding is not None,
                }
                if include_text:
                    control["description"] = description
                controls.append(control)
    return controls


def load_catalog_additions(source_root: Path) -> tuple[list[dict], dict]:
    """Extract added-tool names and descriptions; never read implementation_code as code."""
    tasks, provenance = load_attacks(source_root)
    task_root = source_root.resolve() / UPSTREAM_PATH
    additions = []
    for task in tasks:
        data = json.loads((task_root / task["upstream_file"]).read_bytes())
        entries = data.get("mcp_server_additions", [])
        if entries is None:
            entries = []
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            raise ValueError("INVALID_UPSTREAM_ADDITIONS")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("INVALID_UPSTREAM_ADDITIONS")
            name, description = entry.get("tool_name"), entry.get("description")
            if (
                not isinstance(name, str)
                or TOOL_NAME.fullmatch(name) is None
                or name == "search"
                or not isinstance(description, str)
                or not description
            ):
                raise ValueError("INVALID_UPSTREAM_ADDITIONS")
            additions.append(
                {
                    "upstream_file": task["upstream_file"],
                    "source_sha256": task["source_sha256"],
                    "attack_category": task["attack_category"],
                    "tool_name": name,
                    "description": description,
                    "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
                }
            )
    return additions, provenance


def evaluate(source_root: Path) -> dict:
    tasks, provenance = load_attacks(source_root)
    target_names = {
        item["tool_name"]
        for task in tasks
        for item in task["surfaces"]
        if item["surface"] == "tool_metadata" and isinstance(item["tool_name"], str)
    }
    clean_controls = load_original_tool_descriptions(source_root, target_names)
    all_clean_controls = load_original_tool_descriptions(source_root, None)
    control_manifest_sha256 = hashlib.sha256(
        json.dumps(clean_controls, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    all_control_manifest_sha256 = hashlib.sha256(
        json.dumps(all_clean_controls, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    rows = []
    category_counts: Counter[str] = Counter()
    surface_counts: Counter[str] = Counter()
    extraction_counts: Counter[str] = Counter()
    hit_counts: Counter[str] = Counter()
    covered_categories: Counter[str] = Counter()
    category_hits: Counter[str] = Counter()
    for task in tasks:
        category_counts[task["attack_category"]] += 1
        findings = []
        for item in task["surfaces"]:
            _, finding = detect_indirect(item["text"], new_id(), new_id())
            surface = item["surface"]
            surface_counts[surface] += 1
            extraction_counts[item["extraction"]] += 1
            hit_counts[surface] += finding is not None
            findings.append(
                {
                    "surface": surface,
                    "extraction": item["extraction"],
                    "text_sha256": item["text_sha256"],
                    "rule_detected": finding is not None,
                }
            )
        rows.append(
            {key: value for key, value in task.items() if key != "surfaces"}
            | {"findings": findings}
        )
        if findings:
            covered_categories[task["attack_category"]] += 1
            category_hits[task["attack_category"]] += any(
                item["rule_detected"] for item in findings
            )
    covered = [row for row in rows if row["findings"]]
    hit_tasks = sum(any(item["rule_detected"] for item in row["findings"]) for row in covered)
    return {
        "kind": "mcp-safetybench-offline-attack-text-detection",
        "scope": "Upstream attack text and a small set of original tool docstrings; no upstream task execution, agent ASR, TSR, or general false-positive estimate.",
        "upstream_repository": "https://github.com/xjzzzzzzzz/MCPSafety",
        "upstream_task_path": UPSTREAM_PATH.as_posix(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "detector_version": DETECTOR_VERSION,
        **provenance,
        "original_tool_control_manifest_sha256": control_manifest_sha256,
        "all_original_tool_control_manifest_sha256": all_control_manifest_sha256,
        "summary": {
            "all_tasks": len(rows),
            "covered_tasks": len(covered),
            "uncovered_tasks": len(rows) - len(covered),
            "covered_task_rule_hits": hit_tasks,
            "attack_text_rule_recall": hit_tasks / len(covered) if covered else None,
            "attack_category_counts": dict(sorted(category_counts.items())),
            "covered_category_counts": dict(sorted(covered_categories.items())),
            "covered_category_rule_hits": dict(sorted(category_hits.items())),
            "surface_counts": dict(sorted(surface_counts.items())),
            "extraction_counts": dict(sorted(extraction_counts.items())),
            "surface_rule_hits": dict(sorted(hit_counts.items())),
            "original_tool_descriptions": len(clean_controls),
            "original_tool_description_rule_hits": sum(
                item["rule_detected"] for item in clean_controls
            ),
            "original_tool_names_missing": sorted(
                target_names - {item["tool_name"] for item in clean_controls}
            ),
            "all_original_tool_descriptions": len(all_clean_controls),
            "all_original_tool_rule_hits": sum(
                item["rule_detected"] for item in all_clean_controls
            ),
        },
        "original_tool_controls": clean_controls,
        "all_original_tool_controls": all_clean_controls,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Unpacked official MCPSafety repository root",
    )
    parser.add_argument("--out", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--expected-manifest-sha256",
        help="Reject a source tree whose ordered file path and SHA-256 manifest differs",
    )
    args = parser.parse_args()
    report = evaluate(args.source_root)
    if (
        args.expected_manifest_sha256
        and report["source_manifest_sha256"] != args.expected_manifest_sha256.lower()
    ):
        raise ValueError("UPSTREAM_MANIFEST_MISMATCH")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "source_manifest_sha256": report["source_manifest_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
