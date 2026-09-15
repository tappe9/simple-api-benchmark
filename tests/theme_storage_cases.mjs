import assert from 'node:assert/strict';

// Runs in the page before any application module, never in an isolated world.
function instrumentThemeStorage(mode) {
  const state = { mode, failures: [], errors: [] };
  window.__themeStorageTest = state;
  window.addEventListener('error', event => state.errors.push(String(event.error || event.message)));
  window.addEventListener('unhandledrejection', event => state.errors.push(String(event.reason)));
  const fail = (operation, name) => {
    state.failures.push(operation);
    throw new DOMException(`Instrumented theme storage ${operation} failure`, name);
  };

  if (mode === 'getter-throws') {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get: () => fail('getter', 'SecurityError'),
    });
    return;
  }
  if (mode === 'missing-storage') {
    Object.defineProperty(window, 'localStorage', { configurable: true, value: undefined });
    return;
  }

  // Use the real Storage implementation for every operation not under test.
  const storage = window.localStorage;
  storage.removeItem('sab-theme');
  if (mode === 'saved-dark' || mode === 'write-throws') storage.setItem('sab-theme', 'dark');
  if (mode === 'saved-light') storage.setItem('sab-theme', 'light');
  if (mode === 'invalid-preference') storage.setItem('sab-theme', 'DARK');
  const getItem = Storage.prototype.getItem;
  const setItem = Storage.prototype.setItem;
  if (mode === 'read-throws' || mode === 'read-and-write-throw') {
    Storage.prototype.getItem = function (key) {
      if (key === 'sab-theme') return fail('read', 'SecurityError');
      return Reflect.apply(getItem, this, [key]);
    };
  }
  if (mode === 'write-throws' || mode === 'read-and-write-throw') {
    Storage.prototype.setItem = function (key, value) {
      if (key === 'sab-theme') return fail('write', 'QuotaExceededError');
      return Reflect.apply(setItem, this, [key, value]);
    };
  }
}

async function assertTheme(cdp, evaluate, theme) {
  assert.deepEqual(await evaluate(cdp, `(() => {
    const button = document.getElementById('theme-toggle');
    return {
      theme: document.documentElement.dataset.theme,
      pressed: button.getAttribute('aria-pressed'),
      text: button.textContent,
    };
  })()`), {
    theme,
    pressed: String(theme === 'dark'),
    text: theme === 'dark' ? 'Use light theme' : 'Use dark theme',
  });
}

