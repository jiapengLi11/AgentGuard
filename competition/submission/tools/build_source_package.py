#!/usr/bin/env python3
"""Package the submission source tree for the '可执行程序' deliverable.

Contains source, tests, design docs and the one-key dev entry (sujie/dev.py).
Excludes virtual environments, caches, model caches, local runtime state,
budget ledgers, credentials, raw evaluation runs and any git history.

Usage:
  python3 build_source_package.py --out dist/源码包.zip [--root .]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

INCLUDE_DIRS = [
    "sujie",
    "competition/submission/latex",
    "docs/validation",
]
# Deliberately flat: only material a reviewer needs to build, run and audit the work.
INCLUDE_FILES = [
    ".github/workflows/sujie-ci.yml",
    "PACKAGE_VERSION.json",
    "CONSOLE_THIRD_PARTY_NOTICES.txt",
    "run.py",
    "competition/submission/部署说明-溯界.md",
    "competition/submission/测试样例与流程说明-溯界.md",
    "docs/ARCHITECTURE.md",
    "docs/SECURITY_MODEL.md",
    "docs/THREAT_MODEL.md",
    "LICENSE",
    "SECURITY.md",
    ".env.example",
]
# Authoring notes for the LaTeX project reference internal tooling; the package README covers usage.
EXCLUDE_FILES = {"competition/submission/latex/README.md"}

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    "model-cache", ".control-runtime", "dist", "htmlcov", ".mypy_cache", ".codex-doc-review", ".local-fonts",
}
EXCLUDE_SUFFIXES = (
    ".sqlite3", ".sqlite3-journal", ".pyc", ".pyo", ".log", ".key", ".pem", ".p12", ".pfx",
    ".DS_Store",
)
EXCLUDE_NAME_RE = re.compile(r"(credential|secret|api[_-]?key|honeytoken)", re.I)
TOKEN_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,})")
PEM_RE = re.compile(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----\s*(.*?)\s*-----END \1-----", re.S)
# Fixtures that announce themselves as non-functional key material (e.g. tests proving
# masking) are reported separately so real credentials are not buried in noise.
SYNTHETIC_MARKER_RE = re.compile(
    r"(synthetic|non-?functional|do-?not-?use|demo[- _]?key|fixture|placeholder|假密钥|测试用)",
    re.I,
)


def scan_text(text: str) -> str:
    """Classify one file body: 'real' credential, 'synthetic' fixture, or 'clean'."""
    if TOKEN_RE.search(text):
        return "real"
    verdicts: list[str] = []
    for match in PEM_RE.finditer(text):
        body = re.sub(r"[^A-Za-z0-9+/=]", "", match.group(2))
        window = text[max(0, match.start() - 800) : match.end() + 800]
        # Real private keys carry far more than 64 base64 chars; short bodies are placeholders.
        if len(body) < 64 or SYNTHETIC_MARKER_RE.search(window):
            verdicts.append("synthetic")
        else:
            verdicts.append("real")
    if "real" in verdicts:
        return "real"
    return "synthetic" if verdicts else "clean"

# Raw evaluation runs are handed over as a separate desensitized packet.
# The delivery snapshot under competition/submission/release/ duplicates artifacts
# that are either in this repo already (source) or shipped separately (PDFs).
EXCLUDE_PATH_PARTS = {("sujie", "eval", "reports", "runs"), ("competition", "submission", "release")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_excluded(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS or part.endswith(".egg-info") for part in rel.parts):
        return True
    if rel.as_posix() in EXCLUDE_FILES:
        return True
    if rel.name in ("",) or rel.name.startswith(".") and rel.name not in (".env.example", ".gitignore", ".gitattributes"):
        return True
    if rel.name.endswith(EXCLUDE_SUFFIXES):
        return True
    if EXCLUDE_NAME_RE.search(rel.name):
        return True
    for parts in EXCLUDE_PATH_PARTS:
        if tuple(rel.parts[: len(parts)]) == parts:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--console-dist", type=Path, help="Include a separately built Vue dist")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    files: list[tuple[Path, str]] = []
    for top in INCLUDE_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(root)
            if path.is_file() and not is_excluded(rel):
                files.append((path, rel.as_posix()))
    for name in INCLUDE_FILES:
        path = root / name
        if path.is_file():
            files.append((path, name))

    if args.console_dist:
        console = args.console_dist.resolve()
        if not (console / "index.html").is_file():
            ap.error("--console-dist must contain index.html")
        for path in sorted(console.rglob("*")):
            if path.is_symlink():
                ap.error("Console assets must not contain symlinks")
            if path.is_file() and not path.name.endswith(".map"):
                files.append((path, "sujie/console-vue/dist/" + path.relative_to(console).as_posix()))

    suspects: list[str] = []
    synthetic: list[str] = []
    for path, arc in files:
        if path.stat().st_size > 4 << 20:
            continue
        text = path.read_text("utf-8", errors="ignore")
        verdict = scan_text(text)
        if verdict == "real":
            suspects.append(arc)
        elif verdict == "synthetic":
            synthetic.append(arc)

    manifest = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arc in files:
            zf.write(path, arc)
            manifest.append({"path": arc, "bytes": path.stat().st_size, "sha256": sha256(path)})
        zf.writestr("PACKAGE_README.md", "\n".join([
            "# 溯界（Sujie）——面向大模型智能体的运行时安全网关",
            "",
            "本包为参赛作品「可执行程序」提交件，包含运行时源码、策略与测试、离线评测脚本、报告 LaTeX 源码与验证记录。",
            "",
            "## 目录",
            "",
            "| 路径 | 内容 |",
            "|---|---|",
            "| `sujie/` | 运行时：可信 Host 与模型循环、网关、控制面、策略 DSL、MCP 适配、测试与离线评测脚本 |",
            "| `competition/submission/latex/` | 作品报告 LaTeX 源码（五章正文、矢量图、参考文献） |",
            "| `competition/submission/部署说明-溯界.md` | 安装、启动与复现步骤（与随附 PDF 同源） |",
            "| `competition/submission/测试样例与流程说明-溯界.md` | 测试分层、样例组成与判定口径 |",
            "| `docs/ARCHITECTURE.md`、`docs/SECURITY_MODEL.md`、`docs/THREAT_MODEL.md` | 架构、安全模型与威胁模型 |",
            "| `docs/validation/` | 基线验证记录与三平台回归结果 |",
            "| `PACKAGE_MANIFEST.json` | 本包逐文件 SHA-256 清单 |",
            "",
            "## 快速开始",
            "",
            "```sh",
            "cd sujie",
            "python3 -m venv .venv",
            ".venv/bin/python -m pip install -r requirements.lock",
            *([] if args.console_dist else ["cd console-vue && npm ci && npm run build && cd .."]),
            ".venv/bin/python dev.py demo      # 确定性演示",
            ".venv/bin/python dev.py console   # 操作台 http://127.0.0.1:8765",
            ".venv/bin/python dev.py check     # lint + 全量回归",
            "```",
            "",
            "- Python 3.12.x；Node.js 20.19+ 或 22.12+ 仅前端控制台构建需要。",
            *( ["- 本包附带已构建控制台，直接启动无需 Node.js；修改前端后须重新构建。"] if args.console_dist else []),
            "- Windows：`py -3.12 -m venv .venv`，后续 Python 命令使用 `.venv\\Scripts\\python.exe`。",
            "- 离线检测复现：`dev.py eval-detection`、`dev.py eval-bypass`、`eval/run_public_injection.py`。",
            "- 规则检测指标为离线初筛结果，不是 Agent ASR，也不是网关实际阻断率。",
            "",
            "## 包内容说明",
            "",
            "本包不含虚拟环境、依赖缓存、模型缓存、本地运行状态、预算账本、任何凭据与原始评测运行记录；"
            "原始运行记录以脱敏证据包另行提交。",
            "",
            f"生成时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            "",
        ]))
        zf.writestr("PACKAGE_MANIFEST.json", json.dumps(
            {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "file_count": len(manifest), "files": manifest},
            ensure_ascii=False, indent=2,
        ))

    print(f"OK -> {out} ({out.stat().st_size} bytes, {len(files)} files)")
    if synthetic:
        print(f"note: {len(synthetic)} file(s) carry self-labelled synthetic key fixtures:")
        for s in synthetic:
            print("  " + s)
    if suspects:
        print("WARNING: credential-like strings found (no synthetic marker):")
        for s in suspects:
            print("  " + s)
        return 1
    print("credential scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
