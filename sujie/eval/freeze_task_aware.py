"""Write a classification protocol before querying any held-out case."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent")]

from task_aware_protocol import digest, freeze  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("PROTOCOL_ALREADY_EXISTS")
    protocol = freeze(args.source_root, args.split_manifest)
    raw = (json.dumps(protocol, ensure_ascii=False, indent=2) + "\n").encode()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(raw)
    print(
        json.dumps(
            {
                "protocol_sha256": digest(raw),
                "pairs": {name: len(rows) for name, rows in protocol["partitions"].items()},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
