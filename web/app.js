const $ = (sel) => document.querySelector(sel);

const LABELS = {
  hsguru_meta_standard_legend: "Мета Standard · Legend",
  hsguru_meta_standard_diamond_4to1: "Мета Standard · Diamond",
  hsguru_meta_wild_legend: "Мета Wild · Legend",
  hsguru_meta_wild_diamond_4to1: "Мета Wild · Diamond",
  hsguru_matchups_legend: "Матчапы · Legend",
  hsguru_matchups_diamond_4to1: "Матчапы · Diamond",
  hsguru_streamer_decks_legend_1000: "Колоды стримеров",
  hsreplay_arena: "Арена · тир классов (2-class)",
  hsreplay_arena_cards_advanced: "Арена · тир карт",
  hsreplay_arena_legendaries: "Арена · легендарки",
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
    `<a href="/docs">API docs</a>`;

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

function renderCards(cards) {
  if (!cards || !cards.length) {
    return "<p class='lines'>Карты не декодированы (нет deck code или ошибка).</p>";
  }
  return `<ul class="cards-list">${cards
    .map(
      (c) =>
        `<li><strong>${c.count}×</strong> ${escapeHtml(c.name)} — ` +
        `<code>id: ${c.id || "?"}</code>, <code>dbfId: ${c.dbfId ?? "?"}</code>, ` +
        `${c.cost != null ? c.cost + " мана" : ""} ${c.type || ""}</li>`
    )
    .join("")}</ul>`;
}

function renderDetail(p) {
  if (!p.ok) {
    return `<h2>Ошибка</h2><p>${escapeHtml(p.message || "Нет данных")}</p>`;
  }
  const v = p.view;
  let body = "";

  if (v.kind === "meta") {
    body = `<div class="block"><h3>Стратегии / архетипы (${v.total})</h3>`;
    for (const s of v.strategies || []) {
      body += `<div class="strategy">
        <h4>Стратегия: ${escapeHtml(s.strategy || "?")}</h4>
        <p>Winrate: <strong>${escapeHtml(String(s.winrate || "?"))}</strong> · 
        Popularity: ${escapeHtml(String(s.popularity || "?"))}</p>
      </div>`;
    }
    body += "</div>";
  } else if (v.kind === "streamer_decks") {
    body = `<div class="block"><h3>Колоды стримеров</h3>`;
    for (const d of v.decks || []) {
      body += `<div class="strategy">
        <h4>Стратегия: ${escapeHtml(d.strategy || "?")}</h4>
        <p>Стример: ${escapeHtml(d.streamer || "?")} · ${escapeHtml(d.format || "")} · 
        ${escapeHtml(d.record || "")}</p>
        ${d.deck_code ? `<p><code>${escapeHtml(d.deck_code.slice(0, 48))}…</code></p>` : ""}
        <p><em>Карты внутри (HearthstoneJSON):</em></p>
        ${renderCards(d.cards)}
      </div>`;
    }
    body += "</div>";
  } else if (v.kind === "matchups") {
    body = `<div class="block"><h3>Матчапы</h3>`;
    if (v.matrix_rows?.length) {
      body += renderTable(v.matrix_rows);
    }
    body += `<ul class="lines">${(v.highlights || [])
      .map((l) => `<li>${escapeHtml(l)}</li>`)
      .join("")}</ul></div>`;
  } else {
    body = `<div class="block"><h3>${escapeHtml(v.title || p.source_id)}</h3>`;
    if (v.class_matrix?.length) {
      body += "<p><strong>Матрица классов / винрейты:</strong></p>" + renderTable(v.class_matrix);
    }
    if (v.deck_links?.length) {
      body += "<p><strong>Ссылки на колоды:</strong></p><ul class='lines'>";
      for (const l of v.deck_links) {
        body += `<li><a href="${escapeHtml(l.href)}" target="_blank">${escapeHtml(l.text)}</a></li>`;
      }
      body += "</ul>";
    }
    body += `<p>${escapeHtml(v.note || "")}</p>`;
    body += `<ul class="lines">${(v.highlights || [])
      .slice(0, 35)
      .map((l) => `<li>${escapeHtml(l)}</li>`)
      .join("")}</ul></div>`;
  }

  return `
    <h2>${escapeHtml(LABELS[p.source_id] || p.source_id)}</h2>
    <p class="meta-line">
      ${escapeHtml(p.site)} · ${escapeHtml(p.category)} · 
      обновлено: ${escapeHtml(p.fetched_at || "?")} · backend: ${escapeHtml(p.backend || "?")}
      · <a href="${escapeHtml(p.url)}" target="_blank">источник</a>
    </p>
    ${body}
  `;
}

function renderTable(rows) {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]).filter((k) => !k.startsWith("column_") || rows[0][k]);
  const cols = keys.length ? keys : Object.keys(rows[0]).slice(0, 6);
  let html = "<table class='simple'><thead><tr>";
  for (const c of cols) html += `<th>${escapeHtml(c)}</th>`;
  html += "</tr></thead><tbody>";
  for (const row of rows.slice(0, 20)) {
    html += "<tr>";
    for (const c of cols) html += `<td>${escapeHtml(String(row[c] ?? ""))}</td>`;
    html += "</tr>";
  }
  html += "</tbody></table>";
  return html;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

loadOverview().catch((e) => {
  $("#stats").textContent = "Ошибка загрузки: " + e.message;
});
