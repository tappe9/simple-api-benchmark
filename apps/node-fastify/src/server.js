import { buildApp } from './app.js';
import { createPool } from './database.js';

export async function startServer({ env = process.env, host = '0.0.0.0', port = 8080 } = {}) {
  const pool = createPool(env);
  const app = buildApp(pool);
  try {
    await pool.query('SELECT 1');
    await app.listen({ host, port });
    return app;
  } catch (error) {
    await app.close();
    throw error;
  }
}

async function main() {
  const app = await startServer();
  let stopping = false;
  async function stop() {
    if (stopping) return;
    stopping = true;
    const deadline = setTimeout(() => { process.exit(1); }, 5000);
    deadline.unref();
    try {
      await app.close();
    } catch {
      console.error('server shutdown failed');
      process.exitCode = 1;
    } finally {
      clearTimeout(deadline);
    }
  }
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
}

if (import.meta.main) {
  main().catch(() => {
    console.error('server startup failed');
    process.exitCode = 1;
  });
}
