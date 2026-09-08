import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const reportPath = new URL('../results/latest.json', import.meta.url);
const report = async () => JSON.parse(await readFile(reportPath, 'utf8'));
const formatted = value => value.toLocaleString('en-US', {
  minimumFractionDigits: 3, maximumFractionDigits: 3,
});
async function subject() {
  try {
    return await import('../site/app.mjs');
  } catch (error) {
    if (error.code === 'ERR_MODULE_NOT_FOUND') {
      assert.fail('site/app.mjs must implement the verified-results viewer');
    }
    throw error;
  }
}

test('the view uses all 12 selected whole-run records without recomputing measurements', async () => {
  const { viewModel } = await subject();
  const source = await report();
  const before = JSON.stringify(source);
  const model = viewModel(source);
  assert.equal(model.rows.length, 12);
  for (const backend of source.implementations) {
    for (const endpoint of backend.endpoints) {
      const row = model.rows.find(r => r.id === backend.implementation && r.endpoint === endpoint.endpoint);
      assert.equal(row.rps, endpoint.selected.requests_per_second);
      assert.equal(row.mean, endpoint.selected.mean_response_time_ms);
      assert.equal(row.memory, endpoint.selected.peak_memory_bytes / 1048576);
    }
  }
  assert.equal(model.source, source.metadata.source_commit);
  assert.equal(model.completedAt, source.completed_at);
  assert.equal(JSON.stringify(source), before);
});

test('bars compare one endpoint and one metric; exact ties share the run-specific label', async () => {
  const { viewModel, chartRows } = await subject();
  const model = viewModel(await report());
  const rows = model.rows.filter(r => r.endpoint === '/json');
  rows.forEach((row, index) => { row.rps = index < 2 ? 10 : 5; row.memory = index < 2 ? 1 : 2; });
  const throughput = chartRows(model, '/json', 'rps');
  assert.equal(throughput.length, 4);
  assert.deepEqual(throughput.map(r => r.best), [true, true, false, false]);
  assert.deepEqual(throughput.map(r => r.percent), [100, 100, 50, 50]);
  const memory = chartRows(model, '/json', 'memory');
  assert.deepEqual(memory.map(r => r.best), [true, true, false, false]);
  assert.deepEqual(memory.map(r => r.percent), [50, 50, 100, 100]);
  assert.throws(() => chartRows(model, '/health', 'rps'));
  assert.throws(() => chartRows(model, '/json', 'score'));
});

test('table and bars render the same selected values, date, source and stack versions', async () => {
  const { renderReport } = await subject();
  const source = await report();
  const html = renderReport(source);
  assert.match(html, /<caption>/);
  assert.equal((html.match(/data-result-row/g) || []).length, 12);
  assert.equal((html.match(/<meter /g) || []).length, 24);
  for (const backend of source.implementations) {
    assert.ok(html.includes(`/tree/${source.metadata.source_commit}/apps/${backend.implementation}`));
    for (const endpoint of backend.endpoints) {
      assert.ok(html.includes(formatted(endpoint.selected.requests_per_second)));
      assert.ok(html.includes(formatted(endpoint.selected.mean_response_time_ms)));
      assert.ok(html.includes(formatted(endpoint.selected.peak_memory_bytes / 1048576)));
    }
    for (const version of Object.values(source.metadata.versions[backend.implementation])) {
      assert.ok(html.includes(version));
    }
  }
  assert.ok(html.includes(source.completed_at));
  assert.ok(html.includes(source.metadata.github.run_url));
  assert.match(html, /fastest in this run/);
  assert.match(html, /lower is better/);
  assert.match(html, /higher is better/);
  assert.match(html, /not universal/);
});

test('local, smoke, partial and malformed display data never becomes a result table', async () => {
  const { viewModel } = await subject();
  const changes = [
    r => { r.official = false; }, r => { r.mode = 'smoke'; },
    r => { r.status = 'failed'; }, r => { r.schema_version = true; },
    r => { r.implementations.pop(); }, r => { r.implementations[1] = r.implementations[0]; },
    r => { r.implementations[0].endpoints.pop(); },
    r => { r.implementations[0].endpoints[0].selected.requests_per_second = NaN; },
    r => { r.implementations[0].endpoints[0].selected.mean_response_time_ms = -1; },
    r => { r.implementations[0].endpoints[0].selected.peak_memory_bytes = null; },
    r => { r.conditions.connections = false; },
    r => { r.completed_at = 'not a date'; },
    r => { r.metadata.github.run_url = 'javascript:alert(1)'; },
    r => { r.metadata.source_commit = '../../escape'; },
  ];
  for (const change of changes) {
    const source = await report();
    change(source);
    assert.throws(() => viewModel(source));
  }
  for (const invalid of [null, {}, [], 'result']) assert.throws(() => viewModel(invalid));
});

test('metadata is escaped and cannot introduce HTML or script URLs', async () => {
  const { renderReport } = await subject();
  const source = await report();
  source.metadata.runner.cpu_model = '<img src=x onerror="alert(1)"> & CPU';
  const html = renderReport(source);
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('&quot;alert(1)&quot;'));
  assert.ok(html.includes('&amp; CPU'));
});

test('404, network, HTTP and JSON failures remain honest unavailable states', async () => {
  const { loadReport } = await subject();
  const missing = await loadReport(async () => ({ status: 404, ok: false }));
  assert.equal(missing.state, 'empty');
  for (const fetcher of [
    async () => { throw new Error('offline'); },
    async () => ({ status: 500, ok: false }),
    async () => ({ status: 200, ok: true, json: async () => { throw new SyntaxError('bad JSON'); } }),
    async () => ({ status: 200, ok: true, json: async () => ({ official: false }) }),
  ]) {
    const result = await loadReport(fetcher);
    assert.equal(result.state, 'unavailable');
    assert.equal(result.html, '');
    assert.match(result.message, /unavailable/i);
    assert.ok(!result.message.includes('0.000'));
  }
  const ready = await loadReport(async () => ({ status: 200, ok: true, json: report }));
  assert.equal(ready.state, 'ready');
  assert.ok(ready.html.includes('data-result-row'));
});

test('the document is self-contained, mobile-ready and has a non-JavaScript explanation', async () => {
  let html;
  try { html = await readFile(new URL('../site/index.html', import.meta.url), 'utf8'); }
  catch { assert.fail('site/index.html must provide the accessible static shell'); }
  assert.match(html, /name="viewport"/);
  assert.match(html, /<noscript>/);
  assert.match(html, /id="results"/);
  assert.match(html, /role="status"/);
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /type="module" src="\.\/app\.mjs"/);
  assert.ok(!/<script[^>]+src="https?:/.test(html));
});
