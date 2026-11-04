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

const LIB_COLUMNS = [
  { key: "title", label: "titulo", type: "text" },
  { key: "artist", label: "artista", type: "text" },
  { key: "album", label: "album", type: "text" },
  { key: "genre", label: "genero", type: "text" },
  { key: "bpm", label: "bpm", type: "num" },
  { key: "key", label: "tom", type: "text" },
  { key: "ext", label: "formato", type: "text" },
  { key: "duration", label: "duracao", type: "num" },
];

const libraryState = {
  tracks: [],
  genre: null,
  query: "",
  sortKey: "title",
  sortDir: "asc",
  selected: null,
};

const NO_GENRE = "sem genero";

function trackGenreName(track) {
  return (track.genre || "").trim() || NO_GENRE;
}

function trackBpmValue(track) {
  const value = Number.parseFloat(track.bpm || track.bpm_analysis);
  return Number.isFinite(value) ? value : null;
}

function trackBpmLabel(track) {
  const value = trackBpmValue(track);
  if (value === null) return "-";
  return track.bpm ? String(track.bpm) : value.toFixed(1);
}

function trackKeyLabel(track) {
  return track.key || track.key_camelot || "-";
}

function trackFormat(track) {
  return String(track.ext || "").replace(".", "").toUpperCase() || "-";
}

function librarySortValue(track, key) {
  if (key === "bpm") return trackBpmValue(track);
  if (key === "duration") return Number(track.duration) || null;
  const value = String(track[key] || "").trim().toLowerCase();
  return value || null;
}

function compareLibraryTracks(a, b) {
  const av = librarySortValue(a, libraryState.sortKey);
  const bv = librarySortValue(b, libraryState.sortKey);
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  const dir = libraryState.sortDir === "desc" ? -1 : 1;
  if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
  return String(av).localeCompare(String(bv), "pt-BR") * dir;
}

function filteredLibraryTracks() {
  const query = libraryState.query.toLowerCase();
  const genre = libraryState.genre ? libraryState.genre.toLowerCase() : null;
  return libraryState.tracks
    .filter((track) => {
      if (genre && trackGenreName(track).toLowerCase() !== genre) return false;
      if (!query) return true;
      return [track.title, track.artist, track.album, track.path].some((value) =>
        String(value || "").toLowerCase().includes(query)
      );
    })
    .sort(compareLibraryTracks);
}

function renderLibraryHead() {
  const cells = LIB_COLUMNS.map((column) => {
    const active = libraryState.sortKey === column.key;
    const arrow = active
      ? `<span class="sort-arrow">${libraryState.sortDir === "asc" ? "^" : "v"}</span>`
      : "";
    const cls = [column.type === "num" ? "num-col" : "", active ? "is-sorted" : ""].filter(Boolean).join(" ");
    return `<th data-key="${column.key}"${cls ? ` class="${cls}"` : ""}>${esc(column.label)}${arrow}</th>`;
  });
  $("#library-head").innerHTML = `<th class="idx">#</th>${cells.join("")}`;
}

