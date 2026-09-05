import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { checkHealth } from '../src/healthcheck.js';

async function endpoint(t, status, contentType, body) {
  const server = createServer((_request, response) => {
    response.writeHead(status, { 'Content-Type': contentType });
    response.end(body);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => { server.closeAllConnections(); server.close(resolve); }));
  return `http://127.0.0.1:${server.address().port}/health`;
}

test('the production health check accepts the exact contract', async (t) => {
  await checkHealth(await endpoint(t, 200, 'application/json; charset=utf-8', '{"status":"ok"}'));
});

test('the health check rejects wrong status, type, payload, or malformed JSON', async (t) => {
  for (const values of [
    [503, 'application/json', '{"status":"ok"}'],
    [200, 'text/plain', '{"status":"ok"}'],
    [200, 'application/json', '{"status":"down"}'],
    [200, 'application/json', '{"status":"ok","extra":1}'],
    [200, 'application/json', 'not json'],
    [200, 'application/json', 'null'],
  ]) {
    await assert.rejects(checkHealth(await endpoint(t, ...values)));
  }
});

test('the health check bounds a stalled response', async (t) => {
  const server = createServer(() => {});
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => { server.closeAllConnections(); server.close(resolve); }));
  await assert.rejects(checkHealth(`http://127.0.0.1:${server.address().port}/health`, 50));
});
