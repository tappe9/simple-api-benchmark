import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { checkHealth } from '../src/healthcheck.js';

async function serve(t, body) {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(body);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return `http://127.0.0.1:${server.address().port}/health`;
}

test('healthcheck accepts the exact readiness contract', async (t) => {
  await checkHealth(await serve(t, '{"status":"ok"}'));
});

test('healthcheck rejects extra fields', async (t) => {
  await assert.rejects(checkHealth(await serve(t, '{"status":"ok","extra":true}')), /healthcheck failed/);
});
