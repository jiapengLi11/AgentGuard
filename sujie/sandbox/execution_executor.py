"""Real bounded worker processes with secure input snapshots and local receipts."""

import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path

from sujie_gateway.execution_policy import ExecutionError, ExecutionPolicy, logical_resource

WORKER = Path(__file__).with_name("sujie-inspect.py")


def policy_dict(resources: list[str]) -> dict:
    return {
        "resources": resources,
        "modes": ["sha256", "json-summary"],
        "worker_sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest(),
        "interpreter_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "max_input_bytes": 65536,
        "max_output_bytes": 1024,
        "timeout_seconds": 2,
    }


def snapshot(root: Path, resource: str, limit: int) -> bytes:
    logical_resource(resource)
    if os.name == "posix":
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(root, flags)
        try:
            parts = resource.split("/")
            for part in parts[:-1]:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            file_descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
            )
            with os.fdopen(file_descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ExecutionError("EXEC_INPUT_ALIAS_FORBIDDEN")
                data = stream.read(limit + 1)
        finally:
            os.close(descriptor)
    else:
        path = root
        for part in resource.split("/"):
            path /= part
            if path.exists():
                info = path.lstat()
                if path.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
                ):
                    raise ExecutionError("EXEC_INPUT_ALIAS_FORBIDDEN")
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ExecutionError("EXEC_INPUT_ALIAS_FORBIDDEN")
            data = stream.read(limit + 1)
    if len(data) > limit:
        raise ExecutionError("EXEC_INPUT_TOO_LARGE")
    return data


def execute(
    policy: ExecutionPolicy, arguments: dict, root: Path, cwd: Path, receipts: Path
) -> dict:
    proposal = policy.inspect(arguments)
    if not proposal["permitted"]:
        raise ExecutionError(proposal["operation"])
    config = policy.to_dict()
    if (
        hashlib.sha256(WORKER.read_bytes()).hexdigest() != config["worker_sha256"]
        or hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        != config["interpreter_sha256"]
    ):
        raise ExecutionError("EXEC_PROGRAM_CHANGED")
    try:
        data = snapshot(root, arguments["input_resource"], config["max_input_bytes"])
    except ExecutionError:
        raise
    except OSError:
        raise ExecutionError("EXEC_INPUT_UNAVAILABLE") from None
    command = [sys.executable, "-I", "-S", str(WORKER), proposal["mode"]]
    job_id = secrets.token_hex(16)

    def record(event, **details):
        with receipts.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": event,
                        "job_id": job_id,
                        "time_ns": time.time_ns(),
                        "operation": proposal["operation"],
                        "resource": arguments["input_resource"],
                        "input_sha256": hashlib.sha256(data).hexdigest(),
                        "program_sha256": config["interpreter_sha256"],
                        "worker_sha256": config["worker_sha256"],
                        "argv": ["-I", "-S", "sujie-inspect.py", proposal["mode"]],
                        **details,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    # cwd is a Host-owned empty directory outside the untrusted input workspace.
    with subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env={"SystemRoot": os.environ.get("SystemRoot", ""), "PYTHONIOENCODING": "utf-8"},
        shell=False,
    ) as process:
        record("PROCESS_STARTED", pid=process.pid)
        try:
            output, error = process.communicate(data, timeout=config["timeout_seconds"])
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            record("PROCESS_TIMEOUT", pid=process.pid, returncode=process.returncode)
            raise ExecutionError("EXEC_TIMEOUT") from None
        record(
            "PROCESS_FINISHED",
            pid=process.pid,
            returncode=process.returncode,
            stdout_bytes=len(output),
            stderr_bytes=len(error),
        )
    if process.returncode != 0:
        raise ExecutionError("EXEC_WORKER_FAILED")
    if len(output) > config["max_output_bytes"] or error:
        raise ExecutionError("EXEC_OUTPUT_INVALID")
    try:
        result = json.loads(output)
        if result["input_sha256"] != hashlib.sha256(data).hexdigest() or result[
            "bytes_read"
        ] != len(data):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ExecutionError("EXEC_OUTPUT_INVALID") from None
    return {
        "resource": arguments["input_resource"],
        "content": output.decode("utf-8"),
        "operation": proposal["operation"],
        "receipt_pid": process.pid,
        "receipt_job_id": job_id,
        **result,
    }
