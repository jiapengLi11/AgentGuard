#!/usr/bin/env python3
"""Publish historical text evidence, not credentials, ledgers or environments.

This is a publication copy, not an experiment runner. Original source hashes in
an experiment are NEVER rewritten to make redacted records appear authentic.
Binary documents and nested archives require separate manual review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".md", ".csv", ".yaml", ".yml"}
PRIVATE_DIRS = {".git", ".venv", "node_modules", "secrets", "signatures", "__pycache__"}
PRIVATE_SUFFIXES = {".sqlite3", ".sqlite3-journal", ".sqlite", ".db", ".key", ".pem", ".p12", ".pfx"}
PRIVATE_NAMES = re.compile(r"originality.statement|签名|签字|原创性声明|credential|api.?key", re.I)
PERSONAL_PATH = re.compile(
    r"(?<![\w/])/(?:Users|home)/([A-Za-z0-9_][\w.-]*)(?=/)"
    r"|[A-Za-z]:([\\/]+)Users([\\/]+)([\w.-]+)(?=[\\/])"
)
SYNTHETIC_USERS = {"analyst", "user", "runner", "example", "test", "sujie", "sandbox"}
TOKEN = re.compile(r"sk-[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{24,}")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
NOTICE = """# Historical publication copy

These are earlier development records, including failed/incomplete runs. They
are NOT a new evaluation, the frozen submission baseline, or a general Agent ASR
benchmark. Model names and usage in individual records describe those runs only.

Private ledgers, credentials, signatures and dependencies are excluded. See
PUBLICATION_MANIFEST.json for original/published hashes and transformation counts.
Original experimental hashes are not rewritten. A redacted export may therefore
fail its original integrity verifier; publication integrity is a separate claim.
Unchanged records retain their original bytes. Raw originals remain private.
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def excluded(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        any(part.lower() in PRIVATE_DIRS for part in path.parts)
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or path.name.lower() == ".env"
        or path.name.lower().startswith(".env.")
        or bool(PRIVATE_NAMES.search(path.name))
    )


def redact(text: str, terms: list[str]) -> tuple[str, int]:
    count = 0
    for term in terms:
        if not term:
            raise ValueError("empty redaction term")
        count += text.count(term)
        text = text.replace(term, "PUBLIC_PERSON")

    def replace_path(match: re.Match) -> str:
        nonlocal count
        username = match.group(1) or match.group(4)
        if username in SYNTHETIC_USERS:
            return match.group(0)
        count += 1
        # Retain slash escaping so JSON and embedded JSON remain parseable.
        return match.group(0)[: -len(username)] + "PUBLIC_USER"

    return PERSONAL_PATH.sub(replace_path, text), count


def build(root: Path, output: Path, terms: list[str] | None = None) -> dict:
    root = root.resolve(strict=True)
    output = output.resolve()
    if not root.is_dir() or output.is_relative_to(root):
        raise ValueError("output must be outside the input directory")
    manifest = {"schema": "sujie-public-history-v1", "scope": "historical-publication-not-new-evaluation", "files": [], "excluded_counts": {}}
    members: list[tuple[str, bytes]] = []
    names = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinks require manual review")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if excluded(name):
            reason = "private-state-or-identity"
            manifest["excluded_counts"][reason] = manifest["excluded_counts"].get(reason, 0) + 1
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError("non-text evidence requires manual review")
        original = path.read_bytes()
        text = original.decode("utf-8-sig")
        if TOKEN.search(text) or PRIVATE_KEY.search(text):
            # Do not print the file body, matched value, or secret-bearing name.
            raise ValueError("credential candidate requires private manual review")
        text, changes = redact(text, terms or [])
        public_name, name_changes = redact(name, terms or [])
        published = text.encode("utf-8") if changes else original
        if public_name in names or public_name in {"PUBLICATION_README.md", "PUBLICATION_MANIFEST.json"}:
            raise ValueError("publication filename collision")
        names.add(public_name)
        if path.suffix.lower() == ".json":
            json.loads(published)
        members.append((public_name, published))
        manifest["files"].append({"path": public_name, "original_sha256": digest(original), "published_sha256": digest(published), "bytes": len(published), "redactions": changes + name_changes})
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an accidental replacement of original evidence.
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        members += [("PUBLICATION_README.md", NOTICE.encode()), ("PUBLICATION_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())]
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--redact-term", action="append", default=[], help="private term; never saved in the public manifest")
    args = parser.parse_args()
    result = build(args.root, args.out, args.redact_term)
    print(json.dumps({"files": len(result["files"]), "excluded_counts": result["excluded_counts"], "redactions": sum(row["redactions"] for row in result["files"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
