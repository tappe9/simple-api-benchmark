import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildApp, fibonacci } from '../src/app.js';

function createApp(t, query = async () => { throw new Error('unexpected DB query'); }) {
  const app = buildApp({ query, end: async () => {} });
  t.after(() => app.close());
  return app;
}

function assertResponse(response, status, body) {
  assert.equal(response.statusCode, status);
  assert.match(response.headers['content-type'], /^application\/json(?:;|$)/);
  assert.deepEqual(response.json(), body);
}

test('/health returns the readiness contract without querying the DB', async (t) => {
  assertResponse(await createApp(t).inject('/health'), 200, { status: 'ok' });
});

test('/json sends a fresh native object through normal serialization', async (t) => {
  const app = createApp(t);
  const payloads = [];
  app.addHook('preSerialization', async (_request, _reply, payload) => {
    assert.equal(typeof payload, 'object');
    payloads.push(payload);
    return payload;
  });
  for (let i = 0; i < 2; i += 1) {
    assertResponse(await app.inject('/json'), 200, {
      message: 'Hello, World!', items: [1, 2, 3, 4, 5],
    });
  }
  assert.notEqual(payloads[0], payloads[1]);
});

test('/db/42 uses a bound parameter and serializes the actual returned row', async (t) => {
  const calls = [];
  let row = { id: '42', name: 'Item 42', price: 4200 };
  const app = createApp(t, async (text, values) => {
    calls.push({ text, values });
    return { rows: [row], rowCount: 1, command: 'SELECT', fields: [] };
  });
  assertResponse(await app.inject('/db/42'), 200, { id: 42, name: 'Item 42', price: 4200 });
  row = { id: '42', name: 'Changed item', price: 7 };
  assertResponse(await app.inject('/db/42'), 200, { id: 42, name: 'Changed item', price: 7 });
  assert.deepEqual(calls, [
    { text: 'SELECT id, name, price FROM items WHERE id = $1', values: ['42'] },
    { text: 'SELECT id, name, price FROM items WHERE id = $1', values: ['42'] },
  ]);
});

test('unknown integer IDs return 404 after querying the DB', async (t) => {
  const calls = [];
  const app = createApp(t, async (_text, values) => {
    calls.push(values);
    return { rows: [], rowCount: 0, command: 'SELECT', fields: [] };
  });
  for (const id of ['999', '0', '-1']) {
    assertResponse(await app.inject(`/db/${id}`), 404, { error: 'not found' });
  }
  assert.deepEqual(calls, [['999'], ['0'], ['-1']]);
});

test('invalid IDs return 400 without executing any query', async (t) => {
  let calls = 0;
  const app = createApp(t, async () => { calls += 1; throw new Error('must not query'); });
  for (const id of [
    'abc', '42junk', '1.0', '1e2', '0x2a', 'NaN', '+', '--1', ' 42', '42 ',
    '42 OR 1=1', '9223372036854775808', '-9223372036854775809',
  ]) {
    assertResponse(await app.inject(`/db/${encodeURIComponent(id)}`), 400, { error: 'invalid id' });
  }
  assert.equal(calls, 0);
});

test('signed decimal IDs are normalized without losing BIGINT precision', async (t) => {
  const calls = [];
  const app = createApp(t, async (_text, values) => {
    calls.push(values);
    return { rows: [{ id: values[0], name: 'Boundary item', price: 1 }], rowCount: 1 };
  });
  for (const [input, expected] of [
    ['+00042', '42'], ['9007199254740993', '9007199254740993'],
    ['9223372036854775807', '9223372036854775807'],
    ['-9223372036854775808', '-9223372036854775808'],
  ]) {
    const response = await app.inject(`/db/${encodeURIComponent(input)}`);
    assert.equal(response.statusCode, 200);
    assert.match(response.body, new RegExp(`"id":${expected}(?:,|})`));
    assert.deepEqual(calls.at(-1), [expected]);
  }
});

test('unexpected DB errors return a sanitized JSON 500', async (t) => {
  const app = createApp(t, async () => {
    throw new Error('postgres://private:secret@internal SELECT * FROM hidden\nstack trace');
  });
  assertResponse(await app.inject('/db/42'), 500, { error: 'internal server error' });
});

test('/cpu returns Fibonacci(30) on repeated requests', async (t) => {
  const app = createApp(t);
  for (let i = 0; i < 3; i += 1) {
    assertResponse(await app.inject('/cpu'), 200, { input: 30, result: 832040 });
  }
});

test('Fibonacci follows its base cases and recurrence', () => {
  for (const [input, expected] of [[0, 0], [1, 1], [2, 1], [3, 2], [10, 55]]) {
    assert.equal(fibonacci(input), expected);
  }
});

test('closing the app releases its owned pool exactly once', async () => {
  let closed = 0;
  const app = buildApp({ query: async () => {}, end: async () => { closed += 1; } });
  await app.ready();
  await app.close();
  await app.close();
  assert.equal(closed, 1);
});