function renderLibraryGenres() {
  const counts = new Map();
  for (const track of libraryState.tracks) {
    const name = trackGenreName(track);
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  const items = [
    `<button type="button" class="lib-side-item${libraryState.genre ? "" : " is-active"}" data-genre="">
      <span>toda a biblioteca</span><span class="count">${num(libraryState.tracks.length)}</span>
    </button>`,
  ];
  for (const [name, total] of counts.entries()) {
    const active = libraryState.genre && libraryState.genre.toLowerCase() === name.toLowerCase();
    items.push(`<button type="button" class="lib-side-item${active ? " is-active" : ""}" data-genre="${esc(name)}">
      <span>${esc(name)}</span><span class="count">${num(total)}</span>
    </button>`);
  }
  $("#library-genres").innerHTML = items.join("");
}

function renderLibraryRows() {
  const rows = filteredLibraryTracks();
  const body = $("#library-table tbody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${LIB_COLUMNS.length + 1}" class="empty">nenhuma faixa encontrada</td></tr>`;
    return rows;
  }
  body.innerHTML = rows
    .map((track, index) => {
      const selected = libraryState.selected && libraryState.selected.path === track.path;
      const cls = [selected ? "is-selected" : "", track.is_missing ? "is-missing" : ""].filter(Boolean).join(" ");
      return `<tr data-path="${esc(track.path)}"${cls ? ` class="${cls}"` : ""}>
        <td class="idx">${index + 1}</td>
        <td class="title">${esc(track.title || "(sem titulo)")}</td>
        <td>${esc(track.artist || "-")}</td>
        <td>${esc(track.album || "-")}</td>
        <td>${esc(trackGenreName(track))}</td>
        <td class="num-col">${esc(trackBpmLabel(track))}</td>
        <td>${esc(trackKeyLabel(track))}</td>
        <td>${esc(trackFormat(track))}</td>
        <td class="num-col">${track.duration ? duration(track.duration) : "-"}</td>
      </tr>`;
    })
    .join("");
  return rows;
}

function renderLibraryDetail() {
  const track = libraryState.selected;
  const empty = $("#library-detail-empty");
  const body = $("#library-detail-body");
  if (!track) {
    empty.classList.remove("hidden");
    body.classList.add("hidden");
    body.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");
  body.classList.remove("hidden");
  const rows = [
    ["artista", track.artist],
    ["album", track.album],
    ["genero", trackGenreName(track)],
    ["bpm", trackBpmLabel(track)],
    ["tom", trackKeyLabel(track)],
    ["formato", trackFormat(track)],
    ["duracao", track.duration ? duration(track.duration) : ""],
    ["tamanho", track.size ? `${(Number(track.size) / (1024 * 1024)).toFixed(1)} MB` : ""],
  ];
  body.innerHTML = `
    <div class="lib-detail-ident">
      <div class="lib-detail-title">${esc(track.title || "(sem titulo)")}</div>
      <div class="lib-detail-sub">${esc(track.artist || "artista desconhecido")}</div>
      ${track.is_missing ? '<span class="badge warn">arquivo ausente</span>' : ""}
      <div class="lib-detail-path">${esc(track.path)}</div>
    </div>
    <div class="lib-detail-grid">
      ${rows
        .map(([label, value]) => `<div class="row"><span>${esc(label)}</span><span>${esc(value || "-")}</span></div>`)
        .join("")}
    </div>
  `;
}

function updateLibraryStatus(rows) {
  const shown = rows.length;
  const total = libraryState.tracks.length;
  const missing = rows.filter((track) => track.is_missing).length;
  const totalDuration = rows.reduce((acc, track) => acc + (Number(track.duration) || 0), 0);
  $("#library-count").textContent = `${num(shown)} faixa${shown === 1 ? "" : "s"}`;
  $("#library-scope").textContent = libraryState.genre ? `genero: ${libraryState.genre}` : "toda a biblioteca";
  $("#library-status").textContent = `${num(shown)} de ${num(total)} faixa(s) exibida(s)`;
  const bits = [];
  if (missing) bits.push(`${num(missing)} ausente(s)`);
  if (shown) bits.push(`duracao ${duration(totalDuration)}`);
  if (libraryState.query) bits.push(`busca: "${libraryState.query}"`);
  $("#library-status-right").textContent = bits.join(" · ");
}

function refreshLibrary() {
  renderLibraryHead();
  renderLibraryGenres();
  renderLibraryDetail();
  const rows = renderLibraryRows();
  updateLibraryStatus(rows);
}

function toggleLibraryClear() {
  $("#library-clear").classList.toggle("hidden", !$("#library-query").value);
}

async function loadLibrary() {
  const data = await api("/api/tracks?limit=1000&q=");
  libraryState.tracks = data.tracks || [];
  libraryState.query = $("#library-query").value.trim();
  if (
    libraryState.genre &&
    !libraryState.tracks.some((track) => trackGenreName(track).toLowerCase() === libraryState.genre.toLowerCase())
  ) {
    libraryState.genre = null;
  }
  libraryState.selected = libraryState.tracks.find((track) => track.path === (libraryState.selected || {}).path) || null;
  toggleLibraryClear();
  refreshLibrary();
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

  const notice = $("#integrations-notice");
  notice.textContent = data.notice || "Integracoes Rekordbox/Serato em beta.";
  notice.classList.remove("hidden");

  $("#integrations-cards").innerHTML = data.reports
    .map((report) => {
      if (!report.available) {
        return `<div class="card">
          <span class="label">${esc(report.software)} <span class="badge warn">beta</span></span>
          <span class="value small is-warn">indisponivel</span>
          <div class="hint">${esc(report.error)}</div>
        </div>`;
      }
      const tone = report.missing ? "is-warn" : "is-ok";
      const sample = report.samples.length ? `<div class="hint">ex: ${esc(report.samples[0])}</div>` : "";
      return `<div class="card">
        <span class="label">${esc(report.software)} <span class="badge warn">beta</span></span>
        <span class="value ${tone}">${num(report.resolved)}/${num(report.total)}</span>
        <div class="hint">resolvidos · ${num(report.missing)} ausentes</div>
        ${sample}
      </div>`;
    })
    .join("");
}

async function loadPremium() {
  const data = await api("/api/capabilities");
  const premium = data.premium;
  const license = premium.license || {};

  const notice = $("#premium-notice");
  notice.textContent = premium.notice || "Camada premium preparada no app.";
  notice.classList.remove("hidden");

  $("#premium-plans").innerHTML = premium.plans
    .map(
      (plan) => `<div class="card">
        <span class="label">${esc(plan.name)}</span>
        <span class="value small">${esc(plan.billing)}</span>
        <div class="hint">${esc(plan.detail)}</div>
        <div class="hint"><span class="badge">${esc(plan.cta)}</span></div>
      </div>`
    )
    .join("");

  $("#premium-features").innerHTML = premium.features
    .map(
      (feature) => `<div class="safe-item">
        <div class="safe-title">${esc(feature.name)} <span class="badge warn">${esc(feature.status)}</span></div>
        <div class="safe-detail">${esc(feature.detail)} Planos: ${esc(feature.included_in.join(", "))}.</div>
      </div>`
    )
    .join("");

  $("#premium-install").innerHTML = `
    <div class="safe-item">
      <div class="safe-title">Extra opcional de download</div>
      <div class="safe-detail">Instalacao: <code>${esc(premium.install)}</code></div>
    </div>
    <div class="safe-item">
      <div class="safe-title">Liberacao comercial</div>
      <div class="safe-detail">Estado atual: ${esc(premium.checkout)}. O app ja expoe os planos e a ativacao pode ser feita manualmente, sem intermediario.</div>
    </div>
    <div class="safe-item">
      <div class="safe-title">Licenca offline</div>
      <div class="safe-detail">Valida: ${license.valid ? "sim" : "nao"} · motivo: ${esc(license.reason || "-")} · plano: ${esc(license.plan || "-")} · cliente: ${esc(license.customer_id || "-")}</div>
    </div>
  `;

  await loadDownloadPanel();
  await loadCurationPanel();
}

const DOWNLOAD_TASK_LABELS = {
  probe: "inspecao de URLs",
  download: "download de audio",
};

const DOWNLOAD_RESULT_LABELS = {
  count: "candidatos",
  total: "total",
  ok: "baixados",
  errors: "erros",
  target: "destino",
  scan_hint: "proximo passo",
};

const DOWNLOAD = { timer: null };

function downloadBusy(busy) {
  ["#download-probe", "#download-start"].forEach((selector) => {
    const el = $(selector);
    if (el) el.disabled = busy;
  });
}

function fillDownloadFormats(formats) {
  const select = $("#download-format");
  if (select.dataset.filled || !formats || !formats.length) return;
  select.innerHTML = formats
    .map((name) => `<option value="${esc(name)}">${esc(name)}</option>`)
    .join("");
  select.dataset.filled = "1";
}

function renderDownloadTable(task, items) {
  const head = $("#download-table thead");
  const body = $("#download-table tbody");
  if (task === "download") {
    head.innerHTML = "<tr><th>url</th><th>arquivo</th><th>status</th></tr>";
    body.innerHTML = items && items.length
      ? items
          .map(
            (item) => `<tr>
        <td class="mono" title="${esc(item.url)}">${esc(shorten(item.url, 46))}</td>
        <td class="mono" title="${esc(item.path || "")}">${esc(item.path ? shorten(item.path, 46) : "-")}</td>
        <td>${
          item.ok
            ? '<span class="badge ok">baixado</span>'
            : `<span class="badge fail">${esc(item.message || "erro")}</span>`
        }</td>
      </tr>`
          )
          .join("")
      : `<tr><td colspan="3" class="empty">sem resultados ainda</td></tr>`;
    return;
  }
  head.innerHTML = "<tr><th>titulo</th><th>canal</th><th>duracao</th><th>formato</th></tr>";
  body.innerHTML = items && items.length
    ? items
        .map(
          (item) => `<tr>
        <td>${esc(item.title || "-")}</td>
        <td>${esc(item.uploader || "-")}</td>
        <td class="num">${item.duration ? `${num(Math.round(item.duration))}s` : "-"}</td>
        <td><span class="badge muted">${esc(item.ext || "-")}</span></td>
      </tr>`
        )
        .join("")
    : `<tr><td colspan="4" class="empty">sem resultados ainda</td></tr>`;
}

function renderDownloadJob(job) {
  const panel = $("#download-job");
  if (!job || !job.status || job.status === "idle") {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  $("#download-job-label").textContent = DOWNLOAD_TASK_LABELS[job.task] || job.task || "download";

  const chip = $("#download-job-status");
  chip.textContent = ORGANIZE_STATUS_LABELS[job.status] || job.status;
  chip.className = `chip signal ${
    job.status === "running" ? "warn" : job.status === "done" ? "ok" : job.status === "error" ? "fail" : ""
  }`.trim();

  const result = job.result || {};
  const rows = Object.entries(result)
    .filter(([key]) => key !== "items")
    .map(
      ([key, value]) => `<div class="kv-row">
        <span>${esc(DOWNLOAD_RESULT_LABELS[key] || key)}</span>
        <span>${organizeResultValue(value)}</span>
      </div>`
    )
    .join("");
  const note = job.message ? `<div class="org-note">${esc(job.message)}</div>` : "";
  $("#download-job-body").innerHTML = rows
    ? `<div class="kv org-kv">${rows}</div>${note}`
    : note || `<div class="empty">sem detalhes</div>`;
  renderDownloadTable(job.task, result.items);
}

function pollDownloadJob(task) {
  window.clearTimeout(DOWNLOAD.timer);
  DOWNLOAD.timer = window.setTimeout(async () => {
    let job = null;
    try {
      job = await api(`/api/premium/job?task=${encodeURIComponent(task)}`);
    } catch (err) {
      showBanner(`Falha ao consultar o download: ${err.message}`);
    }
    if (job) renderDownloadJob(job);
    if (job && job.status === "running") {
      pollDownloadJob(task);
      return;
    }
    downloadBusy(false);
  }, 1000);
}

async function startDownloadTask(task) {
  const urls = $("#download-urls").value.trim();
  if (!urls) {
    showBanner("cole ao menos uma URL");
    return;
  }
  downloadBusy(true);
  renderDownloadJob({ task, status: "running", result: {} });
  try {
    showBanner("");
    const body = { urls };
    if (task === "download") {
      body.target = $("#download-target").value.trim();
      body.format = $("#download-format").value;
    }
    const job = await adminFetch(`/api/premium/${task}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    renderDownloadJob(job);
    pollDownloadJob(task);
  } catch (err) {
    downloadBusy(false);
    showBanner(`Falha em ${DOWNLOAD_TASK_LABELS[task] || task}: ${err.message}`);
  }
}

async function loadDownloadPanel() {
  const panel = $("#premium-download");
  if (!panel) return;
  panel.classList.remove("hidden");
  const notice = $("#download-notice");
  const gate = $("#download-gate");
  const consoleEl = $("#download-console");

  let state;
  try {
    state = await api("/api/premium/status");
  } catch (err) {
    notice.textContent = `Painel de download indisponivel: ${err.message}`;
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }

  $("#download-state").textContent = state.ready ? "pronto" : "bloqueado";

  if (!state.licensed) {
    notice.textContent = `Download bloqueado: ${state.reason || "licenca sem o recurso premium.download"}.`;
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }
  if (!state.backend_available) {
    notice.textContent = `Backend de download ausente — instale o extra premium: ${state.install}`;
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }

  notice.textContent = "Recurso liberado: cole as URLs, inspecione (dry-run) e baixe para o destino.";
  const adminStatus = await api("/api/admin/status");
  if (!adminStatus.enabled) {
    notice.textContent += " Defina [license] admin_token para habilitar o download pela UI.";
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }
  if (!adminToken()) {
    gate.classList.remove("hidden");
    consoleEl.classList.add("hidden");
    return;
  }

  gate.classList.add("hidden");
  consoleEl.classList.remove("hidden");
  const target = $("#download-target");
  if (!target.value) target.value = state.default_target || "downloads";
  fillDownloadFormats(state.formats);
}

const CURATION = { choices: [] };

function curationOptionsHtml(selected) {
  return CURATION.choices
    .map(
      (choice) =>
        `<option value="${choice.genre_id}"${choice.genre_id === selected ? " selected" : ""}>${esc(choice.label)}</option>`
    )
    .join("");
}

function renderCurationTable(items) {
  const body = $("#curation-table tbody");
  const rows = items || [];
  $("#curation-count").textContent = `${rows.length} pendente${rows.length === 1 ? "" : "s"}`;
  body.innerHTML = rows.length
    ? rows
        .map((item) => {
          const signals = item.signals
            .map((s) => `<span class="badge muted">${esc(s.source)}: ${esc(s.label)}</span>`)
            .join(" ");
          const level =
            item.level === "divergente"
              ? '<span class="badge fail">divergente</span>'
              : '<span class="badge warn">ambigua</span>';
          return `<tr>
        <td><div class="curation-title">${esc(item.title || "-")}</div><div class="curation-sub">${esc(item.artist || "")}</div></td>
        <td>${level}</td>
        <td class="curation-signals">${signals}</td>
        <td><select class="curation-choice" data-track="${item.track_id}">${curationOptionsHtml(item.suggestion.genre_id)}</select></td>
        <td><button type="button" class="btn curation-save" data-track="${item.track_id}">gravar</button></td>
      </tr>`;
        })
        .join("")
    : `<tr><td colspan="5" class="empty">sem conflitos pendentes</td></tr>`;
}

async function loadCurationPanel() {
  const panel = $("#premium-curation");
  if (!panel) return;
  panel.classList.remove("hidden");
  const notice = $("#curation-notice");
  const gate = $("#curation-gate");
  const consoleEl = $("#curation-console");

  let payload;
  try {
    payload = await api("/api/premium/curation");
  } catch (err) {
    notice.textContent = `Curadoria indisponivel: ${err.message}`;
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }

  $("#curation-state").textContent = payload.ready ? "pronto" : "bloqueado";
  CURATION.choices = payload.choices || [];

  if (!payload.licensed) {
    notice.textContent = `Curadoria bloqueada: ${payload.reason || "licenca sem o recurso premium.assisted_curation"}.`;
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }
  notice.textContent = "Recurso liberado: revise os conflitos e grave a decisao de genero.";
  const adminStatus = await api("/api/admin/status");
  if (!adminStatus.enabled) {
    notice.textContent += " Defina [license] admin_token para gravar decisoes pela UI.";
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }
  if (!adminToken()) {
    gate.classList.remove("hidden");
    consoleEl.classList.add("hidden");
    return;
  }
  gate.classList.add("hidden");
  consoleEl.classList.remove("hidden");
  renderCurationTable(payload.items);
}

async function saveCurationDecision(trackId) {
  const select = $(`.curation-choice[data-track="${trackId}"]`);
  if (!select) return;
  try {
    showBanner("");
    const result = await adminFetch("/api/premium/curation", {
      method: "POST",
      body: JSON.stringify({ track_id: Number(trackId), genre_id: Number(select.value) }),
    });
    await loadCurationPanel();
    showBanner(`Decisao gravada (source=manual). Conflitos pendentes: ${result.pending ?? 0}.`);
  } catch (err) {
    showBanner(`Falha ao gravar a decisao: ${err.message}`);
  }
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

const ADMIN_TOKEN_KEY = "djlife.adminToken";

function adminToken() {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY) || "";
  } catch (err) {
    return "";
  }
}

