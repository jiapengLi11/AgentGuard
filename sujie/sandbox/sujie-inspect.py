"""Pinned stdin-only worker: never evaluate input, import workspace code or open files."""

import hashlib
import json
import sys


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"sha256", "json-summary"}:
        return 2
    data = sys.stdin.buffer.read(65537)
    if len(data) > 65536:
        return 3
    result = {"input_sha256": hashlib.sha256(data).hexdigest(), "bytes_read": len(data)}
    if sys.argv[1] == "json-summary":
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError, RecursionError):
            return 4
        result["json_type"] = {
            dict: "object",
            list: "array",
            str: "string",
            int: "number",
            float: "number",
            bool: "boolean",
            type(None): "null",
        }[type(value)]
        result["top_level_items"] = len(value) if isinstance(value, (dict, list)) else None
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
