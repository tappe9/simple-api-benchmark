# Node.js / Express implementation

`apps/node-express` is the second Node.js stack in Simple API Benchmark. It uses Express 5.2.1 with the same Node.js 24.20.0 runtime, `pg` 8.23.0 driver, SQL, fixture, pool maximum of 10, one server process, 1 CPU and 512 MiB limits as the Fastify baseline.

This is a complete-stack comparison, not an isolated claim about Express routing speed. Express and Fastify have different HTTP/framework internals even though the runtime, PostgreSQL driver and benchmark contract are held constant where practical.

The implementation provides `/health`, `/json`, `/db/:id`, and `/cpu`, preserves signed PostgreSQL BIGINT values as JSON numbers, uses direct recursive Fibonacci(30), runs as the non-root `node` user, and closes the HTTP server before the database pool during SIGINT/SIGTERM shutdown.

Express is registered and exercised by normal CI, including unit tests, real-container acceptance and the shared API contract. The official benchmark remains `four-stack-v1`; adding this implementation does not publish a partial expanded-cohort result.
