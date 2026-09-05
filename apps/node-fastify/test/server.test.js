import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createServer } from 'node:net';
import { promisify } from 'node:util';
import { test } from 'node:test';
import pg from 'pg';
import { startServer } from '../src/server.js';

const environment = {
  DATABASE_HOST: 'postgres', DATABASE_PORT: '5432', DATABASE_NAME: 'benchmark',
  DATABASE_USER: 'benchmark', DATABASE_PASSWORD: 'local-test-password',
};

test('startup waits for a real pool readiness query before listening', async (t) => {
  let pool;
  let releaseReadiness;
  const ready = new Promise((resolve) => { releaseReadiness = resolve; });
  t.mock.method(pg.Pool.prototype, 'query', async function (sql) {
    pool = this;
    assert.equal(sql, 'SELECT 1');
    await ready;
    return { rows: [{ '?column?': 1 }] };
  });
  let listening = false;
  const starting = startServer({ env: environment, host: '127.0.0.1', port: 0 });
  starting.then(() => { listening = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(listening, false);
  releaseReadiness();
  const app = await starting;
  t.after(() => app.close());
  assert.equal(app.server.listening, true);
  const response = await fetch(`http://127.0.0.1:${app.server.address().port}/health`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'ok' });
  await app.close();
  assert.equal(pool.ended, true);
});

test('a DB readiness failure closes the pool and rejects startup', async (t) => {
  let pool;
  t.mock.method(pg.Pool.prototype, 'query', async function () {
    pool = this;
    throw new Error('database unavailable');
  });
  await assert.rejects(startServer({ env: environment, port: 0 }), /database unavailable/);
  assert.equal(pool.ended, true);
});

test('a listen failure closes the already initialized pool', async (t) => {
  const occupied = createServer();
  await new Promise((resolve) => occupied.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => occupied.close(resolve)));
  let pool;
  t.mock.method(pg.Pool.prototype, 'query', async function () { pool = this; return { rows: [] }; });
  await assert.rejects(startServer({
    env: environment, host: '127.0.0.1', port: occupied.address().port,
  }), { code: 'EADDRINUSE' });
  assert.equal(pool.ended, true);
});

test('the production entry point exits nonzero with a sanitized startup error', async () => {
  const env = { ...process.env, DATABASE_PASSWORD: 'must-not-be-logged' };
  delete env.DATABASE_HOST;
  await assert.rejects(promisify(execFile)(process.execPath, ['src/server.js'], {
    env, timeout: 10000, cwd: new URL('..', import.meta.url),
  }), (error) => {
    assert.equal(error.code, 1);
    assert.equal(error.stdout, '');
    assert.equal(error.stderr.trim(), 'server startup failed');
    return true;
  });
});
