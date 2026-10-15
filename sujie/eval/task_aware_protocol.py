"""Freeze untouched task-aware classification partitions and immutable settings."""

import hashlib
import json
from pathlib import Path

from run_external_injecagent import IDENTITY_FIELDS, load_cases
from run_task_aware_injecagent import BENIGN_REPLACEMENT, PLACEHOLDER
from split_injecagent import build_split
from sujie_demo_agent.semantic_detector import TASK_AWARE_PROMPT

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen-plus-2025-12-01"
MAX_TOKENS = 256
IMPLEMENTATION_FILES = (
    "demo-agent/sujie_demo_agent/semantic_detector.py",
    "gateway-python/src/sujie_gateway/detection.py",
    "eval/task_aware_protocol.py",
    "eval/run_frozen_task_aware.py",
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def identity(case: dict) -> str:
    return digest(
        json.dumps(
            [case[field] for field in IDENTITY_FIELDS], ensure_ascii=False, separators=(",", ":")
        ).encode()
    )


def implementation_hashes() -> dict:
    return {name: digest((ROOT / name).read_bytes()) for name in IMPLEMENTATION_FILES}


def pair(case: dict, row: dict) -> dict:
    template = case.get("Tool Response Template")
    if not isinstance(template, str) or template.count(PLACEHOLDER) != 1:
        raise ValueError("INVALID_INJECAGENT_TEMPLATE")
    attack, clean = case["Tool Response"], template.replace(PLACEHOLDER, BENIGN_REPLACEMENT)
    if not all(isinstance(value, str) and 1 <= len(value) <= 12000 for value in (attack, clean)):
        raise ValueError("TASK_AWARE_RESPONSE_TOO_LARGE")
    return {
        "kind": row["kind"],
        "index": row["index"],
        "case_identity_sha256": row["case_identity_sha256"],
        "tool_name": case["User Tool"],
        "trusted_user_request": case["User Instruction"],
        "attack_type": case["Attack Type"],
        "attack": attack,
        "clean": clean,
    }


def freeze(source_root: Path, split_path: Path) -> dict:
    groups, manifest = load_cases(source_root)
    split_raw = split_path.read_bytes()
    split = json.loads(split_raw)
    rebuilt = build_split(source_root)
    if split["source_manifest_sha256"] != manifest:
        raise ValueError("SPLIT_SOURCE_MISMATCH")
    keyed = {(row["kind"], row["index"]): row for row in split["rows"]}
    if len(keyed) != len(rebuilt["rows"]):
        raise ValueError("SPLIT_ROWS_INVALID")
    for row in rebuilt["rows"]:
        actual = keyed.get((row["kind"], row["index"]), {})
        if any(actual.get(key) != value for key, value in row.items()) or not isinstance(
            actual.get("pilot_exposed"), bool
        ):
            raise ValueError("SPLIT_ASSIGNMENT_INVALID")
    partitions = {}
    for name in ("validation", "test"):
        rows = sorted(
            (row for row in split["rows"] if row["partition"] == name and not row["pilot_exposed"]),
            key=lambda row: row["case_identity_sha256"],
        )
        if not rows:
            raise ValueError("EMPTY_UNTOUCHED_PARTITION")
        for row in rows:
            pair(groups[row["kind"], "base"][row["index"]], row)
        partitions[name] = [
            {
                key: row[key]
                for key in ("kind", "index", "case_identity_sha256", "intent_sha256", "tool_sha256")
            }
            for row in rows
        ]
    for axis in ("intent_sha256", "tool_sha256", "case_identity_sha256"):
        if {row[axis] for row in partitions["validation"]} & {
            row[axis] for row in partitions["test"]
        }:
            raise ValueError("HOLDOUT_AXIS_OVERLAP")
    return {
        "kind": "task-aware-held-out-protocol-v1",
        "source_manifest_sha256": manifest,
        "split_manifest_sha256": digest(split_raw),
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "model_tools": [],
        "prompt_sha256": digest(TASK_AWARE_PROMPT.encode()),
        "control_fill_sha256": digest(BENIGN_REPLACEMENT.encode()),
        "control_type": "synthetic-neutral-template-fill-not-real-benign-tool-responses",
        "implementation_sha256": implementation_hashes(),
        "partitions": partitions,
        "exposure_definition": "Exclude earlier task-aware classifier pilot and local Agent mapping cases; rule scans already covered the corpus. Public upstream may occur in model pretraining.",
        "scope": "offline task-aware classification; no Agent execution, blocking rate, or official ASR",
    }


def selected_pairs(protocol: dict, source_root: Path, partition: str) -> list[dict]:
    if (
        protocol.get("kind") != "task-aware-held-out-protocol-v1"
        or protocol.get("model") != MODEL
        or protocol.get("max_tokens") != MAX_TOKENS
        or protocol.get("temperature") != 0
        or protocol.get("model_tools") != []
    ):
        raise ValueError("FROZEN_SETTINGS_MISMATCH")
    if (
        protocol["prompt_sha256"] != digest(TASK_AWARE_PROMPT.encode())
        or protocol["control_fill_sha256"] != digest(BENIGN_REPLACEMENT.encode())
        or protocol["implementation_sha256"] != implementation_hashes()
    ):
        raise ValueError("FROZEN_IMPLEMENTATION_MISMATCH")
    groups, manifest = load_cases(source_root)
    if protocol["source_manifest_sha256"] != manifest:
        raise ValueError("FROZEN_SOURCE_MISMATCH")
    rows = protocol["partitions"][partition]
    seen = set()
    result = []
    for row in rows:
        case = groups[row["kind"], "base"][row["index"]]
        identifier = identity(case)
        if identifier != row["case_identity_sha256"] or identifier in seen:
            raise ValueError("FROZEN_SELECTION_MISMATCH")
        seen.add(identifier)
        result.append(pair(case, row))
    return result
