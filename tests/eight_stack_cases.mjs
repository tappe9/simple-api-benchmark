import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const members = ['go-gin', 'go-echo', 'rust-actix', 'rust-axum', 'node-fastify', 'node-express', 'python-fastapi', 'python-flask'];
const legacyMembers = ['go-gin', 'rust-actix', 'node-fastify', 'python-fastapi'];

export async function realCohortFixtures() {
  const temporary = await mkdtemp(join(tmpdir(), 'sab-real-cohort-fixture-'));
  try {
    const source = `
import json, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_benchmark_publication import synthetic_report
from registry_fixtures import real_eight_report
legacy = synthetic_report(Path(sys.argv[1]))
print(json.dumps({'legacy': legacy, 'eight': real_eight_report(legacy)}))
`;
    return JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', source, temporary], {
      cwd: fileURLToPath(new URL('..', import.meta.url)), encoding: 'utf8',
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    }));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

export function registerEightStackTests() {
  test('real four/eight cohorts render only their own frameworks, selected runs and provenance', async () => {
    const { viewModel, renderReport, dashboardRows } = await import('../site/app.mjs');
    const { legacy, eight } = await realCohortFixtures();
    for (const [report, expected] of [[legacy, legacyMembers], [eight, members]]) {
      const model = viewModel(report);
      assert.deepEqual(model.implementations, expected);
      assert.equal(model.rows.length, expected.length * 3);
      const html = renderReport(report);
      assert.equal((html.match(/data-implementation-filter=/g) || []).length, expected.length);
      assert.equal((html.match(/data-language-filter=/g) || []).length, 4);
      assert.equal((html.match(/data-result-row/g) || []).length, expected.length * 3);
      assert.equal((html.match(/data-run-row/g) || []).length, expected.length * 9);
      assert.match(html, new RegExp(model.cohort));
      assert.match(html, /simple-api-v1/);
      assert.match(html, new RegExp(report.metadata.source_commit));
      for (const endpoint of ['/json', '/db/42', '/cpu']) {
        for (const metric of ['rps', 'mean', 'memory']) {
          const rows = dashboardRows(model, { endpoint, metric, visibleIds: expected });
          assert.equal(rows.length, expected.length);
          for (const row of rows) {
            const entry = report.implementations.find(b => b.implementation === row.id).endpoints.find(e => e.endpoint === endpoint);
            assert.equal(row.rps, entry.selected.requests_per_second);
            assert.equal(row.mean, entry.selected.mean_response_time_ms);
            assert.equal(row.memory, entry.selected.peak_memory_bytes / 1048576);
            assert.equal(row.runs.filter(run => run.selected).length, 1);
          }
        }
      }
    }
    const legacyHtml = renderReport(legacy);
    for (const id of members.filter(id => !legacyMembers.includes(id))) {
      assert.ok(!legacyHtml.includes(`data-implementation-filter="${id}"`));
    }
    assert.match(renderReport(eight), /external-readiness/);
    assert.match(renderReport(legacy), /container-healthcheck/);
  });

  test('real eight-stack display rejects incomplete identities, versions, runs and readiness provenance', async () => {
    const { viewModel } = await import('../site/app.mjs');
    const { eight } = await realCohortFixtures();
    assert.equal(viewModel(eight).rows.length, 24);
    const changes = [
      r => { r.implementations.reverse(); },
      r => { r.benchmark.cohort = 'four-stack-v1'; },
      r => { r.benchmark.cohort = 'unknown-v1'; },
      r => { delete r.metadata.source_commit; },
      r => { delete r.metadata.runner; },
      r => { delete r.metadata.api_health_policy; },
      r => { r.metadata.api_health_policy = 'unknown'; },
      r => { r.mode = 'smoke'; },
    ];
    for (let index = 0; index < members.length; index++) {
      changes.push(
        r => { r.implementations.splice(index, 1); },
        r => { r.implementations[index].implementation = 'unknown-stack'; },
        r => { r.implementations[index].implementation = members[(index + 1) % members.length]; },
        r => { r.implementations[index].endpoints.pop(); },
        r => { r.implementations[index].endpoints.reverse(); },
        r => { r.implementations[index].endpoints[0].runs.pop(); },
      );
      for (const field of Object.keys(eight.metadata.versions[members[index]])) {
        changes.push(r => { delete r.metadata.versions[members[index]][field]; });
      }
    }
    for (const change of changes) {
      const bad = structuredClone(eight);
      change(bad);
      assert.throws(() => viewModel(bad));
    }
  });

  test('schema-v2 readiness provenance is required even for a four-stack report', async () => {
    const { viewModel } = await import('../site/app.mjs');
    const { legacy } = await realCohortFixtures();
    const explicit = structuredClone(legacy);
    explicit.schema_version = 2;
    explicit.benchmark = { definition: 'simple-api-v1', cohort: 'four-stack-v1' };
    assert.throws(() => viewModel(explicit), /health|readiness|policy/i);
    explicit.metadata.api_health_policy = 'external-readiness';
    assert.equal(viewModel(explicit).apiHealthPolicy, 'external-readiness');
    legacy.metadata.api_health_policy = 'external-readiness';
    assert.throws(() => viewModel(legacy), /health|readiness|policy/i);
  });
}

