"""Local, pinned API-text-field token offsets; never fetch assets at runtime."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path

from sujie_gateway.model_context import ContextError, RequestSnapshot, safe_path

ROOT = Path(__file__).resolve().parents[2]


class LocalTokenMapper:
    def __init__(self, manifest_path: Path, asset_path: Path):
        manifest = json.loads(manifest_path.read_bytes())
        raw = asset_path.read_bytes()
        if (
            manifest.get("schema_version") != "sujie-local-tokenizer-v1"
            or hashlib.sha256(raw).hexdigest() != manifest.get("sha256")
            or len(raw) != manifest.get("bytes")
            or importlib.metadata.version("tokenizers") != manifest.get("tokenizers_version")
        ):
            raise ContextError("MODEL_TOKENIZER_MISMATCH")
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_buffer(raw)
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        self.manifest = manifest

    @classmethod
    def available_default(cls) -> LocalTokenMapper | None:
        manifest = ROOT / "assets/tokenizer/qwen3-local-manifest.json"
        if not manifest.is_file():
            return None
        record = json.loads(manifest.read_bytes())
        asset = ROOT / record["cache_path"]
        if not asset.is_file():
            return None
        return cls(manifest, asset)

    def map(self, snapshot: RequestSnapshot) -> dict:
        fields, total = [], 0
        for item in snapshot.fields:
            encoding = self._tokenizer.encode(item.text, add_special_tokens=False)
            offsets = encoding.offsets
            byte_offsets = [0]
            for char in item.text:
                byte_offsets.append(byte_offsets[-1] + len(char.encode("utf-8")))
            tokens = []
            for index, (start, end) in enumerate(offsets):
                if not 0 <= start < end <= len(item.text):
                    raise ContextError("MODEL_TOKEN_OFFSETS_INVALID")
                matched = [span for span in item.spans if span.start < end and span.end > start]
                tokens.append(
                    {
                        "index": index,
                        "char_start": start,
                        "char_end": end,
                        "byte_start": byte_offsets[start],
                        "byte_end": byte_offsets[end],
                        "artifact_ids": sorted(
                            {span.artifact_id for span in matched} | set(item.inherited_artifacts)
                        ),
                        "mapping": "INHERITED"
                        if item.inherited_artifacts
                        else "LITERAL_MATCH"
                        if matched
                        else "UNATTRIBUTED",
                    }
                )
            fields.append(
                {
                    "field_index": item.index,
                    "path": safe_path(item.path),
                    "characters": len(item.text),
                    "utf8_bytes": byte_offsets[-1],
                    "tokens": tokens,
                }
            )
            total += len(tokens)
        return {
            "status": "LOCAL_FIELD_OFFSETS",
            "provider_tokenization": "UNKNOWN",
            "chat_template_equivalence": "NOT_VERIFIED",
            "tokenizer_repository": self.manifest["repository"],
            "tokenizer_revision": self.manifest["revision"],
            "tokenizer_sha256": self.manifest["sha256"],
            "tokenizers_version": self.manifest["tokenizers_version"],
            "token_count": total,
            "fields": fields,
        }
