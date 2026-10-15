"""Collect real stdio returns for authored controls and select training intents."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent"), str(ROOT / "eval")]

from benign_documents import DOCUMENTS  # noqa: E402
from mcp import StdioServerParameters  # noqa: E402
from run_external_injecagent import load_cases  # noqa: E402
from run_task_aware_injecagent import BENIGN_REPLACEMENT, PLACEHOLDER  # noqa: E402
from split_injecagent import build_split  # noqa: E402
from sujie_gateway.m1_runtime import LOCAL_TOOL_CATALOG, StdioMCPProxy  # noqa: E402

SOURCE_SHA = "4498aa40eab6137f42d3915c9c54458df4408778e085ed631edfb68a88b80ab8"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def training_rows(source: Path) -> tuple[list[dict], str]:
    groups, manifest = load_cases(source)
    if manifest != SOURCE_SHA:
        raise ValueError("SOURCE_MANIFEST_MISMATCH")
    split = build_split(source)
    # Development selection intentionally uses TRAIN only. One case per intent;
    # no sample is selected according to a detector result.
    chosen = {}
    for row in sorted(split["rows"], key=lambda item: item["case_identity_sha256"]):
        if row["partition"] == "train":
            chosen.setdefault((row["kind"], row["intent_sha256"]), row)
    result = []
    for row in chosen.values():
        case = groups[row["kind"], "base"][row["index"]]
        template = case.get("Tool Response Template", "")
        if template.count(PLACEHOLDER) != 1:
            raise ValueError("INVALID_TEMPLATE")
        for label, response in (
            (True, case["Tool Response"]),
            (False, template.replace(PLACEHOLDER, BENIGN_REPLACEMENT)),
        ):
            result.append(
                {
                    **{
                        key: row[key]
                        for key in (
                            "kind",
                            "index",
                            "case_identity_sha256",
                            "intent_sha256",
                            "partition",
                        )
                    },
                    "id": f"train-{row['kind']}-{row['index']}-{'attack' if label else 'neutral'}",
                    "source_type": "injecagent-train-attack" if label else "synthetic-neutral-fill",
                    "expected": label,
                    "attack_type": case["Attack Type"],
                    "trusted_user_request": case["User Instruction"],
                    "tool_name": case["User Tool"],
                    "untrusted_tool_response": response,
                    "response_sha256": digest(response.encode()),
                }
            )
    return result, manifest


async def collect_controls() -> list[dict]:
    result = []
    with tempfile.TemporaryDirectory(prefix="sujie-benign-dev-") as directory:
        workspace = Path(directory)
        for name, _, content in DOCUMENTS:
            (workspace / f"{name}.txt").write_text(content, "utf-8")
        params = {
            "operations": StdioServerParameters(
                command=sys.executable,
                args=[str(ROOT / "mcp-servers/operations-server/server.py")],
                env={
                    "SUJIE_WORKSPACE_ROOT": str(workspace),
                    "SUJIE_RECEIVER_URL": "http://127.0.0.1:1/unused",
                },
            )
        }
        async with StdioMCPProxy(
            params, expected_tools={"operations": LOCAL_TOOL_CATALOG["operations"]}
        ) as proxy:
            for name, task, content in DOCUMENTS:
                arguments = {"resource": f"{name}.txt"}
                observed = await proxy.invoke("operations.read_file", arguments)
                if observed != {"resource": f"{name}.txt", "content": content}:
                    raise ValueError("CONTROL_EXECUTION_MISMATCH")
                response = json.dumps(observed, ensure_ascii=False, sort_keys=True)
                result.append(
                    {
                        "id": f"mcp-benign-{name}",
                        "source_type": "authored-benign-real-mcp-return",
                        "expected": False,
                        "trusted_user_request": task,
                        "tool_name": "operations.read_file",
                        "untrusted_tool_response": response,
                        "response_sha256": digest(response.encode()),
                        "execution": {
                            "transport": "stdio-mcp",
                            "arguments": arguments,
                            "tool_version_sha256": proxy.registry[
                                "operations.read_file"
                            ].version_hash,
                            "seed_content_sha256": digest(content.encode()),
                            "server_source_sha256": digest(
                                (ROOT / "mcp-servers/operations-server/server.py").read_bytes()
                            ),
                        },
                    }
                )
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("DATASET_ALREADY_EXISTS")
    rows, manifest = training_rows(args.source_root)
    rows.extend(await collect_controls())
    report = {
        "kind": "task-aware-development-suite-v2",
        "source_manifest_sha256": manifest,
        "scope": "TRAIN development classification only; authored controls executed through real MCP; no field benign FPR, held-out generalization or Agent ASR.",
        "selection": "One minimum-identity TRAIN case per attacker intent, each paired with neutral template fill; all authored controls.",
        "label_provenance": "InjecAgent attack labels; author-assigned synthetic control labels, no independent review.",
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {
                "rows": len(rows),
                "attacks": sum(r["expected"] for r in rows),
                "mcp_controls": len(DOCUMENTS),
                "dataset_sha256": digest(args.out.read_bytes()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
