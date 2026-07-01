from __future__ import annotations

from ..sources import Source

_EXTRACT_JS = """
() => {
  const clean = (s) => (s || "").replace(/\\s+/g, " ").trim();
  const root = document.querySelector("#react-root") || document.body;
  const lines = (root.innerText || "")
    .split("\\n")
    .map(clean)
    .filter((l) => l.length > 0);

  const tables = [];
  document.querySelectorAll("table").forEach((table, index) => {
    const rows = [];
    table.querySelectorAll("tr").forEach((tr) => {
      const cells = [...tr.querySelectorAll("th,td")].map((c) => clean(c.innerText));
      if (cells.some((c) => c)) rows.push(cells);
    });
    if (rows.length >= 2) tables.push({ index, rows });
  });

  const card_rows = [];
  document.querySelectorAll("table tbody tr, table tr").forEach((tr) => {
    const link = tr.querySelector('a[href*="/cards/"]');
    if (!link) return;
    const cells = [...tr.querySelectorAll("th,td")].map((c) => clean(c.innerText));
    if (cells.length >= 2) card_rows.push(cells);
  });

  const card_entries = [];
  const card_grid_rows = [];
  const seenHref = new Set();
  const collectRow = (el) => {
    const link = el.querySelector('a[href*="/cards/"]');
    if (!link) return;
    const href = link.getAttribute("href") || "";
    if (!href || seenHref.has(href)) return;
    seenHref.add(href);
    const m = href.match(/(\\d{3,})/);
    const dbfId = m ? parseInt(m[1], 10) : null;
    const rowText = clean(el.innerText || "");
    const cells = [...el.querySelectorAll("td, th, span, div")]
      .map((c) => clean(c.innerText))
      .filter((t) => t && t.length < 80);
    const item = { href, dbfId, rowText, cells: cells.slice(0, 12) };
    card_entries.push(item);
    if (/%/.test(rowText)) card_grid_rows.push(item);
  };
  ["[role=\\"row\\"]", "div[class*=\\"CardRow\\"]", "div[class*=\\"card-row\\"]"].forEach((sel) => {
    document.querySelectorAll(sel).forEach(collectRow);
  });
  document.querySelectorAll('a[href*="/cards/"]').forEach((link) => {
    const row = link.closest('[role="row"], tr, li, div');
    if (row) collectRow(row);
  });

  let authenticated = null;
  const ud = document.querySelector("script#userdata");
  if (ud && ud.textContent) {
    try {
      authenticated = !!JSON.parse(ud.textContent).user?.is_authenticated;
    } catch (e) {}
  }
  return { lines, tables, card_rows, card_entries, card_grid_rows, authenticated };
}
"""

_LOAD_ERROR_MARKERS = (
    "try again later",
    "повторите попытку",
    "could not load data",
    "не удалось загрузить",
)


async def dismiss_consent(page) -> None:
    for sel in (
        "#onetrust-accept-btn-handler",
        'button:has-text("Consent")',
        'button:has-text("AGREE")',
        'button:has-text("Accept all")',
    ):
        try:
            await page.click(sel, timeout=2500)
            await page.wait_for_timeout(1000)
            return
        except Exception:
            continue


async def scroll_for_lazy_content(page, source: Source) -> None:
    scroll_pages = 7 if source.id.startswith("hsreplay_cards_") else 6
    if source.id == "hsreplay_arena_cards_advanced":
        scroll_pages = 15
    for _ in range(scroll_pages):
        await page.evaluate("window.scrollBy(0, Math.max(window.innerHeight, 900))")
        await page.wait_for_timeout(1200)


async def _wait_data_loaded(page, source: Source) -> None:
    try:
        await page.wait_for_selector("#react-root", state="attached", timeout=15000)
    except Exception:
        pass

    for loop_idx in range(8):
        try:
            text = (await page.locator("#react-root").inner_text(timeout=3000)).lower()
        except Exception:
            await page.wait_for_timeout(2000)
            continue

        if not any(marker in text for marker in _LOAD_ERROR_MARKERS):
            if source.id.startswith("hsreplay_cards_"):
                try:
                    has_cards = await page.locator('a[href*="/cards/"]').count() > 0
                except Exception:
                    has_cards = False
                if has_cards and ("winrate" in text or "win rate" in text or "колод" in text):
                    return
            else:
                return
        for label in ("All Players", "Все игроки", "All Minion Types"):
            try:
                await page.click(f"text={label}", timeout=2000)
                await page.wait_for_timeout(2000)
            except Exception:
                pass
        await page.wait_for_timeout(4000)


async def capture_hsreplay_snapshot(page, source: Source) -> dict:
    if source.site != "hsreplay":
        return {}
    await dismiss_consent(page)
    await page.wait_for_timeout(3000)
    await _wait_data_loaded(page, source)
    await scroll_for_lazy_content(page, source)
    await _wait_data_loaded(page, source)
    await page.wait_for_timeout(2000)
    data = await page.evaluate(_EXTRACT_JS)
    return data if isinstance(data, dict) else {}
