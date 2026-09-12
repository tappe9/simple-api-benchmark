import assert from 'node:assert/strict';
import { test } from 'node:test';
import pg from 'pg';
import { createPool } from '../src/database.js';

const environment = {
  DATABASE_HOST: 'postgres', DATABASE_PORT: '5432', DATABASE_NAME: 'benchmark',
  DATABASE_USER: 'benchmark', DATABASE_PASSWORD: 'local-test-password',
};

test('the real pg pool uses all shared settings and a maximum of ten connections', async () => {
  const pool = createPool(environment);
  try {
    assert.ok(pool instanceof pg.Pool);
    assert.equal(pool.options.max, 10);
    assert.equal(pool.options.host, 'postgres');
    assert.equal(pool.options.port, 5432);
    assert.equal(pool.options.database, 'benchmark');
    assert.equal(pool.options.user, 'benchmark');
    assert.equal(pool.options.password, 'local-test-password');
    assert.equal(pool.options.ssl, false);
    assert.equal(pool.options.connectionTimeoutMillis, 5000);
  } finally {
    await pool.end();
  }
  assert.equal(pool.ended, true);
});

test('every DATABASE setting is required, including nonempty values', () => {
  for (const key of Object.keys(environment)) {
    for (const value of [undefined, '']) {
      assert.throws(() => createPool({ ...environment, [key]: value }), new RegExp(key));
    }
  }
});

test('invalid ports fail before connection and do not expose their value', () => {
  for (const port of ['0', '65536', '5432junk', '-1', '1.5', 'secret-port']) {
    assert.throws(() => createPool({ ...environment, DATABASE_PORT: port }), {
      message: 'DATABASE_PORT must be an integer from 1 to 65535',
    });
  }
});

test('idle pool errors are handled without leaking connection details', async (t) => {
  const log = t.mock.method(console, 'error', () => {});
  const pool = createPool(environment);
  t.after(() => pool.end());
  assert.doesNotThrow(() => pool.emit('error', new Error('password=secret; private-host')));
  assert.equal(log.mock.callCount(), 1);
  assert.deepEqual(log.mock.calls[0].arguments, ['database connection error']);
});
