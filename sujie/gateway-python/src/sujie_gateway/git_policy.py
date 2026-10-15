"""Trusted Git delivery capability: concrete commit/ref/old value and configuration seal."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

REJECTED_GIT_OPERATIONS = (
    "GIT_REJECT_REMOTE",
    "GIT_REJECT_REF",
    "GIT_REJECT_COMMIT",
    "GIT_REJECT_OLD",
    "GIT_REJECT_STATE",
)
SEAL_FIELDS = (
    "repo_config_sha256",
    "remote_config_sha256",
    "head_file_sha256",
    "layout_sha256",
    "git_sha256",
)


class GitError(ValueError):
    """Constant codes; never propagate raw Git output, paths or user arguments."""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class GitPolicy:
    wire_json: str = field(repr=False)

    @classmethod
    def from_dict(cls, value: dict) -> GitPolicy:
        if not isinstance(value, dict) or set(value) != {
            "remote",
            "ref",
            "commit",
            "expected_old",
            "timeout_seconds",
            *SEAL_FIELDS,
        }:
            raise GitError("GIT_POLICY_INVALID")
        if not isinstance(value["remote"], str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{0,31}", value["remote"]
        ):
            raise GitError("GIT_POLICY_INVALID")
        ref = value["ref"]
        if (
            not isinstance(ref, str)
            or not re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9/_.-]{0,127}", ref)
            or ".." in ref
            or "//" in ref
            or ref.endswith(("/", ".", ".lock"))
            or any(part.startswith(".") or part.endswith(".lock") for part in ref.split("/"))
        ):
            raise GitError("GIT_POLICY_INVALID")
        for name in ("commit", "expected_old"):
            if (
                not isinstance(value[name], str)
                or not (name == "expected_old" and value[name] == "")
                and not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value[name])
            ):
                raise GitError("GIT_POLICY_INVALID")
        for name in SEAL_FIELDS:
            if not isinstance(value[name], str) or not re.fullmatch(r"[0-9a-f]{64}", value[name]):
                raise GitError("GIT_POLICY_INVALID")
        if type(value["timeout_seconds"]) is not int or not 1 <= value["timeout_seconds"] <= 5:
            raise GitError("GIT_POLICY_INVALID")
        return cls(json.dumps(value, sort_keys=True, separators=(",", ":")))

    def to_dict(self) -> dict:
        return json.loads(self.wire_json)

    @property
    def server_version(self) -> str:
        return "0.1.0-" + hashlib.sha256(self.wire_json.encode()).hexdigest()

    @property
    def state_hash(self) -> str:
        config = self.to_dict()
        return digest(
            {
                "commit": config["commit"],
                "expected_old": config["expected_old"],
                "seal": {name: config[name] for name in SEAL_FIELDS},
            }
        )

    @property
    def resource(self) -> str:
        return "/workspace/case-001/remote.git/" + self.to_dict()["ref"]

    def inspect(self, arguments: dict) -> dict:
        fields = ("remote", "ref", "commit", "expected_old", "state_hash")
        if (
            not isinstance(arguments, dict)
            or set(arguments) != set(fields)
            or any(
                not isinstance(arguments[name], str) or len(arguments[name]) > 1024
                for name in fields
            )
        ):
            raise GitError("GIT_ARGUMENTS_INVALID")
        config = self.to_dict()
        operations = {
            "remote": "GIT_REJECT_REMOTE",
            "ref": "GIT_REJECT_REF",
            "commit": "GIT_REJECT_COMMIT",
            "expected_old": "GIT_REJECT_OLD",
            "state_hash": "GIT_REJECT_STATE",
        }
        operation = next(
            (
                operations[name]
                for name in fields
                if arguments[name] != (self.state_hash if name == "state_hash" else config[name])
            ),
            "PINNED_LOCAL_GIT_PUSH",
        )
        return {
            "operation": operation,
            "resource": self.resource,
            "permitted": operation not in REJECTED_GIT_OPERATIONS,
        }

    def proposal(self) -> dict:
        config = self.to_dict()
        return {name: config[name] for name in ("remote", "ref", "commit", "expected_old")} | {
            "state_hash": self.state_hash
        }

    def review(self, arguments: dict) -> dict:
        if not self.inspect(arguments)["permitted"]:
            raise GitError("GIT_REVIEW_INVALID")
        return {
            "kind": "SEALED_LOCAL_GIT_PUSH",
            **arguments,
            "layout_sha256": self.to_dict()["layout_sha256"],
            "git_sha256": self.to_dict()["git_sha256"],
        }
