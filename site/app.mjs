const IMPLEMENTATIONS = ["go-gin", "rust-actix", "node-fastify", "python-fastapi"];
const ENDPOINTS = ["/json", "/db/42", "/cpu"];
const NAMES = {
  "go-gin": "Go / Gin",
  "rust-actix": "Rust / Actix Web",
  "node-fastify": "Node.js / Fastify",
  "python-fastapi": "Python / FastAPI",
};
const TESTS = { "/json": "JSON", "/db/42": "PostgreSQL", "/cpu": "CPU" };
const VERSION_KEYS = {
  "go-gin": ["go", "gin", "pgx"],
  "rust-actix": ["rust", "actix-web", "sqlx", "serde", "serde_json"],
  "node-fastify": ["node", "fastify", "pg"],
  "python-fastapi": ["python", "fastapi", "uvicorn", "asyncpg"],
};
const POSITIVE_INTEGER_CONDITIONS = [
  "api_cpus",
  "api_memory_bytes",
  "workers",
  "pool_max",
  "warmup_seconds",
  "duration_seconds",
  "connections",
  "runs",
  "request_timeout_seconds",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function finite(value, label, { positive = false } = {}) {
  assert(typeof value === "number" && Number.isFinite(value), `${label} must be finite`);
  assert(positive ? value > 0 : value >= 0, `${label} is out of range`);
  return value;
}

function integer(value, label) {
  assert(Number.isInteger(value), `${label} must be an integer`);
  return value;
}

function object(value, label) {
  assert(value !== null && typeof value === "object" && !Array.isArray(value), `${label} must be an object`);
  return value;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function validateConditions(conditions) {
  object(conditions, "conditions");
  assert(Number.isInteger(conditions.schema_version) && conditions.schema_version === 1, "unsupported condition schema");
  for (const key of POSITIVE_INTEGER_CONDITIONS) {
    integer(conditions[key], `condition ${key}`);
    assert(conditions[key] > 0, `condition ${key} must be positive`);
  }
  assert(typeof conditions.http_version === "string" && conditions.http_version.length > 0, "invalid HTTP version");
  assert(Array.isArray(conditions.endpoints) && JSON.stringify(conditions.endpoints) === JSON.stringify(ENDPOINTS), "unexpected endpoints");
}

function validateReport(report) {
  object(report, "report");
  assert(Number.isInteger(report.schema_version) && report.schema_version === 1, "unsupported schema");
  assert(report.status === "verified", "result is not verified");
  assert(report.mode === "official" && report.official === true, "result is not official");
  assert(typeof report.completed_at === "string" && !Number.isNaN(Date.parse(report.completed_at)), "invalid completion time");
  validateConditions(report.conditions);

  const metadata = object(report.metadata, "metadata");
  assert(typeof metadata.source_commit === "string" && /^[0-9a-f]{40}$/.test(metadata.source_commit), "invalid source commit");
  const github = object(metadata.github, "GitHub metadata");
  assert(typeof github.run_url === "string" && /^https:\/\/github\.com\/tappe9\/simple-api-benchmark\/actions\/runs\/[1-9][0-9]*$/.test(github.run_url), "invalid Actions URL");
  const versions = object(metadata.versions, "versions");
  const runner = object(metadata.runner, "runner");
  for (const key of ["environment", "os", "architecture", "image_os", "image_version", "cpu_model"]) {
    assert(typeof runner[key] === "string" && runner[key].length > 0, `missing runner ${key}`);
  }

  assert(Array.isArray(report.implementations) && report.implementations.length === IMPLEMENTATIONS.length, "four implementations required");
  const rows = [];
  report.implementations.forEach((backend, backendIndex) => {
    object(backend, "implementation");
    const id = backend.implementation;
    assert(id === IMPLEMENTATIONS[backendIndex], "implementation identity/order mismatch");
    const versionSet = object(versions[id], `versions for ${id}`);
    for (const key of VERSION_KEYS[id]) {
      assert(typeof versionSet[key] === "string" && /^\d+\.\d+\.\d+$/.test(versionSet[key]), `invalid ${id} ${key} version`);
    }
    assert(Array.isArray(backend.endpoints) && backend.endpoints.length === ENDPOINTS.length, "three endpoints required");
    backend.endpoints.forEach((entry, endpointIndex) => {
      object(entry, "endpoint result");
      assert(entry.endpoint === ENDPOINTS[endpointIndex], "endpoint identity/order mismatch");
      const selected = object(entry.selected, "selected run");
      integer(selected.run, "selected run number");
      const rps = finite(selected.requests_per_second, "requests per second", { positive: true });
      const mean = finite(selected.mean_response_time_ms, "mean response time");
      const memoryBytes = finite(selected.peak_memory_bytes, "peak memory", { positive: true });
      integer(selected.memory_samples, "memory samples");
      assert(selected.memory_samples > 0, "memory samples required");
      rows.push({ id, endpoint: entry.endpoint, rps, mean, memory: memoryBytes / 1048576 });
    });
  });
  return { rows, metadata, versions };
}

export function viewModel(report) {
  const { rows, metadata, versions } = validateReport(report);
  return {
    rows,
    versions,
    source: metadata.source_commit,
    completedAt: report.completed_at,
    runUrl: metadata.github.run_url,
    runner: { ...metadata.runner },
    conditions: { ...report.conditions, endpoints: [...report.conditions.endpoints] },
  };
}

export function chartRows(model, endpoint, metric) {
  assert(ENDPOINTS.includes(endpoint), "unsupported endpoint");
  assert(metric === "rps" || metric === "memory", "unsupported metric");
  const rows = model.rows.filter((row) => row.endpoint === endpoint);
  assert(rows.length === IMPLEMENTATIONS.length, "incomplete chart rows");
  const values = rows.map((row) => finite(row[metric], metric, { positive: true }));
  const maximum = Math.max(...values);
  const bestValue = metric === "rps" ? maximum : Math.min(...values);
  return rows.map((row) => ({
    ...row,
    best: row[metric] === bestValue,
    percent: (row[metric] / maximum) * 100,
  }));
}

function number(value) {
  return value.toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function table(model) {
  const rows = model.rows
    .map(
      (row) => `<tr data-result-row><th scope="row">${escapeHtml(NAMES[row.id])}</th><td>${escapeHtml(TESTS[row.endpoint])}</td><td>${number(row.rps)}</td><td>${number(row.mean)}</td><td>${number(row.memory)}</td></tr>`,
    )
    .join("");
  return `<div class="table-scroll"><table><caption>Verified results from this run. Requests/s: higher is better. Response time and observed API memory: lower is better.</caption><thead><tr><th>Backend</th><th>Test</th><th>Requests/s ↑</th><th>Mean response ms ↓</th><th>Observed peak MiB ↓</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function chart(model, endpoint, metric) {
  const rows = chartRows(model, endpoint, metric);
  const isThroughput = metric === "rps";
  const title = isThroughput ? `${TESTS[endpoint]} throughput` : `${TESTS[endpoint]} peak API memory`;
  const guidance = isThroughput ? "Higher is better" : "Lower is better";
  const items = rows
    .map((row) => {
      const value = isThroughput ? `${number(row.rps)} req/s` : `${number(row.memory)} MiB`;
      const winner = row.best ? (isThroughput ? " — fastest in this run" : " — lowest in this run") : "";
      return `<li><div class="bar-label"><span>${escapeHtml(NAMES[row.id])}${winner}</span><strong>${value}</strong></div><meter min="0" max="100" value="${row.percent.toFixed(6)}">${row.percent.toFixed(1)}%</meter></li>`;
    })
    .join("");
  return `<section class="chart" aria-labelledby="${endpoint.replaceAll("/", "-")}-${metric}"><h3 id="${endpoint.replaceAll("/", "-")}-${metric}">${escapeHtml(title)}</h3><p>${guidance}. Bar length shows the measured value; labels and numbers remain the source of meaning.</p><ul>${items}</ul></section>`;
}

function versions(model) {
  return IMPLEMENTATIONS.map((id) => {
    const entries = Object.entries(model.versions[id])
      .map(([key, value]) => `<li><code>${escapeHtml(key)}</code> ${escapeHtml(value)}</li>`)
      .join("");
    return `<section class="version-card"><h3>${escapeHtml(NAMES[id])}</h3><ul>${entries}</ul><a href="https://github.com/tappe9/simple-api-benchmark/tree/${model.source}/apps/${id}">Implementation code</a></section>`;
  }).join("");
}

function environment(model) {
  const runner = model.runner;
  return `<dl class="environment"><div><dt>Runner</dt><dd>${escapeHtml(runner.environment)}</dd></div><div><dt>OS / architecture</dt><dd>${escapeHtml(runner.os)} / ${escapeHtml(runner.architecture)}</dd></div><div><dt>Runner image</dt><dd>${escapeHtml(runner.image_os)} ${escapeHtml(runner.image_version)}</dd></div><div><dt>CPU</dt><dd>${escapeHtml(runner.cpu_model)}</dd></div></dl>`;
}

export function renderReport(report) {
  const model = viewModel(report);
  const charts = ENDPOINTS.flatMap((endpoint) => [chart(model, endpoint, "rps"), chart(model, endpoint, "memory")]).join("");
  const conditions = model.conditions;
  return `<article class="results"><header><p class="eyebrow">Verified official benchmark</p><h2>Results</h2><p>Measured <time datetime="${escapeHtml(model.completedAt)}">${escapeHtml(model.completedAt)}</time> on shared GitHub-hosted hardware. <a href="${escapeHtml(model.runUrl)}">Actions run</a>.</p><p>${conditions.api_cpus} CPU · ${(conditions.api_memory_bytes / 1048576).toFixed(0)} MiB · ${conditions.workers} worker · DB pool ${conditions.pool_max} · HTTP/${escapeHtml(conditions.http_version)} · ${conditions.connections} connections · ${conditions.warmup_seconds}s warm-up · ${conditions.runs} × ${conditions.duration_seconds}s.</p>${environment(model)}</header>${table(model)}<section><h2>Comparison bars</h2><div class="charts">${charts}</div></section><section><h2>Versions in this run</h2><div class="version-grid">${versions(model)}</div></section><section class="limitation"><h2>What this result means</h2><p>This compares complete API stacks on shared hosted hardware, including runtime, framework, HTTP server, database driver, and container configuration. It is a reference for this run, not universal proof that one language or framework is always faster.</p><p><a href="https://github.com/tappe9/simple-api-benchmark/blob/${model.source}/docs/METHODOLOGY.md">Read the methodology</a> · <a href="https://github.com/tappe9/simple-api-benchmark/blob/${model.source}/results/latest.json">Inspect the result JSON</a></p></section></article>`;
}

export async function loadReport(fetcher = fetch) {
  try {
    const response = await fetcher("./results/latest.json", { cache: "no-store" });
    if (response.status === 404) {
      return { state: "empty", html: "", message: "No verified official result is available yet." };
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const report = await response.json();
    return { state: "ready", html: renderReport(report), message: "" };
  } catch (_error) {
    return { state: "unavailable", html: "", message: "Verified results are temporarily unavailable. No missing value is shown as zero." };
  }
}

async function boot() {
  const target = document.getElementById("results");
  if (!target) return;
  const state = await loadReport();
  if (state.state === "ready") {
    target.removeAttribute("role");
    target.innerHTML = state.html;
  } else {
    target.setAttribute("role", "status");
    target.textContent = state.message;
  }
}

if (typeof document !== "undefined") {
  void boot();
}
