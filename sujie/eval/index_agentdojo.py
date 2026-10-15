"""Index base v1 task source without importing or executing upstream code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

SUITES = ("banking", "slack", "travel", "workspace")


def index(source_root: Path) -> dict:
    files, rows = {}, []
    for suite in SUITES:
        relative = f"default_suites/v1/{suite}/user_tasks.py"
        path = source_root / relative
        raw = path.read_bytes()
        if path.is_symlink() or len(raw) > 1_000_000:
            raise ValueError("INVALID_SOURCE_FILE")
        files[relative] = hashlib.sha256(raw).hexdigest()
        for task in ast.parse(raw.decode("utf-8")).body:
            if not isinstance(task, ast.ClassDef) or not task.name.startswith("UserTask"):
                continue
            prompt = next(
                (
                    node.value
                    for node in task.body
                    if isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "PROMPT"
                        for target in node.targets
                    )
                ),
                None,
            )
            if prompt is None:
                raise ValueError("UNSUPPORTED_INHERITED_TASK_PROMPT")
            ground = next(
                (
                    node
                    for node in task.body
                    if isinstance(node, ast.FunctionDef) and node.name == "ground_truth"
                ),
                None,
            )
            tools = set()
            if ground is not None:
                for node in ast.walk(ground):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "FunctionCall"
                    ):
                        function = next(
                            (item.value for item in node.keywords if item.arg == "function"), None
                        )
                        if isinstance(function, ast.Constant) and isinstance(function.value, str):
                            tools.add(function.value)
            rows.append(
                {
                    "suite": suite,
                    "task_class": task.name,
                    "prompt_source_sha256": hashlib.sha256(
                        ast.unparse(prompt).encode()
                    ).hexdigest(),
                    "ground_truth_tool_names": sorted(tools),
                    "prompt_is_literal": isinstance(prompt, ast.Constant),
                }
            )
    return {
        "kind": "agentdojo-v1-static-task-inventory",
        "upstream_repository": "https://github.com/ethz-spylab/agentdojo",
        "upstream_docs": "https://agentdojo.spylab.ai/concepts/task_suite_and_tasks/",
        "scope": "AST inventory of base v1 task classes only; no upstream import, execution, classification, task completion or ASR. Later version overrides are not enumerated.",
        "source_sha256": files,
        "summary": {
            "base_task_classes": len(rows),
            "by_suite": {suite: sum(row["suite"] == suite for row in rows) for suite in SUITES},
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Directory containing agentdojo/default_suites, without the agentdojo prefix",
    )
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("INVENTORY_ALREADY_EXISTS")
    if len(args.artifact_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in args.artifact_sha256
    ):
        parser.error("INVALID_ARTIFACT_SHA256")
    record = index(args.source_root)
    record["package"] = "agentdojo"
    record["version"] = args.package_version
    record["artifact_sha256"] = args.artifact_sha256
    record["artifact_hash_verification"] = (
        "Caller-supplied acquisition metadata; independently verify the downloaded archive against this digest."
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(record["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
