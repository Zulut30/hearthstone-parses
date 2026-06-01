const $ = (sel) => document.querySelector(sel);

const LABELS = {
  hsguru_meta_standard_legend: "Мета Standard · Legend",
  hsguru_meta_standard_diamond_4to1: "Мета Standard · Diamond",
  hsguru_meta_wild_legend: "Мета Wild · Legend",
  hsguru_meta_wild_diamond_4to1: "Мета Wild · Diamond",
  hsguru_matchups_legend: "Матчапы · Legend",
  hsguru_matchups_diamond_4to1: "Матчапы · Diamond",
  hsguru_streamer_decks_legend_1000: "Колоды стримеров",
  hsreplay_arena: "Арена · матрица классов",
  hsreplay_arena_cards_advanced: "Арена · тир карт",
  hsreplay_arena_legendaries: "Арена · легендарные группы",
  hsreplay_arena_winning_decks: "Арена · виновые колоды",
  hsreplay_decks_trending: "Трендовые колоды",
  hsreplay_cards_legend_included_winrate: "Карты · winrate",
  hsreplay_cards_legend_included_popularity: "Карты · popularity",
  hsreplay_battlegrounds_heroes: "BG · герои",
  hsreplay_battlegrounds_comps: "BG · компы",
  hsreplay_battlegrounds_trinkets_lesser: "BG · малые тринкеты",
  hsreplay_battlegrounds_trinkets_greater: "BG · большие тринкеты",
};

async function loadOverview() {
  const res = await fetch("/demo/overview");
  const data = await res.json();
  $("#stats").innerHTML =
    `Источников OK: <strong>${data.ok_count}</strong> / ${data.total} · ` +
    `<a href="/docs">API</a>`;

  const list = $("#source-list");
  list.innerHTML = "";
  for (const s of data.sources) {
    const btn = document.createElement("button");
    btn.className = "source-btn";
    btn.dataset.id = s.source_id;
    const label = LABELS[s.source_id] || s.source_id;
    btn.innerHTML = `
      <span class="id">${label}</span>
      <span class="meta">${s.site} · ${s.category}</span>
      <span class="badge ${s.state === "ok" ? "ok" : "err"}">${s.state}</span>
    `;
    btn.onclick = () => selectSource(s.source_id, btn);
    list.appendChild(btn);
  }
}

