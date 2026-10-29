const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function num(value) {
  return (Number(value) || 0).toLocaleString("pt-BR");
}

function duration(seconds) {
  const total = Math.round(Number(seconds) || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function shorten(text, max = 44) {
  const value = String(text || "");
  return value.length <= max ? value : `...${value.slice(-(max - 3))}`;
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  let payload = null;
  try {
    payload = await response.json();
  } catch (err) {
    payload = null;
  }
  if (!response.ok) {
    throw new Error((payload && payload.error) || `HTTP ${response.status}`);
  }
  return payload;
}

function showBanner(message) {
  const banner = $("#banner");
  if (!message) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function setStatus(state, text) {
  $("#meta-status").className = `chip signal ${state}`.trim();
  $("#meta-status").textContent = text;
}

function maxOf(items, key) {
  return items.reduce((acc, item) => Math.max(acc, Number(item[key]) || 0), 0);
}

function barRow(name, value, max, options = {}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  const cls = options.warn ? "fill warn" : options.alt ? "fill alt" : "fill";
  const suffix = options.suffix ? ` ${esc(options.suffix)}` : "";
  return `<div class="bar">
    <div class="bar-top"><span class="name">${esc(name)}</span><span class="num">${num(value)}${suffix}</span></div>
    <div class="track"><div class="${cls}" style="width:${pct}%"></div></div>
  </div>`;
}

function cardHtml(card) {
  const tone = card.tone || "";
  const size = card.small ? " small" : "";
  const hint = card.hint ? `<div class="hint">${esc(card.hint)}</div>` : "";
  return `<div class="card">
    <span class="label">${esc(card.label)}</span>
    <span class="value ${tone}${size}">${card.value}</span>
    ${hint}
  </div>`;
}

async function loadOverview() {
  const data = await api("/api/overview");
  const stats = data.stats;
  const classification = data.classification;

  $("#meta-schema").textContent = `schema v${data.catalog.schema_version ?? "?"}`;
  $("#meta-catalog").textContent = `catalogo: ${shorten(data.catalog.path)}`;
  $("#meta-catalog").title = data.catalog.path;
  $("#foot-catalog").textContent = data.catalog.path;

  const cards = [
    { label: "arquivos", value: num(stats.files) },
    { label: "faixas", value: num(stats.tracks) },
    { label: "ausentes", value: num(stats.missing), tone: stats.missing ? "is-warn" : "is-ok" },
    { label: "erros de scan", value: num(stats.errors), tone: stats.errors ? "is-fail" : "is-ok" },
    { label: "duracao total", value: duration(stats.total_duration), small: true },
    { label: "generos ativos", value: num(classification.genres_active) },
    { label: "classificadas", value: num(classification.classified), tone: "is-ok" },
    {
      label: "nao classificadas",
      value: num(classification.unclassified),
      tone: classification.unclassified ? "is-warn" : "is-ok",
    },
    { label: "fingerprints", value: num(data.fingerprints) },
    { label: "analisadas", value: num(data.analysis.files) },
    { label: "embeddings", value: num(data.embeddings.files) },
    { label: "propostas (L3)", value: num(data.embeddings.proposed) },
    { label: "lotes aplicados", value: num(data.apply.batches) },
  ];
  $("#overview-cards").innerHTML = cards.map(cardHtml).join("");

  const coverage = stats.coverage;
  const coverageMax = Math.max(1, maxOf(coverage, "base"));
  $("#overview-coverage").innerHTML = coverage.length
    ? coverage
        .map((row) => {
          const pct = row.base ? Math.round((row.filled / row.base) * 100) : 0;
          return barRow(`${row.label} · ${pct}%`, row.filled, coverageMax);
        })
        .join("")
    : `<div class="empty">sem faixas indexadas</div>`;

  const extensions = stats.by_extension;
  $("#overview-extensions").innerHTML = extensions.length
    ? extensions
        .map((row) => barRow(row.ext, row.total, maxOf(extensions, "total"), { alt: true }))
        .join("")
    : `<div class="empty">sem arquivos indexados</div>`;

  const genres = classification.distribution;
  $("#overview-genres").innerHTML = genres.length
    ? genres.map((row) => barRow(row.name, row.total, maxOf(genres, "total"))).join("")
    : `<div class="empty">nenhum genero classificado ainda</div>`;

  const dups = data.duplicates.groups;
  $("#overview-dups").innerHTML = dups.length
    ? dups.map((row) => barRow(row.kind, row.total, maxOf(dups, "total"), { warn: true })).join("")
    : `<div class="empty">nenhuma duplicata detectada</div>`;

  const versionTotal = data.versions.counts.reduce((acc, row) => acc + row.total, 0);
  $("#overview-extra").innerHTML = `
    <div class="kv-row"><span>versao da taxonomia</span><span>${esc(data.catalog.taxonomy_version || "-")}</span></div>
    <div class="kv-row"><span>grupos de duplicatas</span><span>${num(data.duplicates.total)}</span></div>
    <div class="kv-row"><span>versoes classificadas</span><span>${num(versionTotal)}</span></div>
  `;
}

async function loadLibrary() {
  const query = $("#library-query").value.trim();
  const data = await api(`/api/tracks?limit=200&q=${encodeURIComponent(query)}`);
  const rows = data.tracks;

  $("#library-count").textContent = rows.length
    ? `${rows.length} faixa(s) exibida(s)${query ? ` para "${query}"` : ""}`
    : "nenhuma faixa encontrada";

  $("#library-table tbody").innerHTML = rows
    .map(
      (track) => `<tr>
        <td>${esc(track.title || "-")}</td>
        <td>${esc(track.artist || "-")}</td>
        <td>${esc(track.album || "-")}</td>
        <td>${esc(track.genre || "-")}</td>
        <td>${esc(track.bpm || (track.bpm_analysis ? Number(track.bpm_analysis).toFixed(1) : "-"))}</td>
        <td>${esc(track.key || track.key_camelot || "-")}</td>
        <td>${esc(track.ext || "-")}</td>
        <td class="num">${track.duration ? duration(track.duration) : "-"}</td>
        <td class="path">${esc(track.path)}${track.is_missing ? ' <span class="badge warn">ausente</span>' : ""}</td>
      </tr>`
    )
    .join("");
}

async function loadDuplicates() {
  const data = await api("/api/duplicates?limit=50");
  const kinds = data.by_kind;

  $("#duplicates-kinds").innerHTML = kinds.length
    ? kinds.map((row) => `<span class="pill">${esc(row.kind)} <b>${num(row.total)}</b></span>`).join("")
    : `<span class="pill">nenhum grupo <b>0</b></span>`;

  const groups = data.groups;
  $("#duplicates-groups").innerHTML = groups.length
    ? groups
        .map(
          (group) => `<div class="group">
            <div class="group-head">
              <span class="kind">${esc(group.kind)}</span>
              <span class="key">${esc(group.key)}</span>
              <span class="badge muted">${group.members.length} membros</span>
            </div>
            ${group.members
              .map(
                (member) => `<div class="member">
                  <span class="member-path">${esc(member.path)}</span>
                  ${member.is_keeper ? '<span class="badge">keeper</span>' : '<span class="badge warn">redundante</span>'}
                </div>`
              )
              .join("")}
          </div>`
        )
        .join("")
    : `<div class="empty">nenhuma duplicata detectada</div>`;
}

async function loadVersions() {
  const data = await api("/api/versions?limit=50");
  const counts = data.counts;

  $("#versions-counts").innerHTML = counts.length
    ? counts.map((row) => barRow(row.version, row.total, maxOf(counts, "total"), { alt: true })).join("")
    : `<div class="empty">nenhuma versao classificada ainda</div>`;

  $("#versions-table tbody").innerHTML = data.samples.length
    ? data.samples
        .map(
          (row) => `<tr>
            <td class="path">${esc(row.path)}</td>
            <td>${esc(row.version)}</td>
            <td>${esc(row.source)}</td>
            <td>${esc(row.confidence)}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="4" class="empty">sem dados</td></tr>`;
}

async function loadIntegrations() {
  const data = await api("/api/integrations");

  $("#integrations-cards").innerHTML = data.reports
    .map((report) => {
      if (!report.available) {
        return `<div class="card">
          <span class="label">${esc(report.software)}</span>
          <span class="value small is-warn">indisponivel</span>
          <div class="hint">${esc(report.error)}</div>
        </div>`;
      }
      const tone = report.missing ? "is-warn" : "is-ok";
      const sample = report.samples.length ? `<div class="hint">ex: ${esc(report.samples[0])}</div>` : "";
      return `<div class="card">
        <span class="label">${esc(report.software)}</span>
        <span class="value ${tone}">${num(report.resolved)}/${num(report.total)}</span>
        <div class="hint">resolvidos · ${num(report.missing)} ausentes</div>
        ${sample}
      </div>`;
    })
    .join("");
}

async function loadManual() {
  const data = await api("/api/capabilities");

  $("#manual-pipeline").innerHTML = data.pipeline
    .map((stage) => {
      const active = stage.status === "ativo" || stage.status === "parcial";
      const badge = active
        ? `<span class="badge">${esc(stage.status)}</span>`
        : '<span class="badge muted">planejado</span>';
      return `<div class="stage${active ? "" : " is-off"}">
        <div class="layer">${esc(stage.layer)}</div>
        <div>
          <div class="stage-name">${esc(stage.name)} ${badge}</div>
          <div class="stage-detail">${esc(stage.detail)}</div>
        </div>
      </div>`;
    })
    .join("");

  $("#manual-commands").innerHTML = data.commands
    .map(
      (cmd) => `<div class="cmd">
        <div class="cmd-usage">$ ${esc(cmd.usage)}</div>
        <div class="cmd-summary">${esc(cmd.summary)}</div>
        <div class="cmd-detail">${esc(cmd.detail)}</div>
      </div>`
    )
    .join("");

  $("#manual-safety").innerHTML = data.safety
    .map(
      (item) => `<div class="safe-item">
        <div class="safe-title">${esc(item.title)}</div>
        <div class="safe-detail">${esc(item.detail)}</div>
      </div>`
    )
    .join("");
}

const loaders = {
  overview: loadOverview,
  library: loadLibrary,
  duplicates: loadDuplicates,
  versions: loadVersions,
  integrations: loadIntegrations,
  manual: loadManual,
};

async function run(view) {
  try {
    showBanner("");
    setStatus("", "sincronizando");
    await loaders[view]();
    setStatus("ok", "online");
  } catch (err) {
    setStatus("fail", "erro");
    showBanner(`Falha ao carregar "${view}": ${err.message}`);
  }
}

function activate(view) {
  $$(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.view === view));
  $$(".view").forEach((section) => section.classList.toggle("is-active", section.id === `view-${view}`));
  return run(view);
}

$("#tabs").addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) {
    activate(tab.dataset.view);
  }
});

$("#library-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run("library");
});

api("/api/version")
  .then((info) => {
    $("#meta-app").textContent = `v${info.version}`;
  })
  .catch(() => {});

activate("overview");
