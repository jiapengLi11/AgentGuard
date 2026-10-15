"""Host-pinned evidence memory: one key, fixed versions and one allowed CAS transition."""

import hashlib
import json
import re
from dataclasses import dataclass, field


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MemoryError(ValueError):
    """Constant diagnostic codes only."""


@dataclass(frozen=True)
class MemoryPolicy:
    wire_json: str = field(repr=False)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {
            "namespace",
            "key",
            "initial_revision",
            "versions",
            "write_revision",
            "max_bytes",
        }:
            raise MemoryError("MEMORY_POLICY_INVALID")
        if any(
            not isinstance(value[name], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value[name])
            for name in ("namespace", "key")
        ):
            raise MemoryError("MEMORY_POLICY_INVALID")
        revision, write = value["initial_revision"], value["write_revision"]
        if (
            type(revision) is not int
            or not 0 <= revision <= 8
            or (
                write is not None and (type(write) is not int or write != revision + 1 or write > 8)
            )
        ):
            raise MemoryError("MEMORY_POLICY_INVALID")
        versions = value["versions"]
        last = write if write is not None else revision
        if (
            not isinstance(versions, dict)
            or set(versions) != {str(n) for n in range(1, last + 1)}
            or any(
                not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                for digest in versions.values()
            )
            or type(value["max_bytes"]) is not int
            or not 1 <= value["max_bytes"] <= 32768
        ):
            raise MemoryError("MEMORY_POLICY_INVALID")
        return cls(json.dumps(value, sort_keys=True, separators=(",", ":")))

    def to_dict(self):
        return json.loads(self.wire_json)

    @property
    def server_version(self):
        return "0.2.0-" + content_hash(self.wire_json)

    def inspect(self, writing: bool, arguments: dict):
        keys = {"key", "content", "expected_revision", "expected_hash"} if writing else {"key"}
        if not isinstance(arguments, dict) or set(arguments) != keys:
            raise MemoryError("MEMORY_ARGUMENTS_INVALID")
        config = self.to_dict()
        operation = "MEMORY_WRITE_PINNED" if writing else "MEMORY_READ_PINNED"
        if arguments["key"] != config["key"]:
            operation = "MEMORY_REJECT_KEY"
        elif writing:
            if (
                not isinstance(arguments["content"], str)
                or len(arguments["content"].encode()) > config["max_bytes"]
            ):
                operation = "MEMORY_REJECT_CONTENT"
            elif (
                type(arguments["expected_revision"]) is not int
                or arguments["expected_revision"] != config["initial_revision"]
                or arguments["expected_hash"]
                != config["versions"].get(str(config["initial_revision"]), "")
            ):
                operation = "MEMORY_REJECT_VERSION"
            elif (
                config["write_revision"] is None
                or content_hash(arguments["content"])
                != config["versions"][str(config["write_revision"])]
            ):
                operation = "MEMORY_REJECT_CONTENT"
        return {"operation": operation, "permitted": not operation.startswith("MEMORY_REJECT_")}
