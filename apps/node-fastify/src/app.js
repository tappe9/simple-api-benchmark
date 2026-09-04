import Fastify from 'fastify';

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
  const app = Fastify();
  app.addHook('onClose', async () => { await pool.end(); });

  app.get('/health', async () => ({ status: 'ok' }));
  app.get('/json', async () => ({ message: 'Hello, World!', items: [1, 2, 3, 4, 5] }));
  app.get('/db/:id', async (request, reply) => {
    const id = parseId(request.params.id);
    if (id === null) return reply.code(400).send({ error: 'invalid id' });

    try {
      const { rows } = await pool.query(SELECT_ITEM, [id]);
      if (rows.length === 0) return reply.code(404).send({ error: 'not found' });
      const row = rows[0];
      const numericId = Number(row.id);
      // pg returns BIGINT as text. Preserve exact numeric JSON outside Number's safe range.
      return {
        id: Number.isSafeInteger(numericId) ? numericId : JSON.rawJSON(row.id),
        name: row.name,
        price: row.price,
      };
    } catch {
      return reply.code(500).send({ error: 'internal server error' });
    }
  });
  app.get('/cpu', async () => ({ input: 30, result: fibonacci(30) }));
  return app;
}
