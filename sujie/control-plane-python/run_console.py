"""Launch the local operator console; generate a credential outside Agent environments."""

import argparse
import secrets
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "sandbox"), str(ROOT / "demo-agent")]

import uvicorn  # noqa: E402
from sujie_control.api import create_app  # noqa: E402
from sujie_control.model_runner import MODEL_SNAPSHOT  # noqa: E402
from sujie_demo_agent.bailian_agent import BailianChatModel, BailianCredentials  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model-budget-file", type=Path, help="Persistent shared budget ledger")
    parser.add_argument("--max-provider-requests", type=int, default=60)
    parser.add_argument("--max-reservation-units", type=int, default=1_000_000)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="Existing Bailian credential CSV; never passed to MCP or shown by the API",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    if (
        not 1 <= args.max_provider_requests <= 100_000
        or not 1 <= args.max_reservation_units <= 10_000_000_000
    ):
        parser.error("MODEL_BUDGET_CONFIG_INVALID")
    dist = ROOT / "console-vue/dist"
    if not (dist / "index.html").is_file():
        parser.error("Build the console first: cd console-vue; npm ci; npm run build")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            parser.error("PORT_ALREADY_IN_USE")
    model_factory = None
    if args.credentials_file:
        try:
            credentials = BailianCredentials.from_csv(args.credentials_file)
        except (OSError, ValueError):
            parser.error("MODEL_CREDENTIALS_INVALID")

        def model_factory():
            return BailianChatModel(credentials, model=MODEL_SNAPSHOT)

    token = secrets.token_urlsafe(32)
    credential = (
        ROOT
        / ".control-runtime"
        / ("operator-token.txt" if args.port == 8765 else f"operator-token-{args.port}.txt")
    )
    credential.parent.mkdir(parents=True, exist_ok=True)
    credential.write_text(token, encoding="utf-8")
    print(f"Operator console: http://127.0.0.1:{args.port}", flush=True)
    print(f"Local operator token file: {credential}", flush=True)
    print("This sealed local demo uses temporary tasks and synthetic data.", flush=True)
    print(f"Model integration: {'enabled' if model_factory else 'not configured'}", flush=True)
    budget_path = (
        args.model_budget_file or ROOT / ".control-runtime" / f"model-budget-{args.port}.sqlite3"
    )
    print(f"Persistent model budget file: {budget_path}", flush=True)
    uvicorn.run(
        create_app(
            token,
            dist_dir=dist,
            model_factory=model_factory,
            model_budget_path=budget_path,
            max_provider_requests=args.max_provider_requests,
            max_reservation_units=args.max_reservation_units,
        ),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
