import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { buildApp, fibonacci } from '../src/app.js';

async function start(t, query = async () => { throw new Error('unexpected DB query'); }) {
  const server = createServer(buildApp({ query }));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return `http://127.0.0.1:${server.address().port}`;
}

async function request(base, path) {
  const response = await fetch(base + path);
  return { status: response.status, type: response.headers.get('content-type'), text: await response.text() };
}

test('health and json return the shared JSON contracts', async (t) => {
  const base = await start(t);
  let result = await request(base, '/health');
  assert.equal(result.status, 200);
  assert.match(result.type, /^application\/json/);
  assert.deepEqual(JSON.parse(result.text), { status: 'ok' });
  result = await request(base, '/json');
  assert.deepEqual(JSON.parse(result.text), { message: 'Hello, World!', items: [1, 2, 3, 4, 5] });
});

test('db uses a bound parameter and preserves exact signed BIGINT JSON numbers', async (t) => {
  const calls = [];
  const base = await start(t, async (text, values) => {
    calls.push({ text, values });
    return { rows: [{ id: values[0], name: 'Item', price: 7 }] };
  });
  for (const id of ['42', '9007199254740993', '9223372036854775807', '-9223372036854775808']) {
    const result = await request(base, `/db/${encodeURIComponent(id)}`);
    assert.equal(result.status, 200);
    assert.match(result.text, new RegExp(`"id":${id}(?:,|})`));
  }
  assert.equal(calls[0].text, 'SELECT id, name, price FROM items WHERE id = $1');
  assert.deepEqual(calls.map(({ values }) => values), [['42'], ['9007199254740993'], ['9223372036854775807'], ['-9223372036854775808']]);
});

test('invalid ids avoid the DB and missing rows return 404', async (t) => {
  let calls = 0;
  const base = await start(t, async () => { calls += 1; return { rows: [] }; });
  let result = await request(base, '/db/abc');
  assert.equal(result.status, 400);
  assert.deepEqual(JSON.parse(result.text), { error: 'invalid id' });
  assert.equal(calls, 0);
  result = await request(base, '/db/999');
  assert.equal(result.status, 404);
  assert.equal(calls, 1);
});

test('db errors are sanitized', async (t) => {
  const base = await start(t, async () => { throw new Error('postgres://secret internal stack'); });
  const result = await request(base, '/db/42');
  assert.equal(result.status, 500);
  assert.deepEqual(JSON.parse(result.text), { error: 'internal server error' });
  assert.doesNotMatch(result.text, /secret|stack/);
});

test('cpu computes Fibonacci(30)', async (t) => {
  const base = await start(t);
  for (let index = 0; index < 2; index += 1) {
    assert.deepEqual(JSON.parse((await request(base, '/cpu')).text), { input: 30, result: 832040 });
  }
  assert.equal(fibonacci(10), 55);
});
