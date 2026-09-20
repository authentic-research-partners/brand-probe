"""The sole CLI event-loop boundary."""

import asyncio
import sys
import httpx
from pydantic import ValidationError
from brandprobe.cli import parser, run_command
from brandprobe.exceptions import BrandProbeError


def main() -> None:
    args = parser().parse_args()
    if args.command == "serve":
        import uvicorn
        from brandprobe.web import create_app

        uvicorn.run(create_app(args.root.resolve()), host="127.0.0.1", port=args.port)
        return
    try:
        asyncio.run(run_command(args))
    except (BrandProbeError, ValidationError, OSError, httpx.HTTPError) as exc:
        print(f"BrandProbe: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