export async function testEightStackBrowser(t, { cdp, evaluate, waitFor, page, historical, setReportMode }) {
  await t.test('eight-stack filters and history navigation work without padding historical reports', async () => {
    setReportMode('eight-stack');
    try {
      await cdp.send('Page.navigate', { url: page });
      await waitFor(cdp, `location.search === '' && document.querySelectorAll('[data-result-row]').length === 24`);
      assert.match(await evaluate(cdp, `document.getElementById('results').textContent`), /eight-stack-v1/);
      assert.match(await evaluate(cdp, `document.getElementById('results').textContent`), /external-readiness/);
      assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-implementation-filter]').length`), 8);
      assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-run-row]').length`), 72);
      await evaluate(cdp, `document.querySelector('[data-language-filter="Go"]').click()`);
      assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-run-details]:not([hidden])').length`), 6);
      await evaluate(cdp, `document.querySelector('[data-language-filter="Go"]').click(); document.querySelector('[data-implementation-filter="node-express"]').click()`);
      for (const endpoint of ['/json', '/db/42', '/cpu']) {
        for (const metric of ['rps', 'mean', 'memory']) {
          await evaluate(cdp, `document.querySelector('[data-endpoint="${endpoint}"]').click(); document.querySelector('[data-metric="${metric}"]').click()`);
          assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-chart]:not([hidden]) [data-chart-implementation]:not([hidden])').length`), 7);
          assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-run-details]:not([hidden])').length`), 7);
        }
      }
      await evaluate(cdp, `document.querySelector('[data-run-details]:not([hidden])').open = true`);
      assert.equal(await evaluate(cdp, `document.querySelector('[data-run-details]:not([hidden])').querySelectorAll('[data-selected-run="true"]').length`), 1);
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
      assert.equal(await evaluate(cdp, `document.documentElement.scrollWidth <= window.innerWidth`), true);
      await evaluate(cdp, `document.querySelector('[data-history-select]').value = ${JSON.stringify(historical.id)}; document.querySelector('[data-history-select]').dispatchEvent(new Event('change', { bubbles: true }))`);
      await waitFor(cdp, `location.search === ${JSON.stringify(`?run=${historical.id}`)} && document.querySelectorAll('[data-result-row]').length === 12`);
      assert.equal(await evaluate(cdp, `document.querySelector('[data-implementation-filter="go-echo"]') === null`), true);
      assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-implementation-filter]').length`), 4);
      assert.equal(await evaluate(cdp, `document.querySelector('[data-result-json]').href`), new URL(historical.path, page).href);
      assert.match(await evaluate(cdp, `document.querySelector('[data-history-view]').textContent`), /does not infer regressions/i);
      await evaluate(cdp, `document.querySelector('[data-history-select]').value = ''; document.querySelector('[data-history-select]').dispatchEvent(new Event('change', { bubbles: true }))`);
      await waitFor(cdp, `location.search === '' && document.querySelectorAll('[data-result-row]').length === 24`);
      assert.equal(await evaluate(cdp, `document.querySelector('[data-result-json]').href`), `${page}results/latest.json`);
    } finally {
      setReportMode('valid');
    }
  });
}
