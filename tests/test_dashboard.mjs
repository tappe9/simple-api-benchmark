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

test('view model preserves all three observed runs and identifies the selected whole run', async () => {
  const { viewModel } = await subject();
  const model = viewModel(await report());
  const row = model.rows.find(candidate => candidate.id === 'go-gin' && candidate.endpoint === '/json');

  assert.equal(row.runs.length, 3);
  assert.deepEqual(row.runs.map(run => run.run), [1, 2, 3]);
  assert.equal(row.runs.filter(run => run.selected).length, 1);
  assert.equal(row.runs.find(run => run.selected).run, row.selectedRun);
  assert.equal(row.rps, row.runs.find(run => run.selected).rps);
  assert.equal(row.mean, row.runs.find(run => run.selected).mean);
  assert.equal(row.memory, row.runs.find(run => run.selected).memory);
  assert.equal(row.rpsMin, Math.min(...row.runs.map(run => run.rps)));
  assert.equal(row.rpsMax, Math.max(...row.runs.map(run => run.rps)));
});

test('selected whole-run equality is semantic and does not depend on JSON key order', async () => {
  const { viewModel } = await subject();
  const source = await report();
  const entry = source.implementations[0].endpoints[0];
  entry.selected = Object.fromEntries(Object.entries(entry.selected).reverse());
  const model = viewModel(source);
  const row = model.rows.find(candidate => candidate.id === source.implementations[0].implementation && candidate.endpoint === entry.endpoint);
  assert.equal(row.selectedRun, entry.selected.run);
});

test('observed throughput range handles zero spread, ties, and wide spread deterministically', async () => {
  const { viewModel } = await subject();

  const zero = await report();
  const zeroEntry = zero.implementations[0].endpoints[0];
  for (const run of zeroEntry.runs) run.requests_per_second = 100;
  zeroEntry.selected.requests_per_second = 100;
  let row = viewModel(zero).rows.find(candidate => candidate.id === zero.implementations[0].implementation && candidate.endpoint === zeroEntry.endpoint);
  assert.equal(row.rpsMin, 100);
  assert.equal(row.rpsMax, 100);

  const wide = await report();
  const wideEntry = wide.implementations[0].endpoints[0];
  [1, 100, 10000].forEach((value, index) => { wideEntry.runs[index].requests_per_second = value; });
  const selectedRun = wideEntry.selected.run;
  wideEntry.selected.requests_per_second = wideEntry.runs[selectedRun - 1].requests_per_second;
  row = viewModel(wide).rows.find(candidate => candidate.id === wide.implementations[0].implementation && candidate.endpoint === wideEntry.endpoint);
  assert.equal(row.rpsMin, 1);
  assert.equal(row.rpsMax, 10000);
});

test('run validation fails closed on incomplete or inconsistent observed runs', async () => {
  const { viewModel } = await subject();
  const missingRun = await report();
  missingRun.implementations[0].endpoints[0].runs.pop();
  assert.throws(() => viewModel(missingRun), /three measured runs/i);

  const duplicateRun = await report();
  duplicateRun.implementations[0].endpoints[0].runs[2].run = 2;
  assert.throws(() => viewModel(duplicateRun), /run numbers/i);

  const mismatchedSelected = await report();
  mismatchedSelected.implementations[0].endpoints[0].selected.requests_per_second += 1;
  assert.throws(() => viewModel(mismatchedSelected), /selected run/i);
});

test('rendered results expose observed spread and expandable three-run details without statistical claims', async () => {
  const { renderReport } = await subject();
  const html = renderReport(await report());
  assert.match(html, /Observed range/);
  assert.match(html, /Selected run/);
  assert.match(html, /Three measured runs/);
  assert.match(html, /descriptive observations/i);
  assert.match(html, /not a confidence interval/i);
  assert.equal((html.match(/data-run-details/g) || []).length, 12);
  assert.equal((html.match(/data-run-row/g) || []).length, 36);
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
