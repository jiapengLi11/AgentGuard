"""Fetch only the fixed public JSON tokenizer asset; verify before installing."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets/tokenizer/qwen3-local-manifest.json"


def prepare() -> dict:
    manifest = json.loads(MANIFEST.read_bytes())
    revision = manifest["revision"]
    expected = f"https://huggingface.co/Qwen/Qwen3-0.6B/resolve/{revision}/tokenizer.json"
    if manifest["url"] != expected or not all(c in "0123456789abcdef" for c in revision):
        raise ValueError("TOKENIZER_MANIFEST_INVALID")
    asset = (ROOT / manifest["cache_path"]).resolve()
    if not asset.is_relative_to((ROOT / "model-cache").resolve()):
        raise ValueError("TOKENIZER_CACHE_INVALID")
    if asset.is_file():
        raw = asset.read_bytes()
    else:
        with urllib.request.urlopen(expected, timeout=45) as response:
            raw = response.read(32_000_001)
    if (
        not 1 <= len(raw) <= 32_000_000
        or len(raw) != manifest["bytes"]
        or hashlib.sha256(raw).hexdigest() != manifest["sha256"]
    ):
        raise ValueError("TOKENIZER_ASSET_MISMATCH")
    if not asset.is_file():
        asset.parent.mkdir(parents=True, exist_ok=True)
        temporary = asset.with_suffix(".verified.tmp")
        temporary.write_bytes(raw)
        temporary.replace(asset)
    return {
        "repository": manifest["repository"],
        "sha256": manifest["sha256"],
        "bytes": len(raw),
        "weights_downloaded": False,
    }


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(prepare()))
