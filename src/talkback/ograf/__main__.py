"""Run the OGraf Server standalone: `uv run python -m talkback.ograf --port 8090`."""

from __future__ import annotations

import argparse

import uvicorn

from talkback.ograf.server import create_app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m talkback.ograf")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    a = ap.parse_args(argv)
    print(f"renderer pages: http://{a.host}:{a.port}/ograf/renderer/?renderer=world  (add &demo=1 to preview)")
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
