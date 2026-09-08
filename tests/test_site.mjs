import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
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

function resultLink(html) {
  const match = html.match(/<a href="([^"]+)">Inspect the result JSON<\/a>/);
  assert.ok(match, 'the rendered result must expose its JSON link');
  return match[1];
}

test('result JSON link follows the displayed artifact at root and project URLs', async () => {
  const { renderReport } = await subject();
  const source = await report();
  const html = renderReport(source);
  const href = resultLink(html);
  assert.equal(href, './results/latest.json');
  for (const page of ['https://example.test/', 'https://example.test/simple-api-benchmark/',
    'https://example.test/simple-api-benchmark/index.html']) {
    assert.equal(new URL(href, page).href, new URL('./results/latest.json', page).href);
  }
  assert.ok(html.includes(`/blob/${source.metadata.source_commit}/docs/METHODOLOGY.md`));
  assert.ok(!html.includes(`/blob/${source.metadata.source_commit}/results/latest.json`));
});

// Synthetic publications live only in temporary repositories, never in public results/.
for (const previous of ['missing', 'older']) {
  test(`built publication resolves its JSON when the source result is ${previous}`, async t => {
    const root = await mkdtemp(join(tmpdir(), 'sab-site-publication-'));
    t.after(() => rm(root, { recursive: true, force: true }));
    const repo = fileURLToPath(new URL('../', import.meta.url));
    const git = (...args) => execFileSync('git', args, {
      cwd: root, encoding: 'utf8', timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'],
    }).trim();
    const commit = message => git('-c', 'user.name=Site tests', '-c',
      'user.email=site-tests@example.invalid', '-c', 'commit.gpgsign=false',
      'commit', '--quiet', '-m', message);
    const build = () => execFileSync(process.env.PYTHON || 'python3', ['-c',
      'import sys; from pathlib import Path; from benchmark.site import build; build(Path(sys.argv[1]))',
      root], { cwd: repo, timeout: 15000, stdio: ['ignore', 'pipe', 'pipe'] });
    await cp(new URL('../site/', import.meta.url), join(root, 'site'), { recursive: true });
    await mkdir(join(root, 'results'));
    const latest = join(root, 'results/latest.json');
    const older = await report();
    older.metadata.github.run_id = '101';
    older.metadata.github.run_url = 'https://github.com/tappe9/simple-api-benchmark/actions/runs/101';
    older.started_at = '2026-01-01T00:00:00+00:00';
    older.completed_at = '2026-01-01T01:00:00+00:00';
    for (const backend of older.implementations) {
      for (const endpoint of backend.endpoints) {
        for (const run of [...endpoint.runs, endpoint.selected]) run.peak_memory_bytes = 1048576;
      }
    }
    if (previous === 'older') await writeFile(latest, JSON.stringify(older));
    git('init', '--quiet');
    git('add', '.');
    commit('Measured source fixture');
    const sourceSha = git('rev-parse', 'HEAD');
    if (previous === 'missing') {
      assert.throws(() => git('show', `${sourceSha}:results/latest.json`));
    } else {
      assert.deepEqual(JSON.parse(git('show', `${sourceSha}:results/latest.json`)), older);
    }
    build(); // Also validate the older report, or build the honest empty shell.
    const published = await report();
    published.started_at = '2026-01-02T00:00:00+00:00';
    published.completed_at = '2026-01-02T01:00:00+00:00';
    published.metadata.source_commit = sourceSha;
    published.metadata.source_tree = git('rev-parse', 'HEAD^{tree}');
    Object.assign(published.metadata.github, {
      source_commit: sourceSha, workflow_sha: sourceSha, run_id: '202',
      run_url: 'https://github.com/tappe9/simple-api-benchmark/actions/runs/202',
    });
    const raw = JSON.stringify(published) + '\n';
    await writeFile(latest, raw);
    git('add', 'results/latest.json');
    commit('Later publication fixture');
    assert.equal(git('rev-parse', 'HEAD^'), sourceSha);
    assert.notEqual(git('rev-parse', 'HEAD'), sourceSha);
    build();
    const output = join(root, '.cache/site');
    const prefix = '/simple-api-benchmark/';
    const files = new Map(await Promise.all(['index.html', 'app.mjs', 'style.css',
      'results/latest.json'].map(async name => [prefix + name, await readFile(join(output, name))])));
    const server = createServer((request, response) => {
      const path = request.url === prefix ? prefix + 'index.html' : request.url;
      const body = files.get(path);
      response.writeHead(body ? 200 : 404, { 'Content-Type': path.endsWith('.json')
        ? 'application/json' : path.endsWith('.mjs') ? 'text/javascript' : 'text/html' });
      response.end(body || 'Not found');
    });
    t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const page = `http://127.0.0.1:${server.address().port}${prefix}`;
    const get = (url, options = {}) => fetch(url, { ...options, signal: AbortSignal.timeout(5000) });
    const shell = await get(page);
    assert.equal(shell.status, 200);
    assert.match(await shell.text(), /type="module" src="\.\/app\.mjs"/);
    const { loadReport, viewModel } = await import(pathToFileURL(join(output, 'app.mjs')).href);
    const loaded = [];
    const state = await loadReport((url, options) => {
      loaded.push(new URL(url, page).href);
      return get(new URL(url, page), options);
    });
    assert.equal(state.state, 'ready');
    const target = new URL(resultLink(state.html), page);
    // Fail before any external request: neither GitHub nor a live past file is a fixture.
    assert.equal(target.href, new URL('./results/latest.json', page).href);
    assert.deepEqual(loaded, [target.href]);
    const response = await get(target);
    assert.equal(response.status, 200);
    const linkedRaw = await response.text();
    assert.equal(linkedRaw, raw);
    assert.equal(await readFile(latest, 'utf8'), raw);
    const linked = JSON.parse(linkedRaw);
    assert.deepEqual(linked, published);
    assert.notEqual(linked.metadata.github.run_id, older.metadata.github.run_id);
    assert.ok(state.html.includes(`href="${linked.metadata.github.run_url}"`));
    assert.ok(state.html.includes(`<time datetime="${linked.completed_at}">${linked.completed_at}</time>`));
    assert.ok(state.html.includes(`/blob/${sourceSha}/docs/METHODOLOGY.md`));
    const model = viewModel(linked);
    assert.equal(model.source, sourceSha);
    assert.equal(model.completedAt, published.completed_at);
    assert.equal(model.rows.length, 12);
    for (const backend of linked.implementations) {
      assert.ok(state.html.includes(`/tree/${sourceSha}/apps/${backend.implementation}`));
      for (const endpoint of backend.endpoints) {
        const row = model.rows.find(r => r.id === backend.implementation && r.endpoint === endpoint.endpoint);
        assert.equal(row.rps, endpoint.selected.requests_per_second);
        assert.equal(row.mean, endpoint.selected.mean_response_time_ms);
        assert.equal(row.memory, endpoint.selected.peak_memory_bytes / 1048576);
        assert.ok(state.html.includes(`<td>${formatted(row.rps)}</td><td>${formatted(row.mean)}</td><td>${formatted(row.memory)}</td>`));
      }
    }
  });
}
