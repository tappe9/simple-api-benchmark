import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createServer as createNetServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = dirname(fileURLToPath(new URL('../Makefile', import.meta.url)));
const python = process.env.PYTHON || 'python3';

function chromeBinary() {
  if (process.env.CHROME_BIN) return process.env.CHROME_BIN;
  for (const candidate of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']) {
    try {
      return execFileSync('which', [candidate], { encoding: 'utf8' }).trim();
    } catch {}
  }
  throw new Error('a Chromium-based browser is required for the Pages browser test');
}

async function freePort() {
  const server = createNetServer();
  await new Promise((resolve, reject) => server.listen(0, '127.0.0.1', error => error ? reject(error) : resolve()));
  const { port } = server.address();
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function pollJson(url, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return response.json();
    } catch (error) {
      lastError = error;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw lastError || new Error(`timed out waiting for ${url}`);
}

async function connectCdp(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let id = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
  });
  return {
    close: () => socket.close(),
    send(method, params = {}) {
      const requestId = ++id;
      return new Promise((resolve, reject) => {
        pending.set(requestId, { resolve, reject });
        socket.send(JSON.stringify({ id: requestId, method, params }));
      });
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'browser evaluation failed');
  return result.result.value;
}

async function waitFor(cdp, expression, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluate(cdp, expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`timed out waiting for browser condition: ${expression}`);
}

test('Pages dashboard works in a real browser under the project subpath', { timeout: 30000 }, async t => {
  execFileSync(python, ['-m', 'benchmark.site'], { cwd: root, stdio: 'pipe' });
  const output = join(root, '.cache', 'site');
  let reportMode = 'valid';
  const prefix = '/simple-api-benchmark/';
  const server = createServer(async (request, response) => {
    try {
      let path = request.url.split('?')[0];
      if (path === prefix) path += 'index.html';
      if (!path.startsWith(prefix)) {
        response.writeHead(404).end('Not found');
        return;
      }
      const relative = path.slice(prefix.length);
      if (relative === 'results/latest.json' && reportMode === 'malformed') {
        response.writeHead(200, { 'Content-Type': 'application/json' }).end('{bad json');
        return;
      }
      const body = await readFile(join(output, relative));
      const type = extname(relative) === '.json' ? 'application/json'
        : extname(relative) === '.mjs' ? 'text/javascript'
          : extname(relative) === '.css' ? 'text/css' : 'text/html';
      response.writeHead(200, { 'Content-Type': type }).end(body);
    } catch {
      response.writeHead(404).end('Not found');
    }
  });
  await new Promise((resolve, reject) => server.listen(0, '127.0.0.1', error => error ? reject(error) : resolve()));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const page = `http://127.0.0.1:${server.address().port}${prefix}`;

  const debugPort = await freePort();
  const profile = await mkdtemp(join(tmpdir(), 'sab-chrome-'));
  const browser = spawn(chromeBinary(), [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, page,
  ], { stdio: 'ignore' });
  t.after(async () => {
    browser.kill('SIGKILL');
    await rm(profile, { recursive: true, force: true });
  });

  const targets = await pollJson(`http://127.0.0.1:${debugPort}/json/list`);
  const target = targets.find(entry => entry.type === 'page');
  assert.ok(target?.webSocketDebuggerUrl, 'browser page target must be available');
  const cdp = await connectCdp(target.webSocketDebuggerUrl);
  t.after(() => cdp.close());
  await cdp.send('Runtime.enable');
  await waitFor(cdp, `document.querySelectorAll('[data-result-row]').length === 12`);

  assert.equal(await evaluate(cdp, `location.pathname`), prefix);
  assert.equal(await evaluate(cdp, `document.documentElement.dataset.theme`), 'light');
  assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-chart]:not([hidden])').length`), 1);
  assert.equal(
    await evaluate(cdp, `document.querySelector('.limitation a[href="./results/latest.json"]').href`),
    `${page}results/latest.json`,
  );

  await evaluate(cdp, `document.querySelector('[data-endpoint="/cpu"]').click(); document.querySelector('[data-metric="mean"]').click();`);
  assert.equal(await evaluate(cdp, `document.querySelector('[data-endpoint="/cpu"]').getAttribute('aria-selected')`), 'true');
  assert.equal(await evaluate(cdp, `document.querySelector('[data-metric="mean"]').getAttribute('aria-pressed')`), 'true');

  await evaluate(cdp, `document.querySelector('[data-implementation-filter]').click();`);
  assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-chart]:not([hidden]) [data-chart-implementation]:not([hidden])').length`), 3);
  await evaluate(cdp, `document.querySelector('[data-implementation-filter]').click(); document.querySelector('[data-language-filter="Go"]').click();`);
  assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-chart]:not([hidden]) [data-chart-implementation]:not([hidden])').length`), 3);
  await evaluate(cdp, `document.querySelector('[data-language-filter="Go"]').click();`);
  assert.equal(await evaluate(cdp, `document.querySelectorAll('[data-chart]:not([hidden]) [data-chart-implementation]:not([hidden])').length`), 4);

  await evaluate(cdp, `document.getElementById('theme-toggle').click();`);
  assert.equal(await evaluate(cdp, `document.documentElement.dataset.theme`), 'dark');
  assert.equal(await evaluate(cdp, `document.querySelector('[data-endpoint="/cpu"]').getAttribute('aria-selected')`), 'true');
  assert.equal(await evaluate(cdp, `document.querySelector('[data-metric="mean"]').getAttribute('aria-pressed')`), 'true');

  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  assert.equal(await evaluate(cdp, `document.documentElement.scrollWidth <= window.innerWidth`), true);

  await evaluate(cdp, `(() => {
    const current = document.querySelector('[data-endpoint="/cpu"]');
    current.focus();
    current.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  })()`);
  assert.equal(await evaluate(cdp, `document.activeElement.dataset.endpoint`), '/json');
  assert.equal(await evaluate(cdp, `document.querySelector('[data-endpoint="/json"]').getAttribute('aria-selected')`), 'true');

  reportMode = 'malformed';
  await cdp.send('Page.reload', { ignoreCache: true });
  await waitFor(cdp, `document.getElementById('results')?.getAttribute('role') === 'status'`);
  assert.match(await evaluate(cdp, `document.getElementById('results').textContent`), /temporarily unavailable/i);
  assert.equal(await evaluate(cdp, `document.getElementById('results').textContent.includes('0.000')`), false);
});
