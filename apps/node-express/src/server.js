import { createServer } from 'node:http';
import { buildApp } from './app.js';
import { createPool } from './database.js';

function listen(server, host, port) {
  return new Promise((resolve, reject) => {
    const failed = (error) => reject(error);
    server.once('error', failed);
    server.listen(port, host, () => {
      server.off('error', failed);
      resolve();
    });
  });
}

function closeHttp(server) {
  if (!server.listening) return Promise.resolve();
  return new Promise((resolve, reject) => {
    server.close((error) => { if (error) reject(error); else resolve(); });
  });
}

export async function startServer({ env = process.env, host = '0.0.0.0', port = 8080 } = {}) {
  const pool = createPool(env);
  let server;
  try {
    await pool.query('SELECT 1');
    server = createServer(buildApp(pool));
    await listen(server, host, port);
  } catch (error) {
    try {
      if (server?.listening) await closeHttp(server);
    } finally {
      await pool.end();
    }
    throw error;
  }
  let closed = false;
  return {
    server,
    pool,
    async close() {
      if (closed) return;
      closed = true;
      try {
        await closeHttp(server);
      } finally {
        await pool.end();
      }
    },
  };
}

async function main() {
  const instance = await startServer();
  let stopping = false;
  async function stop() {
    if (stopping) return;
    stopping = true;
    const deadline = setTimeout(() => { process.exit(1); }, 5000);
    deadline.unref();
    try {
      await instance.close();
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
