import express from 'express';

const SELECT_ITEM = 'SELECT id, name, price FROM items WHERE id = $1';

export function fibonacci(n) {
  if (n < 2) return n;
  return fibonacci(n - 1) + fibonacci(n - 2);
}

function parseId(value) {
  if (!/^[+-]?[0-9]+$/.test(value)) return null;
  const id = BigInt(value);
  if (id < -9223372036854775808n || id > 9223372036854775807n) return null;
  return id.toString();
}

export function buildApp(pool) {
  const app = express();
  app.disable('x-powered-by');

  app.get('/health', (_request, response) => response.json({ status: 'ok' }));
  app.get('/json', (_request, response) => response.json({
    message: 'Hello, World!', items: [1, 2, 3, 4, 5],
  }));
  app.get('/db/:id', async (request, response) => {
    const id = parseId(request.params.id);
    if (id === null) return response.status(400).json({ error: 'invalid id' });
    try {
      const { rows } = await pool.query(SELECT_ITEM, [id]);
      if (rows.length === 0) return response.status(404).json({ error: 'not found' });
      const row = rows[0];
      const numericId = Number(row.id);
      return response.json({
        id: Number.isSafeInteger(numericId) ? numericId : JSON.rawJSON(row.id),
        name: row.name,
        price: row.price,
      });
    } catch {
      return response.status(500).json({ error: 'internal server error' });
    }
  });
  app.get('/cpu', (_request, response) => response.json({ input: 30, result: fibonacci(30) }));
  return app;
}
