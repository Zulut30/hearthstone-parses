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
  firestone_battlegrounds_cards: "Firestone · BG существа по тавернам",
  firestone_battlegrounds_spells: "Firestone · BG заклинания по тавернам",
  firestone_battlegrounds_comps: "Firestone · BG компы",
  firestone_arena_cards_normal: "Firestone · Арена обычные карты",
  firestone_arena_cards_underground: "Firestone · Подпольная арена обычные карты",
  firestone_arena_legendaries_underground: "Firestone · Подпольная арена легендарки",
  firestone_arena_legendaries_normal: "Firestone · Арена легендарки",
  heartharena_tierlist: "HearthArena · Тир-лист карт",
  metastats_decks: "MetaStats · Архетипы и колоды",
  metastats_matchups: "MetaStats · Матрица матчапов",
  hearthstone_decks: "HS-Decks · Топ легенды (Std/Wild)",
  vicious_syndicate_radars: "vS · Радар карт (Связи)",
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
  
  if (id === "vicious_syndicate_radars" && payload.view) {
    initRadarGraph(payload.view);
  }
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
    if (v.time_period || v.mmr) {
      body += `<p class="muted">Период: ${escapeHtml(v.time_period || "?")} · MMR: ${escapeHtml(v.mmr || "?")}${v.last_update ? " · обновлено Firestone: " + escapeHtml(String(v.last_update)) : ""}</p>`;
    }
    body += renderTableFromObjects(
      v.heroes.map((h) => ({
        Герой: h.hero,
        "Среднее место": h.avg_placement ?? h.average_position ?? "",
        "Pick rate": h.pick_rate || "",
        Игры: h.games ?? h.data_points ?? "",
        "id / dbfId": `${h.hero_card_id || h.id || "?"} / ${h.dbfId ?? "?"}`,
      })),
      ["Герой", "Среднее место", "Pick rate", "Игры", "id / dbfId"]
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
  } else if (t === "heartharena_tierlist" && v.classes) {
    body = `<div class="block"><h3>Оценка карт HearthArena (${v.total_cards} карт)</h3>`;
    const validClasses = v.classes.filter((c) => c.cards && c.cards.length);
    if (validClasses.length > 1) {
      body += `<p class="muted">Быстрый переход: `;
      body += validClasses
        .map((c) => `<a href="#class-${c.class_id}">${escapeHtml(c.class_name)}</a>`)
        .join(" · ");
      body += `</p>`;
    }
    for (const cls of validClasses) {
      body += `<div id="class-${cls.class_id}" class="strategy" style="scroll-margin-top: 20px;">`;
      body += `<h4>${escapeHtml(cls.class_name)} (${cls.total_cards} шт.)</h4>`;
      body += renderTableFromObjects(
        cls.cards.map((c) => ({
          Карта: c.name,
          "Оценка (Score)": c.score ?? "",
          Тир: c.tier_name || "",
          Мана: c.cost ?? "",
          Тип: c.type ?? "",
          Редкость: c.rarity ?? "",
          "id / dbfId": `${c.card_id || c.id || "?"} / ${c.dbfId ?? "?"}`,
        })),
        ["Карта", "Оценка (Score)", "Тир", "Мана", "Тип", "Редкость", "id / dbfId"]
      );
      body += `</div>`;
    }
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
  } else if (t === "bg_card_stats" && v.tiers) {
    body = `<div class="block"><h3>Статистика по тавернам</h3>`;
    if (v.total_data_points || v.last_update_date) {
      body += `<p class="muted">Всего игр: ${escapeHtml(v.total_data_points || "?")} · Обновлено Firestone: ${escapeHtml(String(v.last_update_date || "?"))}</p>`;
    }
    const validTiers = Object.keys(v.tiers).filter((t) => v.tiers[t] && v.tiers[t].length);
    if (validTiers.length > 1) {
      body += `<p class="muted">Быстрый переход: `;
      body += validTiers
        .map((t) => {
          const name = t === "other" ? "Разное" : `Т${t}`;
          return `<a href="#tier-${t}">${name}</a>`;
        })
        .join(" · ");
      body += `</p>`;
    }
    for (const tierName of validTiers) {
      const tierCards = v.tiers[tierName];
      const tierTitle = tierName === "other" ? "Разное (other)" : `Уровень таверны ${tierName}`;
      body += `<div id="tier-${tierName}" class="strategy" style="scroll-margin-top: 20px;">`;
      body += `<h4>${escapeHtml(tierTitle)} (${tierCards.length} шт.)</h4>`;
      body += renderTableFromObjects(
        tierCards.map((c) => {
          let imp = "";
          if (c.impact !== null && c.impact !== undefined) {
            const num = Number(c.impact);
            if (!isNaN(num)) {
              imp = num > 0 ? `+${num.toFixed(3)}` : num.toFixed(3);
            }
          }
          return {
            Карта: c.name,
            "Игр сыграно": c.total_played ?? "",
            "Среднее место": c.average_placement ?? "",
            "Вне колоды": c.average_placement_other ?? "",
            "Влияние (Impact)": imp,
            "id / dbfId": `${c.card_id || c.id || "?"} / ${c.dbfId ?? "?"}`,
          };
        }),
        ["Карта", "Игр сыграно", "Среднее место", "Вне колоды", "Влияние (Impact)", "id / dbfId"]
      );
      body += `</div>`;
    }
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
  } else if (t === "metastats_decks" && v.decks) {
    body = `<div class="block"><h3>Архетипы и колоды MetaStats (${v.total_decks} колод)</h3>`;
    const classes = [...new Set(v.decks.map(d => d.class))];
    body += `<p class="muted">Фильтр по классам: `;
    body += classes.map(cls => `<a href="#class-meta-${cls}">${escapeHtml(cls)}</a>`).join(" · ");
    body += `</p>`;
    
    const decksByClass = {};
    for (const d of v.decks) {
      if (!decksByClass[d.class]) decksByClass[d.class] = [];
      decksByClass[d.class].push(d);
    }
    
    for (const cls of classes) {
      const clsDecks = decksByClass[cls];
      body += `<div id="class-meta-${cls}" style="scroll-margin-top: 20px; margin-bottom: 2rem;">`;
      body += `<h3 style="border-bottom: 2px solid var(--border); padding-bottom: 0.5rem; color: var(--accent);">${escapeHtml(cls)}</h3>`;
      
      const decksByArch = {};
      for (const d of clsDecks) {
        if (!decksByArch[d.archetype_name]) decksByArch[d.archetype_name] = [];
        decksByArch[d.archetype_name].push(d);
      }
      
      for (const archName in decksByArch) {
        const archDecks = decksByArch[archName];
        body += `<div class="strategy" style="margin-bottom: 1.5rem;">`;
        body += `<h4 style="font-size: 1.15rem; color: #ffbc42; margin-bottom: 0.75rem;">${escapeHtml(archName)}</h4>`;
        
        for (const d of archDecks) {
          body += `<div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 6px; margin-bottom: 0.75rem; border-left: 3px solid var(--accent);">`;
          body += `<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem;">`;
          body += `<span style="font-weight: bold; font-size: 0.9rem;">Версия #${escapeHtml(d.deck_id)}</span>`;
          body += `<span class="muted" style="font-size: 0.85rem;">Игр: <strong>${d.games || "?"}</strong> · Winrate: <strong style="color: var(--ok);">${escapeHtml(d.win_rate || "?")}</strong></span>`;
          body += `</div>`;
          
          if (d.deck_code) {
            body += `<div style="margin-bottom: 0.5rem; display: flex; gap: 0.5rem; align-items: center;">`;
            body += `<input type="text" readonly value="${escapeHtml(d.deck_code)}" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 0.2rem 0.4rem; font-size: 0.75rem; border-radius: 4px; flex-grow: 1; font-family: monospace;" onclick="this.select();" />`;
            body += `<button onclick="navigator.clipboard.writeText('${escapeHtml(d.deck_code)}'); alert('Код скопирован в буфер!');" class="source-btn" style="padding: 0.2rem 0.5rem; font-size: 0.75rem; background: var(--panel);">Скопировать</button>`;
            body += `</div>`;
          }
          
          if (d.cards && d.cards.length) {
            body += `<details style="font-size: 0.85rem;"><summary class="muted" style="cursor: pointer; user-select: none;">Показать карты (${d.cards.reduce((sum, c) => sum + (c.count || 1), 0)} шт.)</summary>`;
            body += `<div style="margin-top: 0.5rem; padding-left: 0.5rem;">`;
            body += `<ul class="cards-list" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.25rem 1rem;">`;
            body += d.cards.map(c => `<li><strong>${c.count || 1}×</strong> ${escapeHtml(c.name)} <code style="font-size: 0.7rem; color: var(--muted);">${c.id || ""}</code></li>`).join("");
            body += `</ul></div></details>`;
          }
          body += `</div>`;
        }
        body += `</div>`;
      }
      body += `</div>`;
    }
    body += "</div>";
  } else if (t === "metastats_matchups" && v.matchups) {
    body = `<div class="block"><h3>Матрица матчапов MetaStats (${v.matchups.length} ячеек)</h3>`;
    body += renderTableFromObjects(
      v.matchups.map((m) => ({
        Архетип: m.archetype,
        Против: m.vs,
        Игр: m.games ?? "",
        "Винрейт (WR)": m.winrate || "",
        "Оппонент WR": m.vs_winrate || "",
      })),
      ["Архетип", "Против", "Игр", "Винрейт (WR)", "Оппонент WR"]
    );
    body += "</div>";
  } else if (t === "hearthstone_decks" && v.decks) {
    body = `<div class="block"><h3>Топ легенды Standard и Wild (${v.total_decks} колод)</h3>`;
    body += `<p class="muted">Фильтр по форматам: <a href="#format-Standard">Standard (${v.standard_count || 0})</a> · <a href="#format-Wild">Wild (${v.wild_count || 0})</a></p>`;
    
    const formats = ["Standard", "Wild"];
    for (const fmt of formats) {
      const fmtDecks = v.decks.filter(d => d.format === fmt);
      if (!fmtDecks.length) continue;
      
      body += `<div id="format-${fmt}" style="scroll-margin-top: 20px; margin-bottom: 2rem;">`;
      body += `<h3 style="border-bottom: 2px solid var(--border); padding-bottom: 0.5rem; color: #ff9f1c;">${escapeHtml(fmt)} Decks</h3>`;
      
      let html = "<table class='simple'><thead><tr>";
      html += "<th>Архетип</th><th>Ранг</th><th>Игрок</th><th>Счет</th><th>Код колоды</th><th>Дата</th><th>Ссылка</th>";
      html += "</tr></thead><tbody>";
      
      for (const d of fmtDecks) {
        html += "<tr>";
        html += `<td><strong>${escapeHtml(d.archetype || d.title)}</strong></td>`;
        html += `<td>${escapeHtml(d.rank || "")}</td>`;
        html += `<td>${escapeHtml(d.player || "")}</td>`;
        html += `<td>${escapeHtml(d.score || "")}</td>`;
        
        if (d.deck_code) {
          html += `<td>
            <div style="display: flex; gap: 4px; align-items: center;">
              <input type="text" readonly value="${escapeHtml(d.deck_code)}" style="background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 0.15rem 0.3rem; font-size: 0.72rem; border-radius: 4px; width: 140px; font-family: monospace;" onclick="this.select();" />
              <button onclick="navigator.clipboard.writeText('${escapeHtml(d.deck_code)}'); alert('Код колоды скопирован!');" class="source-btn" style="padding: 0.15rem 0.3rem; font-size: 0.7rem; background: var(--panel);">Копировать</button>
            </div>
          </td>`;
        } else {
          html += "<td><span class='muted'>Загрузка / Нет кода</span></td>";
        }
        
        html += `<td>${escapeHtml(d.date || "")}</td>`;
        html += `<td><a href="${escapeHtml(d.url)}" target="_blank" class="source-btn" style="padding: 0.15rem 0.4rem; font-size: 0.72rem; text-decoration: none; color: inherit; display: inline-block;">Открыть</a></td>`;
        html += "</tr>";
      }
      html += "</tbody></table>";
      body += html;
      body += `</div>`;
    }
    body += "</div>";
  } else if (t === "vicious_syndicate_radars" && v.radars) {
    const classItems = v.classes_summary || Array.from(new Set(v.radars.map(r => r.class))).map(cls => ({
      class: cls,
      has_archetypes: v.radars.some(r => r.class === cls && r.archetype !== null)
    }));
    body = `<div class="block">
      <h3>Интерактивный радар карт Vicious Syndicate (Выпуск #${escapeHtml(v.issue || "?")})</h3>
      <p class="muted" style="margin-bottom: 1.5rem;">Граф показывает связи между картами в колодах. Чем больше круг, тем популярнее карта. Чем толще линия, тем сильнее синергия.</p>
      
      <!-- Class Selector Tabs -->
      <h5 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">Выберите класс:</h5>
      <div class="tabs-container" style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 1rem;">
        ${classItems.map((item, i) => {
          const cls = item.class;
          const hasArch = item.has_archetypes;
          return `
            <button class="source-btn class-tab-btn ${i === 0 ? "active" : ""}" data-class="${escapeHtml(cls)}" style="font-weight: bold; border-radius: 6px; padding: 0.4rem 0.8rem; border: 1px solid var(--border); display: flex; align-items: center; gap: 6px;">
              ${escapeHtml(cls)}
              ${hasArch ? `<span style="background: #2ec4b6; color: #fff; font-size: 0.65rem; padding: 0.1rem 0.35rem; border-radius: 10px; font-weight: normal;">+ Архетипы</span>` : ""}
            </button>
          `;
        }).join("")}
      </div>

      <!-- Archetype Selector Tabs -->
      <h5 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">Выберите архетип / радар:</h5>
      <div id="radar-archetypes-container" style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 1.5rem; background: var(--panel); padding: 0.4rem; border-radius: 8px; border: 1px dashed var(--border);">
        <!-- Populated dynamically -->
      </div>

      <!-- Selected Radar Deck Code Block -->
      <div id="radar-deck-code-section" class="block" style="background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem; display: none;">
        <h4 style="margin-top: 0; color: #ff9f1c; font-size: 1.1rem; margin-bottom: 0.5rem;">Код колоды для этого радара</h4>
        <div style="display: flex; gap: 8px; align-items: center;">
          <input type="text" id="radar-deck-code-input" readonly style="background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 0.5rem 0.8rem; font-size: 0.85rem; border-radius: 6px; width: 100%; font-family: monospace;" onclick="this.select();" />
          <button id="radar-deck-code-copy-btn" class="source-btn" style="padding: 0.5rem 1rem; border-radius: 6px; font-weight: bold; background: #2ec4b6; color: white;">Копировать</button>
        </div>
      </div>

      <!-- Graph Container -->
      <div style="position: relative; margin: 1.5rem 0; background: #0f0f11; border: 1px solid var(--border); border-radius: 12px; padding: 1rem; overflow: hidden;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 10px;">
          <div style="display: flex; gap: 8px; align-items: center;">
            <input type="text" id="radar-search" placeholder="Поиск карты..." style="background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.9rem; width: 220px;" />
            <button id="radar-reset-btn" class="source-btn" style="padding: 0.4rem 0.8rem; border-radius: 6px;">Сброс</button>
          </div>
          <div id="radar-hover-info" class="muted" style="font-size: 0.85rem; min-height: 1.2rem;">Наведите на карту для деталей</div>
        </div>
        
        <canvas id="radar-canvas" width="750" height="750" style="background: #111113; border-radius: 8px; width: 100%; max-width: 750px; aspect-ratio: 1; display: block; margin: 0 auto; cursor: grab;"></canvas>
      </div>

      <!-- Selected Card Details & Table -->
      <div style="display: grid; grid-template-columns: 1fr; gap: 1.5rem; margin-top: 1.5rem;">
        <div class="block" style="background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem;">
          <h4 id="selected-card-title" style="margin-top: 0; color: #ff9f1c; font-size: 1.1rem;">Выберите карту на графе</h4>
          <div id="selected-card-details">
            <p class="muted">Нажмите на любой узел на графе, чтобы увидеть его сильные связи с другими картами.</p>
          </div>
        </div>
        
        <div class="block" style="background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem;">
          <h4 style="margin-top: 0; margin-bottom: 1rem; font-size: 1.1rem;">Список карт в радаре</h4>
          <div style="max-height: 350px; overflow-y: auto;">
            <table class="simple" id="radar-nodes-table">
              <thead>
                <tr>
                  <th>Название карты</th>
                  <th>Популярность (Радиус)</th>
                  <th>Связей</th>
                </tr>
              </thead>
              <tbody>
                <!-- Populated dynamically -->
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;
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

let radarAnimationId = null;

function initRadarGraph(data) {
  if (radarAnimationId) {
    cancelAnimationFrame(radarAnimationId);
    radarAnimationId = null;
  }

  const canvas = document.getElementById("radar-canvas");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const searchInput = document.getElementById("radar-search");
  const resetBtn = document.getElementById("radar-reset-btn");
  const hoverInfo = document.getElementById("radar-hover-info");
  const selectedCardTitle = document.getElementById("selected-card-title");
  const selectedCardDetails = document.getElementById("selected-card-details");
  const nodesTableBody = document.querySelector("#radar-nodes-table tbody");
  const archetypesContainer = document.getElementById("radar-archetypes-container");

  let currentClass = data.radars[0] ? data.radars[0].class : null;
  let currentArchetype = null;
  let nodes = [];
  let edges = [];
  let draggedNode = null;
  let hoveredNode = null;
  let selectedNode = null;
  let searchText = "";

  function rebuildArchetypeTabs(clsName) {
    if (!archetypesContainer) return;
    archetypesContainer.innerHTML = "";

    const classRadars = data.radars.filter(r => r.class === clsName);
    
    // Sort radars so that the main class radar (archetype === null) is first
    classRadars.sort((a, b) => {
      if (a.archetype === null) return -1;
      if (b.archetype === null) return 1;
      return a.archetype.localeCompare(b.archetype);
    });

    classRadars.forEach((r, i) => {
      const btn = document.createElement("button");
      btn.className = `source-btn arch-tab-btn ${i === 0 ? "active" : ""}`;
      btn.style.fontSize = "0.8rem";
      btn.style.padding = "0.3rem 0.6rem";
      btn.style.borderRadius = "4px";
      btn.style.border = "1px solid var(--border)";
      btn.textContent = r.archetype ? r.archetype : "Общий (Класс)";
      
      btn.addEventListener("click", () => {
        document.querySelectorAll(".arch-tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentArchetype = r.archetype;
        loadClassRadar(currentClass, currentArchetype);
      });

      archetypesContainer.appendChild(btn);
    });
  }

  document.querySelectorAll(".class-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".class-tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentClass = btn.dataset.class;
      currentArchetype = null;
      rebuildArchetypeTabs(currentClass);
      loadClassRadar(currentClass, null);
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      searchText = e.target.value.toLowerCase().trim();
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      searchText = "";
      selectedNode = null;
      hoveredNode = null;
      updateSelectedCardView();
      loadClassRadar(currentClass, currentArchetype);
    });
  }

  function loadClassRadar(clsName, archetype = null) {
    const radar = data.radars.find(r => r.class === clsName && r.archetype === archetype);
    if (!radar) return;

    selectedNode = null;
    hoveredNode = null;
    updateSelectedCardView();

    // Display deck code if available
    const deckCodeSec = document.getElementById("radar-deck-code-section");
    const deckCodeInp = document.getElementById("radar-deck-code-input");
    const deckCodeBtn = document.getElementById("radar-deck-code-copy-btn");
    
    if (deckCodeSec && deckCodeInp && deckCodeBtn) {
      if (radar.deck_code) {
        deckCodeInp.value = radar.deck_code;
        deckCodeSec.style.display = "block";
        deckCodeBtn.onclick = () => {
          navigator.clipboard.writeText(radar.deck_code);
          alert("Код колоды скопирован!");
        };
      } else {
        deckCodeSec.style.display = "none";
      }
    }

    nodes = radar.nodes.map(n => {
      const angle = Math.random() * Math.PI * 2;
      const radius = 150 + Math.random() * 100;
      return {
        ...n,
        x: 375 + Math.cos(angle) * radius,
        y: 375 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        linksCount: radar.edges.filter(e => e.source === n.name || e.target === n.name).length
      };
    });

    edges = radar.edges.map(e => ({ ...e }));
    updateNodesTable();
  }

  function updateNodesTable() {
    if (!nodesTableBody) return;
    nodesTableBody.innerHTML = "";
    
    const sortedNodes = [...nodes].sort((a, b) => b.radius - a.radius);
    
    for (const n of sortedNodes) {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.innerHTML = `
        <td><strong>${escapeHtml(n.name)}</strong></td>
        <td>${n.radius.toFixed(1)}</td>
        <td>${n.linksCount}</td>
      `;
      tr.addEventListener("click", () => {
        const matchingNode = nodes.find(node => node.name === n.name);
        if (matchingNode) {
          selectedNode = matchingNode;
          updateSelectedCardView();
        }
      });
      nodesTableBody.appendChild(tr);
    }
  }

  function updateSelectedCardView() {
    if (!selectedCardTitle || !selectedCardDetails) return;
    
    if (!selectedNode) {
      selectedCardTitle.textContent = "Выберите карту на графе";
      selectedCardDetails.innerHTML = `<p class="muted">Нажмите на любой узел на графе, чтобы увидеть его сильные связи с другими картами.</p>`;
      return;
    }

    selectedCardTitle.textContent = selectedNode.name;
    
    const conn = edges
      .filter(e => e.source === selectedNode.name || e.target === selectedNode.name)
      .map(e => {
        const other = e.source === selectedNode.name ? e.target : e.source;
        return { name: other, weight: e.weight };
      })
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 10);

    let html = `<p><strong>Популярность (радиус):</strong> ${selectedNode.radius.toFixed(1)}</p>`;
    html += `<h5 style="margin: 0.8rem 0 0.4rem 0; border-bottom: 1px solid var(--border); padding-bottom: 0.2rem;">Топ-10 сильнейших связей:</h5>`;
    if (conn.length === 0) {
      html += `<p class="muted">Связи не найдены.</p>`;
    } else {
      html += `<ul style="margin: 0; padding-left: 1.2rem; line-height: 1.5; font-size: 0.9rem;">`;
      for (const c of conn) {
        html += `<li><strong>${escapeHtml(c.name)}</strong> (сила связи: ${(c.weight * 100).toFixed(0)}%)</li>`;
      }
      html += `</ul>`;
    }

    selectedCardDetails.innerHTML = html;
  }

  function getMousePos(evt) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (evt.clientX - rect.left) * (750 / rect.width),
      y: (evt.clientY - rect.top) * (750 / rect.height)
    };
  }

  canvas.addEventListener("mousedown", (e) => {
    const pos = getMousePos(e);
    let clicked = null;
    for (const n of nodes) {
      const dx = n.x - pos.x;
      const dy = n.y - pos.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= n.radius + 5) {
        clicked = n;
        break;
      }
    }

    if (clicked) {
      draggedNode = clicked;
      selectedNode = clicked;
      updateSelectedCardView();
      canvas.style.cursor = "grabbing";
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    const pos = getMousePos(e);
    
    if (draggedNode) {
      draggedNode.x = pos.x;
      draggedNode.y = pos.y;
      draggedNode.vx = 0;
      draggedNode.vy = 0;
    } else {
      let found = null;
      for (const n of nodes) {
        const dx = n.x - pos.x;
        const dy = n.y - pos.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist <= n.radius + 5) {
          found = n;
          break;
        }
      }

      hoveredNode = found;
      if (found) {
        canvas.style.cursor = "pointer";
        if (hoverInfo) {
          hoverInfo.innerHTML = `Карта: <strong>${escapeHtml(found.name)}</strong> · Популярность: ${found.radius.toFixed(1)} · Связей: ${found.linksCount}`;
        }
      } else {
        canvas.style.cursor = "grab";
        if (hoverInfo) {
          hoverInfo.textContent = "Наведите на карту для деталей";
        }
      }
    }
  });

  window.addEventListener("mouseup", () => {
    if (draggedNode) {
      draggedNode = null;
      canvas.style.cursor = "grab";
    }
  });

  canvas.addEventListener("touchstart", (e) => {
    if (e.touches.length > 0) {
      const touch = e.touches[0];
      const mouseEvent = new MouseEvent("mousedown", {
        clientX: touch.clientX,
        clientY: touch.clientY
      });
      canvas.dispatchEvent(mouseEvent);
    }
  });

  canvas.addEventListener("touchmove", (e) => {
    if (e.touches.length > 0) {
      const touch = e.touches[0];
      const mouseEvent = new MouseEvent("mousemove", {
        clientX: touch.clientX,
        clientY: touch.clientY
      });
      canvas.dispatchEvent(mouseEvent);
    }
  });

  canvas.addEventListener("touchend", () => {
    const mouseEvent = new MouseEvent("mouseup", {});
    window.dispatchEvent(mouseEvent);
  });

  function tick() {
    const centerX = 375;
    const centerY = 375;
    
    for (let i = 0; i < nodes.length; i++) {
      const n1 = nodes[i];
      const cdx = centerX - n1.x;
      const cdy = centerY - n1.y;
      const cdist = Math.sqrt(cdx * cdx + cdy * cdy) || 1;
      n1.vx += (cdx / cdist) * 0.15;
      n1.vy += (cdy / cdist) * 0.15;

      for (let j = i + 1; j < nodes.length; j++) {
        const n2 = nodes[j];
        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const minDist = n1.radius + n2.radius + 35;
        if (dist < minDist) {
          const force = (minDist - dist) * 0.4;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          n1.vx -= fx;
          n1.vy -= fy;
          n2.vx += fx;
          n2.vy += fy;
        }
      }
    }

    for (const e of edges) {
      const sourceNode = nodes.find(n => n.name === e.source);
      const targetNode = nodes.find(n => n.name === e.target);
      if (sourceNode && targetNode) {
        const dx = targetNode.x - sourceNode.x;
        const dy = targetNode.y - sourceNode.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        
        if (e.weight > 0.1) {
          const desiredLen = e.length || 220;
          const k = 0.015 * e.weight;
          const force = (dist - desiredLen) * k;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          sourceNode.vx += fx;
          sourceNode.vy += fy;
          targetNode.vx -= fx;
          targetNode.vy -= fy;
        }
      }
    }

    for (const n of nodes) {
      if (n === draggedNode) continue;

      n.vx *= 0.85;
      n.vy *= 0.85;

      n.x += n.vx;
      n.y += n.vy;

      const margin = n.radius + 10;
      if (n.x < margin) { n.x = margin; n.vx = -n.vx * 0.5; }
      if (n.x > 750 - margin) { n.x = 750 - margin; n.vx = -n.vx * 0.5; }
      if (n.y < margin) { n.y = margin; n.vy = -n.vy * 0.5; }
      if (n.y > 750 - margin) { n.y = 750 - margin; n.vy = -n.vy * 0.5; }
    }

    ctx.clearRect(0, 0, 750, 750);

    for (const e of edges) {
      const sourceNode = nodes.find(n => n.name === e.source);
      const targetNode = nodes.find(n => n.name === e.target);
      if (!sourceNode || !targetNode) continue;

      let opacity = e.weight * 0.5;
      let isHighlighted = false;

      if (searchText) {
        const sMatch = sourceNode.name.toLowerCase().includes(searchText);
        const tMatch = targetNode.name.toLowerCase().includes(searchText);
        if (sMatch && tMatch) {
          isHighlighted = true;
          opacity = Math.min(1.0, e.weight * 1.5);
        } else {
          opacity = 0.02;
        }
      } else if (selectedNode) {
        if (sourceNode.name === selectedNode.name || targetNode.name === selectedNode.name) {
          isHighlighted = true;
          opacity = Math.min(0.9, e.weight * 1.8);
        } else {
          opacity = 0.02;
        }
      } else {
        if (e.weight < 0.15) continue;
      }

      ctx.beginPath();
      ctx.moveTo(sourceNode.x, sourceNode.y);
      ctx.lineTo(targetNode.x, targetNode.y);
      ctx.lineWidth = isHighlighted ? 2.5 : 1.0;
      ctx.strokeStyle = isHighlighted ? `rgba(255, 159, 28, ${opacity})` : `rgba(255, 255, 255, ${opacity})`;
      ctx.stroke();
    }

    for (const n of nodes) {
      let isHighlighted = true;
      let drawBorder = false;

      if (searchText) {
        isHighlighted = n.name.toLowerCase().includes(searchText);
      } else if (selectedNode) {
        isHighlighted = (n.name === selectedNode.name || edges.some(e => 
          (e.source === selectedNode.name && e.target === n.name) || 
          (e.target === selectedNode.name && e.source === n.name)
        ));
        drawBorder = (n.name === selectedNode.name);
      }

      const baseAlpha = isHighlighted ? 0.9 : 0.2;
      const strokeAlpha = isHighlighted ? 1.0 : 0.2;

      let fillStyle = n.fill || "rgba(0,102,0,0.75)";
      let strokeStyle = n.stroke || "rgba(221,221,221,1.00)";
      
      fillStyle = fillStyle.replace(/[\d.]+\)$/, `${baseAlpha})`);
      strokeStyle = strokeStyle.replace(/[\d.]+\)$/, `${strokeAlpha})`);

      if (drawBorder) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius + 6, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255, 159, 28, 0.3)";
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      ctx.fillStyle = fillStyle;
      ctx.fill();
      ctx.lineWidth = n.strokewidth || 2.0;
      ctx.strokeStyle = drawBorder ? "#ff9f1c" : strokeStyle;
      ctx.stroke();

      ctx.font = `bold ${n.radius < 10 ? 10 : 12}px sans-serif`;
      ctx.fillStyle = isHighlighted ? "rgba(255,255,255,1.00)" : "rgba(255,255,255,0.25)";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      
      ctx.shadowColor = "rgba(0, 0, 0, 0.9)";
      ctx.shadowBlur = 4;
      ctx.fillText(n.name, n.x, n.y);
      ctx.shadowBlur = 0;
    }

    radarAnimationId = requestAnimationFrame(tick);
  }

  rebuildArchetypeTabs(currentClass);
  loadClassRadar(currentClass, null);
  tick();
}

