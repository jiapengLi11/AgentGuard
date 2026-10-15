"""Normalize structured program/argv proposals under a trusted execution capability."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

REJECTED_OPERATIONS = (
    "EXEC_REJECT_ENCODED",
    "EXEC_REJECT_INLINE",
    "EXEC_REJECT_DOWNLOAD",
    "EXEC_REJECT_SHELL_SYNTAX",
    "EXEC_REJECT_PROGRAM",
    "EXEC_REJECT_ARGV",
    "EXEC_REJECT_RESOURCE",
)


class ExecutionError(ValueError):
    """Constant error codes; never reflect process arguments or file contents."""


def logical_resource(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or not re.fullmatch(r"case-[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+", value)
        or any(part in {".", ".."} for part in value.split("/"))
        or any(part.endswith((".", " ")) for part in value.split("/"))
        or any(
            part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
            for part in value.split("/")
        )
    ):
        raise ExecutionError("EXEC_RESOURCE_INVALID")
    return "/workspace/" + value


@dataclass(frozen=True)
class ExecutionPolicy:
    wire_json: str = field(repr=False)

    @classmethod
    def from_dict(cls, value: dict) -> ExecutionPolicy:
        if not isinstance(value, dict) or set(value) != {
            "resources",
            "modes",
            "worker_sha256",
            "interpreter_sha256",
            "max_input_bytes",
            "max_output_bytes",
            "timeout_seconds",
        }:
            raise ExecutionError("EXEC_POLICY_INVALID")
        if not isinstance(value["resources"], list) or not 1 <= len(value["resources"]) <= 64:
            raise ExecutionError("EXEC_POLICY_INVALID")
        for resource in value["resources"]:
            logical_resource(resource)
        if len(set(value["resources"])) != len(value["resources"]):
            raise ExecutionError("EXEC_POLICY_INVALID")
        if (
            not isinstance(value["modes"], list)
            or not value["modes"]
            or any(mode not in ("sha256", "json-summary") for mode in value["modes"])
        ):
            raise ExecutionError("EXEC_POLICY_INVALID")
        for name in ("worker_sha256", "interpreter_sha256"):
            if not isinstance(value[name], str) or not re.fullmatch(r"[0-9a-f]{64}", value[name]):
                raise ExecutionError("EXEC_POLICY_INVALID")
        for name, low, high in (
            ("max_input_bytes", 1, 65536),
            ("max_output_bytes", 128, 4096),
            ("timeout_seconds", 1, 5),
        ):
            if type(value[name]) is not int or not low <= value[name] <= high:
                raise ExecutionError("EXEC_POLICY_INVALID")
        return cls(json.dumps(value, sort_keys=True, separators=(",", ":")))

    def to_dict(self) -> dict:
        return json.loads(self.wire_json)

    @property
    def server_version(self) -> str:
        return "0.1.0-" + hashlib.sha256(self.wire_json.encode()).hexdigest()[:16]

    def inspect(self, arguments: dict) -> dict:
        if (
            not isinstance(arguments, dict)
            or set(arguments) - {"program", "argv", "input_resource", "env"}
            or not {"program", "argv", "input_resource"} <= set(arguments)
        ):
            raise ExecutionError("EXEC_ARGUMENTS_INVALID")
        program, argv = arguments["program"], arguments["argv"]
        if (
            not isinstance(program, str)
            or not 1 <= len(program) <= 1024
            or not isinstance(argv, list)
            or not 1 <= len(argv) <= 16
            or any(not isinstance(arg, str) or len(arg) > 4096 for arg in argv)
            or (arguments.get("env") is not None and not isinstance(arguments["env"], dict))
        ):
            raise ExecutionError("EXEC_ARGUMENTS_INVALID")
        resource = logical_resource(arguments["input_resource"])
        # Classification explains rejection; only the exact raw argv grammar is executable.
        view = unicodedata.normalize("NFKC", " ".join([program, *argv])).lower()
        if any(
            item in view
            for item in (
                "encodedcommand",
                "frombase64",
                "base64",
                "b64decode",
                "atob(",
            )
        ):
            operation = "EXEC_REJECT_ENCODED"
        elif any(
            item in view
            for item in (
                "http://",
                "https://",
                "invoke-webrequest",
                "downloadstring",
                "curl ",
                "wget ",
            )
        ):
            operation = "EXEC_REJECT_DOWNLOAD"
        elif any(character in view for character in ("|", ";", "&", "\n", "\r", "`", "#")):
            operation = "EXEC_REJECT_SHELL_SYNTAX"
        elif any(item in view for item in ("eval(", "exec(", "-c ", "-command ")):
            operation = "EXEC_REJECT_INLINE"
        elif program != "python":
            operation = "EXEC_REJECT_PROGRAM"
        elif (
            len(argv) != 4
            or argv[:3] != ["-I", "-S", "sujie-inspect.py"]
            or argv[3] not in self.to_dict()["modes"]
            or arguments.get("env", {})
        ):
            operation = "EXEC_REJECT_ARGV"
        elif arguments["input_resource"] not in self.to_dict()["resources"]:
            operation = "EXEC_REJECT_RESOURCE"
        else:
            operation = "EXEC_INSPECT_SHA256" if argv[3] == "sha256" else "EXEC_INSPECT_JSON"
        return {
            "operation": operation,
            "resource": resource,
            "permitted": operation not in REJECTED_OPERATIONS,
            "mode": argv[-1],
        }
