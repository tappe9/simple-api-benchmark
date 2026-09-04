import pg from 'pg';

export function createPool(env = process.env) {
  for (const key of [
    'DATABASE_HOST', 'DATABASE_PORT', 'DATABASE_NAME', 'DATABASE_USER', 'DATABASE_PASSWORD',
  ]) {
    if (!env[key]) throw new Error(`required environment variable ${key} is empty`);
  }
  const port = Number(env.DATABASE_PORT);
  if (!/^[0-9]+$/.test(env.DATABASE_PORT) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('DATABASE_PORT must be an integer from 1 to 65535');
  }
  const pool = new pg.Pool({
    host: env.DATABASE_HOST,
    port,
    database: env.DATABASE_NAME,
    user: env.DATABASE_USER,
    password: env.DATABASE_PASSWORD,
    max: 10,
    connectionTimeoutMillis: 5000,
    ssl: false,
  });
  pool.on('error', () => { console.error('database connection error'); });
  return pool;
}
