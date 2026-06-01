from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .fetcher import refresh_sources
from .sources import SOURCE_BY_ID

DEFAULT_ENV_FILE = Path("/etc/hs-data-api.env")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Always trust /etc/hs-data-api.env for app settings (avoid stale shell exports).
        if key.startswith(("HS_API_", "HS_FETCH_", "HS_FLARESOLVERR_", "HS_IPROYAL_", "HS_PROXY_")):
            os.environ[key] = value
        elif key not in os.environ:
            os.environ[key] = value


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Hearthstone data sources.")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh")
    refresh.add_argument("--all", action="store_true", help="Refresh every configured source.")
    refresh.add_argument("--source", action="append", default=[], help="Refresh one source id.")
    sub.add_parser("proxy-check", help="Verify HS_FETCH_PROXY_URL egress IP.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args = parse_args(argv or sys.argv[1:])
    if args.command == "proxy-check":
        from .scrapers.proxy import check_proxy_health

        info = asyncio.run(check_proxy_health())
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    if args.command == "refresh":
        if not args.all and not args.source:
            print("Use --all or --source SOURCE_ID", file=sys.stderr)
            return 2
        missing = [source_id for source_id in args.source if source_id not in SOURCE_BY_ID]
        if missing:
            print(f"Unknown source ids: {', '.join(missing)}", file=sys.stderr)
            return 2
        results = asyncio.run(refresh_sources(None if args.all else args.source))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
