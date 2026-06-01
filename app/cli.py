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
        if key.startswith(
            ("HS_API_", "HS_FETCH_", "HS_FLARESOLVERR_", "HS_IPROYAL_", "HS_PROXY_", "HSREPLAY_", "TELEGRAM_")
        ):
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
    sub.add_parser(
        "proxy-rotation-check",
        help="Sample egress IPs (rotation test; set HS_IPROYAL_ROTATE_PER_FETCH=true for max spread).",
    )
    login = sub.add_parser("hsreplay-login", help="Log into HSReplay Premium and save browser session.")
    imp = sub.add_parser(
        "hsreplay-import-storage",
        help="Import Playwright storage_state JSON (export from logged-in browser).",
    )
    imp.add_argument("path", type=Path, help="Path to storage_state JSON file.")
    enrich = sub.add_parser("enrich-links", help="Rebuild structured data from cached links (no refetch).")
    enrich.add_argument("--source", action="append", default=[], help="Source id to enrich.")
    enrich.add_argument("--all-hsreplay", action="store_true", help="All HSReplay sources.")
    sub.add_parser(
        "telegram-setup",
        help="Fetch latest Telegram bot updates, automatically detect chat ID, and configure notifications.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args = parse_args(argv or sys.argv[1:])
    if args.command == "proxy-check":
        from .scrapers.proxy import check_proxy_health

        info = asyncio.run(check_proxy_health())
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    if args.command == "proxy-rotation-check":
        from .scrapers.proxy import check_proxy_rotation

        info = asyncio.run(check_proxy_rotation(8))
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("rotating") or info.get("unique_ips", 0) >= 1 else 1
    if args.command == "hsreplay-login":
        from .config import hsreplay_storage_path
        from .hsreplay_auth import ensure_hsreplay_login
        from .scrapers.browser_pool import PatchrightPool
        from .scrapers.proxy import playwright_proxy

        async def _login() -> bool:
            pool = await PatchrightPool.get()
            ctx_kw: dict = {"viewport": {"width": 1440, "height": 900}}
            px = playwright_proxy("hsreplay_login")
            if px:
                ctx_kw["proxy"] = px
            context = await pool._browser.new_context(**ctx_kw)
            page = await context.new_page()
            try:
                return await ensure_hsreplay_login(page, context)
            finally:
                await context.close()

        ok = asyncio.run(_login())
        print(json.dumps({"ok": ok, "storage": str(hsreplay_storage_path())}, indent=2))
        return 0 if ok else 1
    if args.command == "hsreplay-import-storage":
        from .hsreplay_auth import import_storage_state

        dest = import_storage_state(args.path)
        print(json.dumps({"ok": True, "storage": str(dest)}, indent=2))
        return 0
    if args.command == "telegram-setup":
        from .config import telegram_bot_token
        import httpx

        token = telegram_bot_token()
        if not token:
            print("ERROR: TELEGRAM_BOT_TOKEN is not configured in /etc/hs-data-api.env", file=sys.stderr)
            return 1

        print(f"Connecting to Telegram Bot with token: {token}")
        print("Please send a message (e.g. /start) to your bot in Telegram now.")
        print("Waiting for updates...")

        async def _setup() -> int:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            async with httpx.AsyncClient(timeout=10.0) as client:
                for attempt in range(1, 11):
                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        data = resp.json()
                        updates = data.get("result", [])
                        if updates:
                            last_update = updates[-1]
                            message = last_update.get("message") or last_update.get("edited_message")
                            if message and "chat" in message:
                                chat = message["chat"]
                                chat_id = str(chat["id"])
                                first_name = chat.get("first_name", "")
                                username = chat.get("username", "")
                                print(f"\nDetected Telegram Chat!")
                                print(f"  Chat ID: {chat_id}")
                                print(f"  Name: {first_name} (@{username})")
                                
                                env_path = Path("/etc/hs-data-api.env")
                                if env_path.exists():
                                    lines = env_path.read_text(encoding="utf-8").splitlines()
                                    new_lines = []
                                    updated = False
                                    for line in lines:
                                        if line.strip().startswith("TELEGRAM_CHAT_ID="):
                                            new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
                                            updated = True
                                        else:
                                            new_lines.append(line)
                                    if not updated:
                                        new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
                                    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                                    print(f"Updated /etc/hs-data-api.env with TELEGRAM_CHAT_ID={chat_id}")
                                    os.environ["TELEGRAM_CHAT_ID"] = chat_id
                                else:
                                    print("WARNING: /etc/hs-data-api.env not found, could not save chat ID automatically.")

                                test_url = f"https://api.telegram.org/bot{token}/sendMessage"
                                test_msg = (
                                    "✅ <b>Hearthstone Parser Alert</b>\n\n"
                                    "Уведомления успешно настроены и подключены к этому чату! "
                                    "Вы будете получать сообщения о критических ошибках сбора данных."
                                )
                                try:
                                    await client.post(test_url, json={
                                        "chat_id": chat_id,
                                        "text": test_msg,
                                        "parse_mode": "HTML"
                                    })
                                    print("Sent test notification message to Telegram!")
                                except Exception as e:
                                    print(f"Failed to send test message: {e}", file=sys.stderr)
                                return 0
                    except Exception as e:
                        print(f"Error checking updates: {e}", file=sys.stderr)
                    print(f"Attempt {attempt}/10: No new messages found yet. Checking again in 3s...")
                    await asyncio.sleep(3)
                print("\nTimeout: No messages found in Telegram. Did you send a message to the bot?", file=sys.stderr)
                return 1

        return asyncio.run(_setup())
    if args.command == "enrich-links":
        from .hsreplay_extract import (
            extract_arena_cards_from_links,
            extract_arena_winning_decks_from_links,
            extract_bg_comps_from_links,
            extract_ranked_cards_from_links,
        )
        from .sources import SOURCES
        from .storage import load_dataset, save_dataset
        from .structured import build_structured

        ids = args.source or []
        if args.all_hsreplay:
            ids = [s.id for s in SOURCES if s.site == "hsreplay"]
        if not ids:
            print("Use --source ID or --all-hsreplay", file=sys.stderr)
            return 2
        for sid in ids:
            source = SOURCE_BY_ID[sid]
            ds = load_dataset(sid)
            if not ds:
                print(sid, "skip: no dataset")
                continue
            data = ds["data"]
            links = data.get("links") or []
            extracted: dict = {}
            if sid == "hsreplay_battlegrounds_comps":
                extracted = {"type": "bg_comps", "comps": extract_bg_comps_from_links(links), "blocked": False}
            elif sid.startswith("hsreplay_cards_"):
                extracted = {
                    "type": "card_stats",
                    "cards": extract_ranked_cards_from_links(links),
                    "blocked": False,
                }
            elif sid == "hsreplay_arena_winning_decks":
                extracted = {
                    "type": "arena_winning_decks",
                    "decks": extract_arena_winning_decks_from_links(
                        links, data.get("text_preview") or []
                    ),
                }
            elif sid == "hsreplay_arena_cards_advanced":
                extracted = {
                    "type": "arena_card_tiers",
                    "cards": extract_arena_cards_from_links(links),
                    "total_cards": None,
                }
            else:
                extracted = build_structured(source, data)
            data["hsreplay_extracted"] = extracted
            data["structured"] = extracted
            ds["data"] = data
            save_dataset(sid, ds)
            summary = {
                k: len(v) if isinstance(v, list) else v
                for k, v in extracted.items()
                if k != "type"
            }
            print(sid, json.dumps(summary, ensure_ascii=False))
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
