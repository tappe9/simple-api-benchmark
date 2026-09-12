export async function checkHealth(url = 'http://127.0.0.1:8080/health', timeout = 2000) {
  const response = await fetch(url, { signal: AbortSignal.timeout(timeout), redirect: 'error' });
  const contentType = response.headers.get('content-type')?.split(';')[0].trim();
  if (response.status !== 200 || contentType !== 'application/json') {
    await response.body?.cancel();
    throw new Error('healthcheck failed');
  }
  const body = await response.json();
  if (body === null || body.status !== 'ok' || Object.keys(body).length !== 1) {
    throw new Error('healthcheck failed');
  }
}

if (import.meta.main) {
  checkHealth().catch(() => { process.exitCode = 1; });
}