export async function testThemeStorage(t, {
  cdp, evaluate, waitFor, page, latestReport, historical, historicalReport, setReportMode,
}) {
  await cdp.send('Page.enable');
  const latestRows = latestReport.implementations.flatMap(implementation => implementation.endpoints).length;
  const historicalRows = historicalReport.implementations.flatMap(implementation => implementation.endpoints).length;
  const cases = [
    { mode: 'getter-throws', initial: 'light', failures: ['getter'] },
    { mode: 'read-throws', initial: 'light', failures: ['read'] },
    { mode: 'write-throws', initial: 'dark', failures: ['write'] },
    { mode: 'read-and-write-throw', initial: 'light', failures: ['read', 'write'] },
    { mode: 'missing-storage', initial: 'light', failures: [] },
    { mode: 'missing-preference', initial: 'light', failures: [] },
    { mode: 'invalid-preference', initial: 'light', failures: [] },
    { mode: 'saved-light', initial: 'light', failures: [] },
    { mode: 'saved-dark', initial: 'dark', failures: [] },
  ];

  async function withStorage(mode, run) {
    await cdp.send('Page.navigate', { url: 'about:blank' });
    await waitFor(cdp, `location.href === 'about:blank'`);
    const script = await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
      source: `(${instrumentThemeStorage.toString()})(${JSON.stringify(mode)});`,
    });
    try {
      await run();
    } finally {
      await cdp.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: script.identifier });
    }
  }

  async function ready(url, rows) {
    await cdp.send('Page.navigate', { url });
    // Also stop on an escaped boot error so RED identifies the real failure,
    // rather than reporting only a generic timeout with no diagnostic.
    await waitFor(cdp, `location.href === ${JSON.stringify(url)} &&
      window.__themeStorageTest &&
      (window.__themeStorageTest.errors.length > 0 || document.querySelectorAll('[data-result-row]').length === ${rows})`);
    assert.deepEqual(await evaluate(cdp, `window.__themeStorageTest.errors`), [], 'optional storage must not reject boot');
    assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-result-row]').length`), rows);
  }

  for (const { mode, initial, failures } of cases) {
    await t.test(`theme storage: ${mode} preserves real results and controls`, async () => {
      setReportMode('valid');
      await withStorage(mode, async () => {
        await ready(page, latestRows);
        await assertTheme(cdp, evaluate, initial);
        assert.equal(await evaluate(cdp, `document.querySelector('[data-result-json]').href`), `${page}results/latest.json`);

        // Exercise history navigation as well as initial/latest loading.
        await evaluate(cdp, `document.querySelector('[data-history-select]').value = ${JSON.stringify(historical.id)};
          document.querySelector('[data-history-select]').dispatchEvent(new Event('change', { bubbles: true }));`);
        await waitFor(cdp, `location.search === ${JSON.stringify(`?run=${historical.id}`)} &&
          document.querySelector('[data-history-select]')?.value === ${JSON.stringify(historical.id)} &&
          document.querySelectorAll('[data-result-row]').length === ${historicalRows}`);
        await assertTheme(cdp, evaluate, initial);
        assert.equal(await evaluate(cdp, `document.querySelector('[data-result-json]').href`), new URL(historical.path, page).href);
        assert.equal(await evaluate(cdp, `document.getElementById('results').textContent.includes(${JSON.stringify(historicalReport.metadata.github.source_commit)})`), true);

        await evaluate(cdp, `(() => {
          const endpoint = document.querySelector('[data-endpoint="/db/42"]');
          endpoint.focus();
          endpoint.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
          document.querySelector('[data-metric="mean"]').click();
          document.querySelector('[data-implementation-filter]').click();
          document.querySelector('[data-language-filter="Python"]').click();
          document.querySelector('[data-run-details]:not([hidden])').open = true;
        })()`);
        assert.equal(await evaluate(cdp, `document.activeElement.dataset.endpoint`), '/cpu');
        assert.equal(await evaluate(cdp, `document.querySelector('[data-endpoint="/cpu"]').getAttribute('aria-selected')`), 'true');
        assert.equal(await evaluate(cdp, `document.querySelector('[data-metric="mean"]').getAttribute('aria-pressed')`), 'true');
        assert.equal(await evaluate(cdp, `document.querySelector('[data-implementation-filter]').checked`), false);
        assert.equal(await evaluate(cdp, `document.querySelector('[data-language-filter="Python"]').checked`), false);
        const before = await evaluate(cdp, `document.getElementById('results').innerHTML`);
        await evaluate(cdp, `document.getElementById('theme-toggle').focus();`);

        // Real keyboard activation must still work, including when writes fail.
        for (const theme of [initial === 'dark' ? 'light' : 'dark', initial]) {
          await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
          await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
          await assertTheme(cdp, evaluate, theme);
          assert.equal(await evaluate(cdp, `document.activeElement.id`), 'theme-toggle');
          assert.equal(await evaluate(cdp, `document.getElementById('results').innerHTML`), before, 'theme changes must not rerender or reset the selected result');
        }
        assert.equal(await evaluate(cdp, `location.search`), `?run=${historical.id}`);
        assert.deepEqual(await evaluate(cdp, `window.__themeStorageTest.errors`), [], 'optional storage must not escape through event handlers');
        assert.deepEqual(await evaluate(cdp, `[...new Set(window.__themeStorageTest.failures)].sort()`), [...failures].sort(), 'the intended failure path must actually execute');
        if (mode === 'saved-light' || mode === 'saved-dark') {
          assert.equal(await evaluate(cdp, `localStorage.getItem('sab-theme')`), initial);
        }
      });
    });
  }

  for (const reportMode of ['malformed', 'unverified', 'server-error']) {
    await t.test(`theme storage denial does not hide ${reportMode} report failures`, async () => {
      setReportMode(reportMode);
      try {
        await withStorage('getter-throws', async () => {
          await cdp.send('Page.navigate', { url: page });
          await waitFor(cdp, `location.href === ${JSON.stringify(page)} && window.__themeStorageTest &&
            (window.__themeStorageTest.errors.length > 0 || document.getElementById('results')?.getAttribute('role') === 'status')`);
          assert.deepEqual(await evaluate(cdp, `window.__themeStorageTest.errors`), []);
          const message = await evaluate(cdp, `document.getElementById('results').textContent`);
          assert.match(message, /temporarily unavailable|could not be verified/i);
          assert.doesNotMatch(message, /0\.000/);
          assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-result-row]').length`), 0);
          await evaluate(cdp, `document.getElementById('theme-toggle').click();`);
          await assertTheme(cdp, evaluate, 'dark');
          assert.equal(await evaluate(cdp, `document.getElementById('results').textContent`), message);
          assert.deepEqual(await evaluate(cdp, `window.__themeStorageTest.errors`), []);
          assert.ok(await evaluate(cdp, `window.__themeStorageTest.failures.includes('getter')`));
        });
      } finally {
        setReportMode('valid');
      }
    });
  }
}
