const $ = (sel) => document.querySelector(sel);

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function list(items) {
  if (!items || !items.length) return "<p class='muted'>Нет данных.</p>";
  return `<ul class="tech-bullets">${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

function renderApiTable(apis) {
  if (!apis || !apis.length) return "<p class='muted'>API не описаны.</p>";
  return `
    <div class="tech-api-table-wrap">
      <table class="simple tech-api-table">
        <thead>
          <tr>
            <th>Endpoint / route</th>
            <th>Тип</th>
            <th>Для чего используем</th>
          </tr>
        </thead>
        <tbody>
          ${apis
            .map(
              (api) => `
                <tr>
                  <td><strong>${esc(api.name || "")}</strong><br><code>${esc(api.url_pattern || "")}</code></td>
                  <td>${esc(api.type || "")}</td>
                  <td>${esc(api.used_for || "")}</td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>`;
}

function renderSite(site) {
  return `
    <article id="site-${esc(site.key)}" class="tech-site-card block">
      <div class="tech-site-heading">
        <div>
          <h3>${esc(site.name)}</h3>
          <p class="muted">${esc(site.role)}</p>
        </div>
        <a href="${esc(site.homepage)}" target="_blank" rel="noopener">Открыть сайт</a>
      </div>

      <div class="tech-grid">
        <section>
          <h4>Frontend</h4>
          ${list(site.frontend)}
        </section>
        <section>
          <h4>Backend / данные</h4>
          ${list(site.backend)}
        </section>
        <section>
          <h4>Хостинг / сеть</h4>
          ${list(site.hosting)}
        </section>
        <section>
          <h4>Авторизация</h4>
          <p>${esc(site.auth)}</p>
        </section>
      </div>

      <h4>API и маршруты, которые мы используем</h4>
      ${renderApiTable(site.apis)}

      <div class="tech-grid tech-grid-bottom">
        <section>
          <h4>Parser strategy</h4>
          ${list(site.parser_strategy)}
        </section>
        <section>
          <h4>Риски стабильности</h4>
          ${list(site.risks)}
        </section>
        <section>
          <h4>Доп. заметки</h4>
          ${list(site.notes)}
        </section>
      </div>
    </article>
  `;
}

function renderComponents(components) {
  if (!components || !components.length) return "<p class='muted'>Нет данных.</p>";
  return `
    <div class="tech-table-wrap tech-components-wrap">
      <table class="tech-table">
        <thead>
          <tr>
            <th>Компонент</th>
            <th>Назначение</th>
            <th>Слой</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          ${components
            .map(
              (item) => `
                <tr>
                  <td>${item.link ? `<a href="${esc(item.link)}" target="_blank" rel="noopener">${esc(item.name)}</a>` : esc(item.name)}
                    ${item.notes ? `<br><span class="muted">${esc(item.notes)}</span>` : ""}
                  </td>
                  <td>${esc(item.role)}</td>
                  <td>${esc(item.layer)}</td>
                  <td><span class="tech-status tech-status--${esc(item.status)}">${esc(item.status)}</span></td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>`;
}

async function loadTechnologiesPage() {
  const res = await fetch("/system/technologies");
  if (!res.ok) throw new Error(`/system/technologies -> ${res.status}`);
  const data = await res.json();
  $("#tech-page-stats").innerHTML =
    `Сайтов: <strong>${esc(data.site_count || 0)}</strong> · компонентов parser stack: <strong>${esc(data.count || 0)}</strong> · обновлено: ${esc(data.updated || "?")}`;

  const sites = data.sites || [];
  $("#tech-site-nav").innerHTML = sites
    .map(
      (site) => `
        <a class="source-btn tech-nav-link" href="#site-${esc(site.key)}">
          <span class="id">${esc(site.name)}</span>
          <span class="meta">${esc(site.key)}</span>
        </a>
      `
    )
    .join("");
  $("#tech-sites").innerHTML = sites.map(renderSite).join("");
  $("#tech-components").innerHTML = renderComponents(data.technologies || []);
}

loadTechnologiesPage().catch((err) => {
  $("#tech-page-stats").innerHTML = `<span class="err-text">Ошибка: ${esc(err.message)}</span>`;
});
