import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const reportPath = new URL('../results/latest.json', import.meta.url);
const report = async () => JSON.parse(await readFile(reportPath, 'utf8'));

async function subject() {
  return import('../site/app.mjs');
}

test('dashboard rows support all three metrics with deterministic sorting and filtering', async () => {
  const { viewModel, dashboardRows } = await subject();
  const model = viewModel(await report());

  const throughput = dashboardRows(model, {
    endpoint: '/json', metric: 'rps', visibleIds: ['rust-actix', 'go-gin'],
  });
  assert.deepEqual(throughput.map(row => row.id), [...throughput]
    .sort((a, b) => b.rps - a.rps || model.implementations.indexOf(a.id) - model.implementations.indexOf(b.id))
    .map(row => row.id));
  assert.ok(throughput.every(row => row.endpoint === '/json'));
  assert.ok(throughput.every(row => row.percent >= 0 && row.percent <= 100));

  const latency = dashboardRows(model, {
    endpoint: '/db/42', metric: 'mean', visibleIds: model.implementations,
  });
  assert.deepEqual(latency.map(row => row.id), [...latency]
    .sort((a, b) => a.mean - b.mean || model.implementations.indexOf(a.id) - model.implementations.indexOf(b.id))
    .map(row => row.id));

  const memory = dashboardRows(model, {
    endpoint: '/cpu', metric: 'memory', visibleIds: model.implementations,
  });
  assert.deepEqual(memory.map(row => row.id), [...memory]
    .sort((a, b) => a.memory - b.memory || model.implementations.indexOf(a.id) - model.implementations.indexOf(b.id))
    .map(row => row.id));
});

test('dashboard rows handle exact ties and zero latency without inventing values', async () => {
  const { viewModel, dashboardRows } = await subject();
  const model = viewModel(await report());
  const rows = model.rows.filter(row => row.endpoint === '/json');
  rows.forEach((row, index) => {
    row.mean = index < 2 ? 0 : 1;
    row.rps = 10;
  });
  const latency = dashboardRows(model, {
    endpoint: '/json', metric: 'mean', visibleIds: model.implementations,
  });
  assert.deepEqual(latency.map(row => row.mean), [0, 0, 1, 1]);
  assert.deepEqual(latency.map(row => row.best), [true, true, false, false]);
  assert.ok(latency.every(row => Number.isFinite(row.percent)));

  assert.throws(() => dashboardRows(model, {
    endpoint: '/missing', metric: 'rps', visibleIds: model.implementations,
  }));
  assert.throws(() => dashboardRows(model, {
    endpoint: '/json', metric: 'score', visibleIds: model.implementations,
  }));
  assert.throws(() => dashboardRows(model, {
    endpoint: '/json', metric: 'rps', visibleIds: ['unknown-stack'],
  }));
});

test('rendered results expose accessible dashboard controls while keeping the full verified table', async () => {
  const { renderReport } = await subject();
  const html = renderReport(await report());
  assert.match(html, /data-dashboard/);
  assert.match(html, /role="tablist"/);
  assert.equal((html.match(/data-endpoint=/g) || []).length, 3);
  assert.equal((html.match(/data-metric=/g) || []).length, 3);
  assert.equal((html.match(/data-language-filter=/g) || []).length, 4);
  assert.equal((html.match(/data-implementation-filter=/g) || []).length, 4);
  assert.match(html, /Requests\/s/);
  assert.match(html, /Mean response/);
  assert.match(html, /Observed peak memory/);
  assert.match(html, /higher is better/i);
  assert.match(html, /lower is better/i);
  assert.equal((html.match(/data-result-row/g) || []).length, 12);
});

test('the static shell provides an explicit theme toggle and theme CSS is user-selectable', async () => {
  const [html, css] = await Promise.all([
    readFile(new URL('../site/index.html', import.meta.url), 'utf8'),
    readFile(new URL('../site/style.css', import.meta.url), 'utf8'),
  ]);
  assert.match(html, /id="theme-toggle"/);
  assert.match(html, /aria-pressed="false"/);
  assert.match(css, /:root\[data-theme="dark"\]/);
  assert.match(css, /:root\[data-theme="light"\]/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /@media \(max-width: 760px\)/);
});
