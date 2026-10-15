"""Check independent reference MCP tool descriptions without running source code."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from run_external_mcpsafety_protocol import admission_status  # noqa: E402
from sujie_gateway.detection import DETECTOR_VERSION, detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import new_id  # noqa: E402

SOURCE_FILES = ("src/filesystem/server.ts", "src/memory/index.ts")
MAX_SOURCE_BYTES = 1_000_000
TOOL_HEADER = re.compile(
    r'server\.registerTool\(\s*"([A-Za-z_][A-Za-z_0-9]*)"\s*,\s*\{\s*'
    r'title:\s*"(?:\\.|[^"\\])*"\s*,\s*description:\s*'
)
STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def _description(source: str, offset: int) -> str:
    parts: list[str] = []
    while True:
        match = STRING.match(source, offset)
        if match is None:
            raise ValueError("UNSUPPORTED_TOOL_DESCRIPTION")
        parts.append(json.loads(match.group()))
        offset = match.end()
        while offset < len(source) and source[offset].isspace():
            offset += 1
        if offset < len(source) and source[offset] == "+":
            offset += 1
            while offset < len(source) and source[offset].isspace():
                offset += 1
            continue
        if not source.startswith(",", offset):
            raise ValueError("UNSUPPORTED_TOOL_DESCRIPTION")
        if not re.match(r"\s*inputSchema\s*:", source[offset + 1 :]):
            raise ValueError("UNSUPPORTED_TOOL_DESCRIPTION")
        return "".join(parts)


def load_descriptions(source_root: Path) -> tuple[list[dict], str]:
    root = source_root.resolve()
    rows = []
    manifest = []
    names: set[tuple[str, str]] = set()
    for relative in SOURCE_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("MISSING_REFERENCE_SOURCE")
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("REFERENCE_SOURCE_TOO_LARGE")
        digest = hashlib.sha256(raw).hexdigest()
        manifest.append({"path": relative, "sha256": digest})
        source = raw.decode("utf-8")
        headers = list(TOOL_HEADER.finditer(source))
        if not headers:
            raise ValueError("NO_REFERENCE_TOOLS")
        for header in headers:
            name = header.group(1)
            if (relative, name) in names:
                raise ValueError("DUPLICATE_REFERENCE_TOOL")
            names.add((relative, name))
            description = _description(source, header.end())
            rows.append(
                {
                    "source_file": relative,
                    "source_sha256": digest,
                    "tool_name": name,
                    "description": description,
                    "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
                }
            )
    manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return rows, manifest_sha


async def evaluate(source_root: Path) -> dict:
    descriptions, manifest_sha = load_descriptions(source_root)
    rows = []
    for item in descriptions:
        _, finding = detect_indirect(item["description"], new_id(), new_id())
        status = await admission_status(item["description"])
        rows.append(
            {key: value for key, value in item.items() if key != "description"}
            | {"rule_detected": finding is not None, "protocol_status": status}
        )
    return {
        "kind": "independent-reference-mcp-clean-catalog-admission",
        "scope": "Static descriptions from two official reference servers; no source execution.",
        "upstream_repository": "https://github.com/modelcontextprotocol/servers",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "detector_version": DETECTOR_VERSION,
        "source_manifest_sha256": manifest_sha,
        "summary": {
            "descriptions": len(rows),
            "offline_rejected": sum(row["rule_detected"] for row in rows),
            "protocol_admitted": sum(row["protocol_status"] == "ADMITTED" for row in rows),
            "protocol_rejected": sum(
                row["protocol_status"] == "REJECTED_INJECTION" for row in rows
            ),
            "protocol_errors": sum(row["protocol_status"] == "PROTOCOL_ERROR" for row in rows),
        },
        "rows": rows,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = await evaluate(args.source_root)
    if (
        args.expected_manifest_sha256
        and report["source_manifest_sha256"] != args.expected_manifest_sha256.lower()
    ):
        raise ValueError("REFERENCE_MANIFEST_MISMATCH")
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
    return int(report["summary"]["protocol_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
