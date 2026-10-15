"""Controlled Operations MCP server; credentials and receiver URL stay in this process."""

import os
import secrets
import stat
import subprocess
import sys
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from mcp.server import MCPServer

ROOT = Path(os.environ["SUJIE_WORKSPACE_ROOT"]).resolve()
RECEIVER = os.environ["SUJIE_RECEIVER_URL"]
server = MCPServer("sujie-operations", version="0.1.0")


def _parts(resource: str) -> list[str]:
    parts = resource.split("/")
    if (
        resource.startswith("/")
        or "\\" in resource
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("invalid resource")
    return parts


def resolve(resource: str) -> Path:
    """Windows fallback rejects existing aliases before path resolution."""
    path = ROOT
    for part in _parts(resource):
        path = path / part
        if path.is_symlink():
            raise ValueError("symbolic link resource")
    return path


@contextmanager
def _parent_fd(resource: str, *, create: bool):
    """On POSIX, walk directories without following symlinks or changing roots."""
    parts = _parts(resource)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(ROOT, flags)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, parts[-1]
    finally:
        os.close(fd)


@server.tool(
    description="Read a file from the controlled synthetic workspace.", structured_output=True
)
def read_file(resource: str) -> dict[str, str]:
    if os.name == "posix":
        with _parent_fd(resource, create=False) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise ValueError("not a regular file")
                content = stream.read()
    else:
        path = resolve(resource)
        if not path.is_file():
            raise ValueError("file not found")
        content = path.read_text("utf-8")
    return {"resource": resource, "content": content}


@server.tool(
    description="Write a UTF-8 file in the controlled synthetic workspace.", structured_output=True
)
def write_file(resource: str, content: str) -> dict[str, object]:
    if os.name == "posix":
        with _parent_fd(resource, create=True) as (parent, name):
            try:
                existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None and not stat.S_ISREG(existing.st_mode):
                raise ValueError("not a regular file")
            temporary = f".sujie-{secrets.token_hex(12)}.tmp"
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
    else:
        path = resolve(resource)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = resolve(resource)
        temporary = path.parent / f".sujie-{secrets.token_hex(12)}.tmp"
        try:
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"resource": resource, "bytes_written": len(content.encode("utf-8"))}


@server.tool(
    description="Run the fixed SHA-256 worker on a bounded local report in the synthetic workspace.",
    structured_output=True,
)
def exec_hash_report(resource: str) -> dict[str, object]:
    """A real child process with a fixed program and stdin-only data, not a shell."""
    if not resource.startswith("case-001/output/"):
        raise ValueError("report resource required")
    _parts(resource)
    if os.name == "posix":
        with _parent_fd(resource, create=False) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise ValueError("not a regular file")
                content = stream.read(65537)
    else:
        path = resolve(resource)
        if not path.is_file():
            raise ValueError("file not found")
        with path.open("rb") as stream:
            content = stream.read(65537)
    if len(content) > 65536:
        raise ValueError("report too large")
    worker = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())",
        ],
        input=content,
        capture_output=True,
        check=True,
        timeout=2,
        env={
            "PYTHONIOENCODING": "utf-8",
            "SystemRoot": os.environ.get("SystemRoot", ""),
        },
    )
    return {
        "resource": resource,
        "sha256": worker.stdout.decode("ascii").strip(),
        "bytes_hashed": len(content),
    }


@server.tool(
    description="Send data only to the sealed local receiver label.", structured_output=True
)
def send_data(destination: str, content: str) -> dict[str, object]:
    if destination != "receiver":
        raise ValueError("destination not available")
    request = urllib.request.Request(RECEIVER, data=content.encode(), method="POST")
    with urllib.request.urlopen(request, timeout=2) as response:
        return {"destination": destination, "status": response.status}


if __name__ == "__main__":
    server.run("stdio")
