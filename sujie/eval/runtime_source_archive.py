"""Archive exact source bytes for a finite validation, excluding credentials and caches."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def archive_runtime(out: Path, extra_files: tuple[str, ...]) -> str:
    files = {
        path
        for directory in (
            "gateway-python/src/sujie_gateway",
            "demo-agent/sujie_demo_agent",
            "control-plane-python/sujie_control",
            "mcp-servers",
            "sandbox",
        )
        for path in (ROOT / directory).rglob("*.py")
    }
    files.update((ROOT / "contracts/schemas").glob("*.json"))
    files.update((ROOT / "gateway-python/policies").glob("*.yaml"))
    files.update(
        ROOT / name
        for name in (
            "requirements.lock",
            "contracts/enums.json",
            "contracts/manifest.json",
            "assets/tokenizer/qwen3-local-manifest.json",
            "eval/runtime_source_archive.py",
            "eval/verify_operator_export.py",
            "eval/verify_sequence_export.py",
            "console-vue/src/App.vue",
            "console-vue/src/types.ts",
            "console-vue/package.json",
            "console-vue/package-lock.json",
            *extra_files,
        )
    )
    document = {
        "schema_version": "sujie-runtime-source-archive-v1",
        "scope": "exact UTF-8 runtime, executor, policy, schema, lock, UI source and selected validation files; excludes credentials, environment files and caches",
        "files": {
            str(path.relative_to(ROOT)).replace("\\", "/"): {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "utf8": path.read_bytes().decode("utf-8"),
            }
            for path in sorted(files)
        },
    }
    data = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    (out / "runtime-sources.json").write_bytes(data)
    return hashlib.sha256(data).hexdigest()
