#!/usr/bin/env python3
"""Package the report's exact runtime, current report, and optional built console.

The working tree's runtime is deliberately never copied into this package.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--console-dist", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    binding_path = repo / "competition/submission/latex/runtime-version.json"
    binding = json.loads(binding_path.read_text())
    record_raw = subprocess.check_output(
        ["git", "show", f"{binding['source_commit']}:{binding['validation_record']}"], cwd=repo
    )
    if hashlib.sha256(record_raw).hexdigest() != binding["validation_record_sha256"]:
        parser.error("Report validation record hash mismatch")
    record = json.loads(record_raw)
    baseline = record["code_baseline"]
    archive = subprocess.check_output(["git", "archive", baseline], cwd=repo)
    with tempfile.TemporaryDirectory(prefix="sujie-frozen-package-") as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")
        for name, expected in record["candidate_source_hashes"].items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected.removeprefix("sha256:"):
                parser.error(f"Runtime source mismatch: {name}")
        # Only authoring material is overlaid; the sujie/ tree stays at baseline.
        for folder in ("competition/submission/latex", "docs/validation"):
            target = root / folder
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(repo / folder, target, ignore=shutil.ignore_patterns(
                "*.pdf", "*.log", "*.aux", "*.out", "*.toc", "*.fls", "*.fdb_latexmk", "*.xdv", ".local-fonts"
            ))
        for name in ("部署说明-溯界.md", "测试样例与流程说明-溯界.md"):
            shutil.copy2(repo / "competition/submission" / name, root / "competition/submission" / name)
        if args.console_dist:
            # Dist must be built from the same package.json/package-lock.json.
            for name in ("package.json", "package-lock.json"):
                parent = args.console_dist.resolve().parent
                if (parent / name).read_bytes() != (root / "sujie/console-vue" / name).read_bytes():
                    parser.error("Console dependency manifest differs from the frozen runtime")
            # Check all tracked frontend sources too, not only the dependency lock.
            paths = subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", baseline, "sujie/console-vue"], cwd=repo, text=True
            ).splitlines()
            for name in paths:
                relative = Path(name).relative_to("sujie/console-vue")
                if (parent / relative).read_bytes() != (root / name).read_bytes():
                    parser.error(f"Console source differs from the frozen runtime: {relative}")
            notices = ["Third-party code in the prebuilt console (not claimed as original work).\n"]
            for package in ("vue", "@vue/shared", "@vue/reactivity", "@vue/runtime-core", "@vue/runtime-dom"):
                folder = parent / "node_modules" / package
                license_file = folder / "LICENSE"
                if not license_file.is_file():
                    parser.error(f"Missing third-party license: {package}; run npm ci before packaging")
                metadata = json.loads((folder / "package.json").read_text())
                notices.extend([f"\n--- {package} {metadata['version']} ---\n", license_file.read_text()])
            (root / "CONSOLE_THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices))
        (root / "PACKAGE_VERSION.json").write_text(json.dumps({
            "runtime_commit": baseline,
            "report_binding": binding,
            "runtime_files_checked": len(record["candidate_source_hashes"]),
            "console_prebuilt": args.console_dist is not None,
            "scope": "Python source distribution; dependencies require installation; no cloud credentials",
        }, ensure_ascii=False, indent=2) + "\n")
        (root / "run.py").write_text('''"""Run the packaged demo or local console after installing requirements.lock."""
import argparse
from pathlib import Path
import subprocess
import sys

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Python 3.12 is required; see PACKAGE_README.md")
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("mode", choices=("demo", "console"), nargs="?", default="demo")
p.add_argument("--port", type=int, default=8765)
a = p.parse_args()
root = Path(__file__).resolve().parent / "sujie"
cmd = [sys.executable, "dev.py", "demo"] if a.mode == "demo" else [
    sys.executable, "control-plane-python/run_console.py", "--port", str(a.port)]
raise SystemExit(subprocess.call(cmd, cwd=root))
''')
        command = [sys.executable, str(repo / "competition/submission/tools/build_source_package.py"),
                   "--root", str(root), "--out", str(args.out.resolve())]
        if args.console_dist:
            command.extend(["--console-dist", str(args.console_dist.resolve())])
        subprocess.run(command, check=True)
    print(f"Frozen runtime verified: {baseline}, {len(record['candidate_source_hashes'])} source files")


if __name__ == "__main__":
    main()