async function selectSource(id, btn) {
  document.querySelectorAll(".source-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  $("#placeholder").classList.add("hidden");
  const detail = $("#detail");
  detail.classList.remove("hidden");
  detail.innerHTML = "<p>Загрузка…</p>";

  const res = await fetch(`/demo/view/${id}`);
  const payload = await res.json();
  detail.innerHTML = renderDetail(payload);
}

function viewType(v) {
  return v.type || v.kind || "";
}

function renderCards(cards) {
  if (!cards || !cards.length) {
    return "<p class='muted'>Нет декодированных карт.</p>";
  }
  return `<ul class="cards-list">${cards
    .map(
      (c) =>
        `<li><strong>${c.count || 1}×</strong> ${escapeHtml(c.name)} — ` +
        `<code>id: ${c.id || "?"}</code> <code>dbfId: ${c.dbfId ?? "?"}</code></li>`
    )
    .join("")}</ul>`;
}

function renderTableFromObjects(rows, columns) {
  if (!rows.length) return "<p class='muted'>Нет строк.</p>";
  const cols = columns || Object.keys(rows[0]);
  let html = "<table class='simple'><thead><tr>";
  for (const c of cols) html += `<th>${escapeHtml(c)}</th>`;
  html += "</tr></thead><tbody>";
  for (const row of rows.slice(0, 50)) {
    html += "<tr>";
    for (const c of cols) html += `<td>${escapeHtml(String(row[c] ?? ""))}</td>`;
    html += "</tr>";
  }
  html += "</tbody></table>";
  return html;
}

function renderCardStatsTable(cards) {
  return renderTableFromObjects(
    cards.map((c) => ({
      Карта: c.name,
      Мана: c.mana ?? c.cost ?? "",
      "Deck WR": c.deck_winrate || c.deck_popularity || "",
      "Avg copies": c.avg_copies || "",
      "Times played": c.times_played || "",
      "Pick rate": c.pick_rate || "",
      "id / dbfId": `${c.id || "?"} / ${c.dbfId ?? "?"}`,
    })),
    ["Карта", "Мана", "Deck WR", "Avg copies", "Times played", "Pick rate", "id / dbfId"]
  );
}

function renderDetail(p) {
  if (!p.ok) return `<h2>Ошибка</h2><p>${escapeHtml(p.message || "")}</p>`;

  const v = p.view;
  const t = viewType(v);
  let body = "";

  if (t === "arena_legendary_groups" && v.groups) {
    body = `<div class="block"><h3>Легендарные группы (${v.groups.length})</h3>`;
    for (const g of v.groups) {
      const key = g.key_card || g.legendary_card || {};
      body += `<div class="strategy"><h4>${escapeHtml(key.name || key.card_id || "Легендарка")}</h4>
        <p class="muted">${escapeHtml(g.class || "")} · id: ${escapeHtml(key.id || "?")} · dbfId: ${escapeHtml(String(key.dbfId ?? "?"))}</p>
        <p>Winrate: <strong>${escapeHtml(g.winrate || "?")}</strong>${g.pick_rate ? " · Pick: " + escapeHtml(g.pick_rate) : ""}${g.offer_rate ? " · Offer: " + escapeHtml(g.offer_rate) : ""}</p>
        <p><strong>Карты пакета</strong></p>${renderCards(g.cards)}</div>`;
    }
    body += "</div>";
  } else if (t === "arena_winning_decks" && v.decks) {
    body = `<div class="block"><h3>Виновые колоды арены (${v.decks.length})</h3>`;
    for (const d of v.decks) {
      const cls = d.main_class || d.class || "?";
      body += `<div class="strategy"><h4>${escapeHtml(cls)} · ${escapeHtml(d.record || "?")} · ${escapeHtml(d.player || "?")}</h4>
        <p class="muted">${escapeHtml(d.played_at || "")}${d.region ? " · " + escapeHtml(d.region) : ""}${d.draft_id ? " · draft " + escapeHtml(String(d.draft_id)) : ""}${d.legendary_group ? " · Группа: " + escapeHtml(d.legendary_group) : ""}</p>
        ${d.hero_power_class ? `<p class="muted">Hero power: ${escapeHtml(d.hero_power_class)}</p>` : ""}
        <p><strong>Финальная колода</strong> (${(d.final_deck || []).reduce((s, c) => s + (c.count || 1), 0)} карт, ${(d.final_deck || []).length} уник.)</p>${renderCards(d.final_deck || [])}
        <p><strong>Сброшено (redraft)</strong></p>${renderCards(d.discarded || d.redraft?.discarded || [])}
        <p><strong>Добавлено (redraft)</strong></p>${renderCards(d.added || d.redraft?.added || [])}
        ${d.package_cards?.length ? `<p><strong>Легендарный пакет</strong></p>${renderCards(d.package_cards)}` : ""}</div>`;
    }
    body += "</div>";
  } else if (t === "trending_decks" && v.decks) {
    body = `<div class="block"><h3>Трендовые колоды (${v.decks.length})</h3>`;
    body += renderTableFromObjects(
      v.decks.map((d) => ({
        Колодa: d.name,
        Winrate: d.winrate,
        Games: d.games,
        Duration: d.duration || "",
        "HSReplay ID": d.hsreplay_deck_id,
      })),
      ["Колодa", "Winrate", "Games", "Duration", "HSReplay ID"]
    );
    body += "</div>";
  } else if (t === "bg_heroes" && v.blocked) {
    body = `<div class="block warn"><h3>Герои BG не загрузились</h3>
      <p>HSReplay вернул «Повторите попытку позже». Обновите источник или проверьте сессию.</p></div>`;
  } else if (t === "bg_heroes" && v.heroes) {
    body = `<div class="block"><h3>Герои Battlegrounds (${v.heroes.length})</h3>`;
    body += renderTableFromObjects(
      v.heroes.map((h) => ({
        Герой: h.hero,
        "Pick Rate": h.pick_rate || "",
        Описание: (h.description || "").slice(0, 100),
      })),
      ["Герой", "Pick Rate", "Описание"]
    );
    body += "</div>";
  } else if (t === "arena_class_matrix") {
    body = `<div class="block"><h3>Арена · классы и матчапы</h3>`;
    if (v.classes?.length) {
      body += `<h4>Винрейт классов (${v.classes.length})</h4>`;
      body += renderTableFromObjects(
        v.classes.map((c) => ({
          Класс: c.class,
          Winrate: c.winrate || c.win_rate,
          Drafts: c.num_drafts ?? "",
          "Pick %": c.pick_rate ?? "",
          "7+ wins %": c.pct_7_plus ?? "",
        })),
        ["Класс", "Winrate", "Drafts", "Pick %", "7+ wins %"]
      );
    }
    if (v.matchups?.length) {
      body += `<h4>Двухклассовые матчапы (${v.matchups.length})</h4>`;
      if (v.matchups[0]?.class_a) {
        body += renderTableFromObjects(v.matchups.slice(0, 80), ["class_a", "class_b", "winrate"]);
      } else {
        body += renderTableFromObjects(v.matchups.slice(0, 25));
      }
    }
    body += "</div>";
  } else if (t === "matchups" && v.matchups && v.matchups.length) {
    body = `<div class="block"><h3>Матрица матчапов (${v.matchups.length} ячеек)</h3>`;
    body += renderTableFromObjects(
      v.matchups.slice(0, 100).map((m) => ({
        Архетип: m.archetype,
        Против: m.vs,
        Winrate: m.winrate,
      })),
      ["Архетип", "Против", "Winrate"]
    );
    if (v.matchups.length > 100) {
      body += `<p class="muted">Показаны первые 100. API: <code>/datasets/${escapeHtml(p.source_id)}</code></p>`;
    }
    body += "</div>";
  } else if (t === "meta" && v.strategies) {
    body = `<div class="block"><h3>Стратегии (${v.strategies.length})</h3>`;
    body += renderTableFromObjects(v.strategies.slice(0, 30));
    body += "</div>";
  } else if (t === "streamer_decks" && v.decks) {
    body = `<div class="block"><h3>Колоды стримеров (${v.decks.length})</h3>`;
    for (const d of v.decks) {
      body += `<div class="strategy"><h4>${escapeHtml(d.strategy)}</h4>
        <p>${escapeHtml(d.streamer || "")} · ${escapeHtml(d.format || "")} · ${escapeHtml(d.record || "")}</p>
        ${renderCards(d.cards)}</div>`;
    }
    body += "</div>";
  } else if (t === "card_stats" && v.blocked) {
    body = `<div class="block warn"><h3>Требуется сессия HSReplay</h3>
      <p>Импортируйте cookies и выполните refresh.</p></div>`;
  } else if (t === "card_stats" && v.cards && v.cards.length) {
    body = `<div class="block"><h3>Карты (${v.cards.length})</h3>${renderCardStatsTable(v.cards)}</div>`;
  } else if (t === "arena_card_tiers" && v.cards && v.cards.length) {
    body = `<div class="block"><h3>Тир-лист арены (${v.cards.length} карт)</h3>`;
    if (v.total_cards) body += `<p class="muted">Всего в базе: ${escapeHtml(v.total_cards)}</p>`;
    body += renderTableFromObjects(
      v.cards.map((c) => ({
        Карта: c.name,
        Тир: c.tier || "",
        Winrate: c.deck_winrate || c.pick_rate || "",
        Мана: c.mana ?? c.cost ?? "",
        "id / dbfId": `${c.id || "?"} / ${c.dbfId ?? "?"}`,
      })),
      ["Карта", "Тир", "Winrate", "Мана", "id / dbfId"]
    );
    body += "</div>";
  } else if (t === "bg_trinkets" && v.trinkets && v.trinkets.length) {
    body = `<div class="block"><h3>Тринкеты (${v.trinkets.length})</h3>`;
    body += renderTableFromObjects(
      v.trinkets.map((x) => ({
        Тринкет: x.name,
        "Pick Rate": x.pick_rate || "",
        "Avg placement": x.avg_placement || "",
        Описание: (x.description || "").slice(0, 80),
      })),
      ["Тринкет", "Pick Rate", "Avg placement", "Описание"]
    );
    body += "</div>";
  } else if (t === "bg_comps" && v.comps && v.comps.length) {
    body = `<div class="block"><h3>Компы Battlegrounds (${v.comps.length})</h3>`;
    for (const c of v.comps) {
      const title = c.title || c.name || c.slug || "?";
      body += `<div class="strategy"><h4>${escapeHtml(title)} <span class="muted">#${escapeHtml(String(c.comp_id || c.source_id || ""))}</span></h4>`;
      if (c.url) body += `<p class="muted"><a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.url)}</a></p>`;
      if (c.main_cards?.length) {
        body += `<p><strong>Основа (${c.main_cards.length})</strong></p>${renderCards(c.main_cards)}`;
      }
      if (c.additional_cards?.length) {
        body += `<p><strong>Доп. миньоны (${c.additional_cards.length})</strong></p>${renderCards(c.additional_cards)}`;
      }
      body += "</div>";
    }
    body += "</div>";
  } else if (t === "bg_comps") {
    body = `<div class="block warn"><h3>Компы BG</h3>
      <p>Данные не загрузились. Нужна сессия HSReplay и refresh.</p></div>`;
  } else if (t === "bg_page" && v.items) {
    body = `<div class="block"><ul class="lines">${v.items.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ul></div>`;
  } else if (v.lines) {
    body = `<div class="block"><ul class="lines">${v.lines.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}</ul></div>`;
  }

  return `
    <h2>${escapeHtml(LABELS[p.source_id] || p.source_id)}</h2>
    <p class="meta-line">
      ${escapeHtml(p.site)} · ${escapeHtml(p.category)} · обновлено: ${escapeHtml(p.fetched_at || "?")}
      · <a href="${escapeHtml(p.url)}" target="_blank">источник</a>
    </p>
    ${body || "<p class='muted'>Нет структурированных данных.</p>"}
  `;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

loadOverview().catch((e) => {
  $("#stats").textContent = "Ошибка: " + e.message;
});
