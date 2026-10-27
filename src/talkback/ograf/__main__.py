"""Run the OGraf Server standalone: `uv run python -m talkback.ograf --port 8090`."""

from __future__ import annotations

import argparse
import os

import uvicorn

from talkback.ograf.layout import TOKEN_ENV, control_token
from talkback.ograf.server import create_app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m talkback.ograf")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    a = ap.parse_args(argv)
    print(f"renderer pages: http://{a.host}:{a.port}/ograf/renderer/?renderer=world  (add &demo=1 to preview)")
    token = f"the {TOKEN_ENV} value" if os.environ.get(TOKEN_ENV) else control_token()
    print(f"calls that change graphics: Authorization: Bearer {token}")
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