function setAdminToken(value) {
  try {
    if (value) sessionStorage.setItem(ADMIN_TOKEN_KEY, value);
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch (err) {
    /* sessionStorage indisponivel */
  }
}

async function adminFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Admin-Token": adminToken(),
      ...(options.headers || {}),
    },
  });
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

function licenseBadge(status) {
  const tone = status === "active" ? "" : status === "revoked" ? " warn" : " muted";
  return `<span class="badge${tone}">${esc(status || "-")}</span>`;
}

function renderAdminSummary(status) {
  const registry = status.registry_path
    ? `<div class="kv-row"><span>registro</span><span title="${esc(status.registry_path)}">${esc(shorten(status.registry_path, 46))}</span></div>`
    : "";
  const key = status.has_private_key === undefined
    ? ""
    : `<div class="kv-row"><span>chave privada</span><span>${status.has_private_key ? "presente" : "ausente"}</span></div>`;
  $("#admin-summary").innerHTML = `
    <div class="kv-row"><span>painel admin</span><span>${status.enabled ? "habilitado" : "desabilitado"}</span></div>
    <div class="kv-row"><span>modo owner</span><span>${status.owner ? "ativo (acesso total)" : "inativo"}</span></div>
    ${key}
    ${registry}
  `;
}

async function refreshLicenses() {
  const data = await adminFetch("/api/admin/licenses");
  if (data.status) renderAdminSummary(data.status);
  const rows = data.licenses || [];
  $("#admin-table tbody").innerHTML = rows.length
    ? rows
        .map(
          (row) => `<tr>
            <td>${esc(row.customer_id)}</td>
            <td>${esc(row.plan)}</td>
            <td>${licenseBadge(row.effective_status)}</td>
            <td class="mono">${esc(row.expires_at || "sem expiracao")}</td>
            <td class="mono">${esc(shorten(row.machine_hash || "-", 16))}</td>
            <td class="mono">${esc(row.id)}</td>
            <td>
              <button class="btn ghost" data-action="renew" data-id="${esc(row.id)}">renovar</button>
              <button class="btn ghost" data-action="revoke" data-id="${esc(row.id)}">revogar</button>
            </td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="7" class="empty">nenhuma licenca registrada</td></tr>`;
  return data;
}

async function loadAdmin() {
  const status = await api("/api/admin/status");
  const notice = $("#admin-notice");
  const gate = $("#admin-gate");
  const consolePanel = $("#admin-console");
  const listPanel = $("#admin-list-panel");

  renderAdminSummary(status);
  notice.classList.remove("hidden");

  if (!status.enabled) {
    notice.textContent =
      "Painel admin desabilitado: defina [license] admin_token no djlife.toml e reinicie o `djlife ui`.";
    gate.classList.add("hidden");
    consolePanel.classList.add("hidden");
    listPanel.classList.add("hidden");
    return;
  }

  notice.textContent = status.owner
    ? "Modo owner ativo: acesso total, sem trava premium."
    : "Painel admin habilitado. Informe o token para gerenciar licencas.";

  if (!adminToken()) {
    gate.classList.remove("hidden");
    consolePanel.classList.add("hidden");
    listPanel.classList.add("hidden");
    return;
  }

  try {
    await refreshLicenses();
  } catch (err) {
    setAdminToken("");
    gate.classList.remove("hidden");
    consolePanel.classList.add("hidden");
    listPanel.classList.add("hidden");
    throw new Error(`sessao admin recusada: ${err.message}`);
  }
  gate.classList.add("hidden");
  consolePanel.classList.remove("hidden");
  listPanel.classList.remove("hidden");
}

async function initAdminTab() {
  try {
    const status = await api("/api/admin/status");
    if (status.enabled) {
      $('.tab[data-view="admin"]').classList.remove("hidden");
    }
  } catch (err) {
    /* sem painel admin: mantem a interface limpa */
  }
}

const ORGANIZE_TASK_LABELS = {
  scan: "varredura de pastas",
  classify: "classificacao de generos",
  apply: "aplicacao do plano",
  undo: "reversao de lote",
};

const ORGANIZE_STATUS_LABELS = {
  idle: "ocioso",
  running: "executando",
  done: "concluido",
  error: "erro",
};

const ORGANIZE_RESULT_LABELS = {
  seen: "vistos",
  new: "novos",
  updated: "atualizados",
  missing: "ausentes",
  indexed: "indexadas",
  errors: "erros",
  taxonomy_version: "taxonomia",
  genres: "generos",
  layers: "camadas",
  rules: "regras",
  tracks: "faixas",
  tagged: "marcadas",
  ruled: "por regras",
  unresolved: "sem resolucao",
  inserted: "inseridas",
  batch: "lote",
  strategy: "estrategia",
  linked: "hardlinks",
  moved: "movidas",
  skipped: "ignoradas",
  applied: "aplicadas",
  requested: "selecionadas",
  removed: "removidos",
  restored: "restaurados",
  untagged: "tags removidas",
};

const ORGANIZE_PLAN_LABELS = {
  ready: "pronto",
  exists: "ja existe",
  conflict: "conflito",
  unclassified: "sem genero",
};

const ORGANIZE_PLAN_TONE = {
  ready: "ok",
  exists: "muted",
  conflict: "warn",
  unclassified: "warn",
};

const ORGANIZE_STRATEGY_LABELS = {
  hardlink: "hardlink (preserva originais)",
  move: "mover (realoca originais)",
  tag_only: "somente tags (sem mover)",
};

const ORGANIZE = {
  plan: null,
  selected: new Set(),
  timer: null,
};

function organizeBusy(busy) {
  ["#organize-scan", "#organize-classify", "#organize-plan"].forEach((selector) => {
    const el = $(selector);
    if (el) el.disabled = busy;
  });
  const checkAll = $("#organize-check-all");
  if (checkAll) checkAll.disabled = busy;
}

function renderOrganizeConfig(files) {
  const select = $("#organize-strategy");
  const strategies = (files && files.strategies) || [];
  select.innerHTML = strategies
    .map(
      (name) =>
        `<option value="${esc(name)}">${esc(ORGANIZE_STRATEGY_LABELS[name] || name)}</option>`
    )
    .join("");
  if (files && files.strategy) select.value = files.strategy;

  $("#organize-target").value = (files && files.target) || "";

  const chip = $("#organize-config-state");
  chip.textContent = files && files.target ? "configurado" : "nao definido";
  chip.className = `chip signal ${files && files.target ? "ok" : "warn"}`;
}

function renderOrganizeSummary(status) {
  const roots = status.roots && status.roots.length
    ? status.roots.map((root) => `<span title="${esc(root)}">${esc(shorten(root, 44))}</span>`).join(" · ")
    : "nao configurada";
  $("#organize-summary").innerHTML = `
    <div class="kv-row"><span>raizes de varredura</span><span>${roots}</span></div>
    <div class="kv-row"><span>destino organizado</span><span title="${esc(status.target || "")}">${status.target ? esc(shorten(status.target, 48)) : "nao definido"}</span></div>
    <div class="kv-row"><span>estrategia</span><span>${esc(status.strategy)}</span></div>
    <div class="kv-row"><span>template</span><span class="mono">${esc(status.template)}</span></div>
    <div class="kv-row"><span>catalogo</span><span title="${esc(status.catalog)}">${esc(shorten(status.catalog, 48))}</span></div>
  `;
  renderOrganizeConfig(status);
}

function organizeResultValue(value) {
  if (Array.isArray(value)) return value.map((item) => esc(item)).join(", ") || "-";
  if (value === null || value === undefined || value === "") return "-";
  return esc(value);
}

function renderOrganizeJob(job) {
  const panel = $("#organize-job");
  if (!job || !job.status || job.status === "idle") {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  $("#organize-job-label").textContent = ORGANIZE_TASK_LABELS[job.task] || job.task || "tarefa";

  const status = job.status;
  const chip = $("#organize-job-status");
  chip.textContent = ORGANIZE_STATUS_LABELS[status] || status;
  chip.className = `chip signal ${
    status === "running" ? "warn" : status === "done" ? "ok" : status === "error" ? "fail" : ""
  }`.trim();

  const isScan = job.result === undefined;
  const result = isScan
    ? {
        seen: job.seen,
        new: job.new,
        updated: job.updated,
        missing: job.missing,
        indexed: job.indexed,
        errors: job.errors,
      }
    : job.result || {};
  const rows = Object.entries(result)
    .map(
      ([key, value]) => `<div class="kv-row">
        <span>${esc(ORGANIZE_RESULT_LABELS[key] || key)}</span>
        <span>${organizeResultValue(value)}</span>
      </div>`
    )
    .join("");
  const message = job.message || job.error || "";
  const note = message ? `<div class="org-note">${esc(message)}</div>` : "";
  $("#organize-job-body").innerHTML = rows
    ? `<div class="kv org-kv">${rows}</div>${note}`
    : note || `<div class="empty">sem detalhes</div>`;
}

function organizeRow(item) {
  const tone = ORGANIZE_PLAN_TONE[item.status] || "";
  const check = item.status === "ready"
    ? `<input type="checkbox" class="org-item-check" data-track="${item.track_id}"${
        ORGANIZE.selected.has(item.track_id) ? " checked" : ""
      } />`
    : `<span class="org-lock" title="somente itens prontos podem ser aplicados">-</span>`;
  const genre = [item.genre, item.subgenre].filter(Boolean).join(" / ") || "-";
  return `<tr class="org-row">
    <td class="org-check">${check}</td>
    <td class="mono" title="${esc(item.src)}">${esc(shorten(item.src, 46))}</td>
    <td>${esc(genre)}</td>
    <td class="mono" title="${esc(item.dst || "")}">${esc(item.dst ? shorten(item.dst, 46) : "-")}</td>
    <td><span class="badge ${tone}">${esc(ORGANIZE_PLAN_LABELS[item.status] || item.status)}</span></td>
  </tr>`;
}

function syncOrganizeSelection() {
  const items = (ORGANIZE.plan && ORGANIZE.plan.items) || [];
  const ready = items.filter((item) => item.status === "ready");
  const count = ORGANIZE.selected.size;
  const all = $("#organize-check-all");
  all.checked = ready.length > 0 && count === ready.length;
  all.indeterminate = count > 0 && count < ready.length;
  const button = $("#organize-apply");
  button.disabled = ready.length === 0;
  button.textContent = count ? `aplicar ${num(count)} selecionados` : "aplicar prontos";
}

function renderOrganizePlan() {
  const plan = ORGANIZE.plan;
  if (!plan) return;
  const summary = plan.summary || {};
  $("#organize-plan-summary").textContent =
    `${num(summary.total)} itens · ${num(summary.ready)} prontos · ${num(summary.conflict)} conflitos · ${num(summary.unclassified)} sem genero`;

  const ready = new Set(
    plan.items.filter((item) => item.status === "ready").map((item) => item.track_id)
  );
  ORGANIZE.selected = new Set([...ORGANIZE.selected].filter((id) => ready.has(id)));

  $("#organize-table tbody").innerHTML = plan.items.length
    ? plan.items.map(organizeRow).join("")
    : `<tr><td colspan="5" class="empty">nenhum item no plano</td></tr>`;
  syncOrganizeSelection();
}

async function refreshOrganizePlan() {
  const panel = $("#organize-plan-panel");
  try {
    ORGANIZE.plan = await api("/api/organize/plan");
  } catch (err) {
    ORGANIZE.plan = null;
    panel.classList.remove("hidden");
    $("#organize-plan-summary").textContent = "indisponivel";
    $("#organize-table tbody").innerHTML = `<tr><td colspan="5" class="empty">${esc(err.message)}</td></tr>`;
    $("#organize-apply").disabled = true;
    return;
  }
  panel.classList.remove("hidden");
  renderOrganizePlan();
}

function renderOrganizeHistory(data) {
  const rows = (data && data.batches) || [];
  $("#organize-history tbody").innerHTML = rows.length
    ? rows
        .map(
          (row) => `<tr>
            <td class="mono">${esc(row.batch)}</td>
            <td class="mono">${esc(row.created_at)}</td>
            <td>${esc(row.strategy)}</td>
            <td class="num">${num(row.files)}</td>
            <td class="num">${num(row.tags)}</td>
            <td>${
              row.pending
                ? `<span class="badge warn">${num(row.pending)} pendentes</span>`
                : `<span class="badge muted">aplicado</span>`
            }</td>
            <td>${
              row.pending
                ? `<button class="btn ghost" data-batch="${esc(row.batch)}">desfazer</button>`
                : ""
            }</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="7" class="empty">nenhum lote aplicado ainda</td></tr>`;
}

async function refreshOrganizeHistory() {
  try {
    renderOrganizeHistory(await api("/api/organize/history?limit=20"));
  } catch (err) {
    $("#organize-history tbody").innerHTML = `<tr><td colspan="7" class="empty">${esc(err.message)}</td></tr>`;
  }
}

function pollOrganizeJob(task) {
  window.clearTimeout(ORGANIZE.timer);
  ORGANIZE.timer = window.setTimeout(async () => {
    let job = null;
    try {
      job = await api(`/api/organize/job?task=${encodeURIComponent(task)}`);
    } catch (err) {
      showBanner(`Falha ao consultar a tarefa: ${err.message}`);
    }
    if (job) renderOrganizeJob(job);
    if (job && job.status === "running") {
      pollOrganizeJob(task);
      return;
    }
    organizeBusy(false);
    await refreshOrganizeHistory();
    await refreshOrganizePlan();
  }, 1200);
}

async function startOrganizeTask(task, body = {}) {
  organizeBusy(true);
  try {
    showBanner("");
    const job = await adminFetch(`/api/organize/${task}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    renderOrganizeJob(job);
    pollOrganizeJob(task);
  } catch (err) {
    organizeBusy(false);
    showBanner(`Falha em ${ORGANIZE_TASK_LABELS[task] || task}: ${err.message}`);
  }
}

async function saveOrganizeConfig() {
  const target = $("#organize-target").value.trim();
  const strategy = $("#organize-strategy").value;
  if (!target) {
    showBanner("informe a pasta de destino da organizacao");
    return;
  }
  try {
    showBanner("");
    await adminFetch("/api/setup/files", {
      method: "POST",
      body: JSON.stringify({ target, strategy }),
    });
    showBanner("destino da organizacao salvo");
    renderOrganizeSummary(await api("/api/organize/status"));
    ORGANIZE.selected = new Set();
    await refreshOrganizePlan();
  } catch (err) {
    showBanner(`Falha ao salvar destino: ${err.message}`);
  }
}

async function loadOrganize() {
  const adminStatus = await api("/api/admin/status");
  const notice = $("#organize-notice");
  const gate = $("#organize-gate");
  const consoleEl = $("#organize-console");
  notice.classList.remove("hidden");

  try {
    renderOrganizeSummary(await api("/api/organize/status"));
    $("#organize-summary").classList.remove("hidden");
  } catch (err) {
    $("#organize-summary").classList.add("hidden");
  }

  if (!adminStatus.enabled) {
    notice.textContent =
      "Organizacao desabilitada: defina [license] admin_token no djlife.toml e reinicie o `djlife ui`. A escrita no filesystem exige o modo owner/admin.";
    gate.classList.add("hidden");
    consoleEl.classList.add("hidden");
    return;
  }

  notice.textContent = adminStatus.owner
    ? "Modo owner ativo: organizacao liberada. Toda aplicacao registra journal e pode ser revertida."
    : "Informe o token de administracao para varrer, classificar e aplicar o plano.";

  if (!adminToken()) {
    gate.classList.remove("hidden");
    consoleEl.classList.add("hidden");
    return;
  }

  gate.classList.add("hidden");
  consoleEl.classList.remove("hidden");
  await refreshOrganizeHistory();
  await refreshOrganizePlan();
}

$("#organize-login").addEventListener("submit", (event) => {
  event.preventDefault();
  setAdminToken($("#organize-token").value.trim());
  $("#organize-token").value = "";
  run("organize");
});

$("#organize-logout").addEventListener("click", () => {
  setAdminToken("");
  run("organize");
});

$("#organize-scan").addEventListener("click", () => startOrganizeTask("scan"));
$("#organize-classify").addEventListener("click", () => startOrganizeTask("classify"));
$("#organize-plan").addEventListener("click", refreshOrganizePlan);
$("#organize-history-refresh").addEventListener("click", refreshOrganizeHistory);

$("#organize-config-form").addEventListener("submit", (event) => {
  event.preventDefault();
  saveOrganizeConfig();
});

$("#download-form").addEventListener("submit", (event) => event.preventDefault());

$("#download-login").addEventListener("submit", (event) => {
  event.preventDefault();
  setAdminToken($("#download-token").value.trim());
  $("#download-token").value = "";
  run("premium");
});

$("#download-probe").addEventListener("click", () => startDownloadTask("probe"));
$("#download-start").addEventListener("click", () => startDownloadTask("download"));

$("#curation-login").addEventListener("submit", (event) => {
  event.preventDefault();
  setAdminToken($("#curation-token").value.trim());
  $("#curation-token").value = "";
  run("premium");
});

$("#curation-refresh").addEventListener("click", () => loadCurationPanel());

$("#curation-table").addEventListener("click", (event) => {
  const button = event.target.closest(".curation-save");
  if (!button) return;
  saveCurationDecision(button.dataset.track);
});

$("#organize-table").addEventListener("change", (event) => {
  const box = event.target.closest(".org-item-check");
  if (!box) return;
  const id = Number(box.dataset.track);
  if (box.checked) ORGANIZE.selected.add(id);
  else ORGANIZE.selected.delete(id);
  syncOrganizeSelection();
});

$("#organize-check-all").addEventListener("change", (event) => {
  const items = (ORGANIZE.plan && ORGANIZE.plan.items) || [];
  const ready = items.filter((item) => item.status === "ready");
  ORGANIZE.selected = event.target.checked ? new Set(ready.map((item) => item.track_id)) : new Set();
  renderOrganizePlan();
});

$("#organize-select-all").addEventListener("click", () => {
  const items = (ORGANIZE.plan && ORGANIZE.plan.items) || [];
  const ready = items.filter((item) => item.status === "ready");
  const allSelected = ready.length > 0 && ORGANIZE.selected.size === ready.length;
  ORGANIZE.selected = allSelected ? new Set() : new Set(ready.map((item) => item.track_id));
  renderOrganizePlan();
});

$("#organize-apply").addEventListener("click", () => {
  const ids = [...ORGANIZE.selected];
  const body = ids.length ? { track_ids: ids } : {};
  const label = ids.length
    ? `${ids.length} item(ns) selecionado(s)`
    : "todos os itens prontos";
  if (!window.confirm(`Aplicar o plano (${label})? Hardlinks e tags DJLIFE_* serao gravados.`)) return;
  startOrganizeTask("apply", body);
});

$("#organize-history").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-batch]");
  if (!button) return;
  const batch = button.dataset.batch;
  if (!window.confirm(`Reverter o lote ${batch}? Hardlinks e moves serao desfeitos.`)) return;
  startOrganizeTask("undo", { batch });
});

const loaders = {
  overview: loadOverview,
  library: loadLibrary,
  organize: loadOrganize,
  duplicates: loadDuplicates,
  versions: loadVersions,
  integrations: loadIntegrations,
  premium: loadPremium,
  manual: loadManual,
  admin: loadAdmin,
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
  libraryState.query = $("#library-query").value.trim();
  toggleLibraryClear();
  refreshLibrary();
});

$("#library-query").addEventListener("input", () => {
  libraryState.query = $("#library-query").value.trim();
  toggleLibraryClear();
  refreshLibrary();
});

$("#library-clear").addEventListener("click", () => {
  $("#library-query").value = "";
  libraryState.query = "";
  toggleLibraryClear();
  refreshLibrary();
});

$("#library-genres").addEventListener("click", (event) => {
  const button = event.target.closest(".lib-side-item");
  if (!button) return;
  libraryState.genre = button.dataset.genre || null;
  refreshLibrary();
});

$("#library-head").addEventListener("click", (event) => {
  const header = event.target.closest("th[data-key]");
  if (!header) return;
  const key = header.dataset.key;
  if (libraryState.sortKey === key) {
    libraryState.sortDir = libraryState.sortDir === "asc" ? "desc" : "asc";
  } else {
    libraryState.sortKey = key;
    libraryState.sortDir = "asc";
  }
  refreshLibrary();
});

$("#library-table").addEventListener("click", (event) => {
  const row = event.target.closest("tbody tr[data-path]");
  if (!row) return;
  libraryState.selected = libraryState.tracks.find((track) => track.path === row.dataset.path) || null;
  refreshLibrary();
});

$("#admin-login").addEventListener("submit", (event) => {
  event.preventDefault();
  setAdminToken($("#admin-token").value.trim());
  $("#admin-token").value = "";
  run("admin");
});

$("#admin-logout").addEventListener("click", () => {
  setAdminToken("");
  run("admin");
});

$("#admin-issue").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.target);
  const body = {
    customer_id: String(data.get("customer_id") || "").trim(),
    plan: String(data.get("plan") || "lifetime"),
    days: String(data.get("days") || "").trim() || null,
    expires: String(data.get("expires") || "").trim() || null,
    machine_hash: String(data.get("machine_hash") || "").trim() || null,
    passphrase: String(data.get("passphrase") || ""),
    bind_current_machine: data.get("bind_current_machine") === "on",
  };
  if (!body.customer_id) {
    showBanner("Informe o cliente para emitir a licenca.");
    return;
  }
  try {
    showBanner("");
    setStatus("", "emitindo");
    await adminFetch("/api/admin/issue", { method: "POST", body: JSON.stringify(body) });
    event.target.reset();
    await refreshLicenses();
    setStatus("ok", "online");
  } catch (err) {
    setStatus("fail", "erro");
    showBanner(`Falha ao emitir licenca: ${err.message}`);
  }
});

$("#admin-table").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const id = button.dataset.id;
  const action = button.dataset.action;
  let body = null;
  if (action === "renew") {
    const answer = window.prompt("Nova validade em dias (vazio = sem expiracao):", "365");
    if (answer === null) return;
    body = { id, days: answer.trim() || null };
  } else if (action === "revoke") {
    const reason = window.prompt("Motivo da revogacao (opcional):", "");
    if (reason === null) return;
    body = { id, reason: reason.trim() || null };
  } else {
    return;
  }
  try {
    showBanner("");
    await adminFetch(`/api/admin/${action}`, { method: "POST", body: JSON.stringify(body) });
    await refreshLicenses();
  } catch (err) {
    showBanner(`Falha na acao admin: ${err.message}`);
  }
});

async function setupFetch(endpoint, options = {}) {
  const response = await fetch(`/api/setup/${endpoint}`, {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
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

const ONBOARD = {
  places: [],
  path: null,
  parent: null,
  busy: false,
  scanTimer: null,
};

function onboardFeedback(message, tone = "") {
  const box = $("#onboarding-feedback");
  if (!message) {
    box.className = "onboarding-feedback hidden";
    box.textContent = "";
    return;
  }
  box.className = `onboarding-feedback${tone ? ` ${tone}` : ""}`;
  box.textContent = message;
}

function renderOnboardPlaces() {
  $("#onboarding-places").innerHTML = ONBOARD.places.length
    ? ONBOARD.places
        .map(
          (place) => `<button type="button" class="onboard-place${
            place.path === ONBOARD.path ? " is-active" : ""
          }" data-path="${esc(place.path)}">${esc(place.name)}</button>`
        )
        .join("")
    : `<div class="empty">sem locais</div>`;
}

function renderOnboardDirs(data) {
  ONBOARD.path = data.path;
  ONBOARD.parent = data.parent;
  $("#onboarding-current").value = data.path;
  $("#onboarding-up").disabled = !data.parent;
  renderOnboardPlaces();
  $("#onboarding-dirs").innerHTML = data.dirs.length
    ? data.dirs
        .map(
          (dir) => `<button type="button" class="onboard-dir" data-path="${esc(dir.path)}">
            <span class="onboard-dir-icon">/</span><span>${esc(dir.name)}</span>
          </button>`
        )
        .join("")
    : `<div class="empty">nenhuma subpasta aqui</div>`;
}

async function onboardNavigate(path) {
  try {
    renderOnboardDirs(await setupFetch(`list?path=${encodeURIComponent(path)}`));
    onboardFeedback("");
  } catch (err) {
    onboardFeedback(err.message, "fail");
  }
}

async function onboardUse() {
  if (ONBOARD.busy || !ONBOARD.path) return;
  ONBOARD.busy = true;
  try {
    await setupFetch("root", { method: "POST", body: JSON.stringify({ path: ONBOARD.path }) });
    onboardFeedback("pasta raiz salva. Agora escaneie para indexar o acervo.", "ok");
    $("#onboarding-scan").classList.remove("hidden");
    $("#onboarding-use").disabled = true;
  } catch (err) {
    onboardFeedback(err.message, "fail");
  } finally {
    ONBOARD.busy = false;
  }
}

const SCAN_LABELS = { idle: "aguardando", running: "varrendo", done: "concluido", error: "erro" };

function renderOnboardScan(job) {
  const status = job.status || "idle";
  const chip = $("#onboarding-scan-status");
  chip.textContent = SCAN_LABELS[status] || status;
  chip.className = `chip signal ${status === "running" ? "warn" : status === "done" ? "ok" : status === "error" ? "fail" : ""}`.trim();
  const stats = [
    ["vistos", job.seen],
    ["novos", job.new],
    ["atualizados", job.updated],
    ["ausentes", job.missing],
    ["indexados", job.indexed],
    ["erros", job.errors],
  ];
  $("#onboarding-scan-stats").innerHTML = stats
    .map(([label, value]) => `<div class="onboard-stat"><span>${esc(label)}</span><b>${num(value)}</b></div>`)
    .join("");
}

function pollOnboardScan() {
  window.clearTimeout(ONBOARD.scanTimer);
  ONBOARD.scanTimer = window.setTimeout(async () => {
    let job = null;
    try {
      job = await setupFetch("scan");
    } catch (err) {
      onboardFeedback(err.message, "fail");
    }
    if (job) renderOnboardScan(job);
    if (job && job.status === "running") {
      pollOnboardScan();
      return;
    }
    $("#onboarding-scan-now").disabled = false;
    $("#onboarding-scan-now").textContent = "escanear novamente";
    $("#onboarding-finish").classList.remove("hidden");
  }, 1200);
}

async function onboardScan() {
  $("#onboarding-scan-now").disabled = true;
  try {
    renderOnboardScan(await setupFetch("scan", { method: "POST" }));
    pollOnboardScan();
  } catch (err) {
    onboardFeedback(err.message, "fail");
    $("#onboarding-scan-now").disabled = false;
  }
}

async function initOnboarding() {
  const status = await setupFetch("status");
  if (status.configured) return false;
  ONBOARD.places = status.places || [];
  const start = status.places && status.places.length ? status.places[0].path : "/";
  await onboardNavigate(start);
  $("#onboarding").classList.remove("hidden");
  return true;
}

$("#onboarding-places").addEventListener("click", (event) => {
  const button = event.target.closest(".onboard-place");
  if (button) onboardNavigate(button.dataset.path);
});

$("#onboarding-dirs").addEventListener("click", (event) => {
  const button = event.target.closest(".onboard-dir");
  if (button) onboardNavigate(button.dataset.path);
});

$("#onboarding-up").addEventListener("click", () => {
  if (ONBOARD.parent) onboardNavigate(ONBOARD.parent);
});

$("#onboarding-use").addEventListener("click", onboardUse);
$("#onboarding-scan-now").addEventListener("click", onboardScan);

$("#onboarding-finish").addEventListener("click", () => {
  window.clearTimeout(ONBOARD.scanTimer);
  $("#onboarding").classList.add("hidden");
  boot();
});

async function boot() {
  try {
    const info = await api("/api/version");
    $("#meta-app").textContent = `v${info.version}`;
  } catch (err) {
    /* metadados opcionais */
  }
  await initAdminTab();
  await activate("overview");
}

(async () => {
  try {
    if (await initOnboarding()) return;
  } catch (err) {
    showBanner(`Falha ao carregar primeiro acesso: ${err.message}`);
  }
  boot();
})();
