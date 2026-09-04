# API Contract

All v0.1 implementations must provide the endpoints in this document.

## General rules

- Listen on port `8080` inside the container.
- Use HTTP/1.1.
- Return the documented status code.
- Return JSON endpoints with a content type beginning with `application/json`.
- Serialize native language values; do not return a prebuilt JSON byte string.
- Do not cache benchmark responses.
- Do not add framework-specific fields.
- JSON object key order and insignificant whitespace are not compared.

## `GET /health`

Used only for readiness checks.

Response:

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "status": "ok"
}
```

## `GET /json`

Returns a small JSON object.

Response:

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "message": "Hello, World!",
  "items": [1, 2, 3, 4, 5]
}
```

Each request must construct or serialize the response through the normal framework path. Returning the JSON example as a fixed string is not allowed.

## `GET /db/{id}`

Reads one PostgreSQL row by primary key and returns it as JSON.

Example request:

```http
GET /db/42
```

Required schema:

```sql
CREATE TABLE items (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL
);
```

Required fixture:

```sql
INSERT INTO items (id, name, price)
VALUES (42, 'Item 42', 4200);
```

Required logical query:

```sql
SELECT id, name, price
FROM items
WHERE id = $1;
```

Placeholder syntax may differ by driver, but the query must be parameterized.

Successful response:

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "id": 42,
  "name": "Item 42",
  "price": 4200
}
```

Unknown ID:

```http
HTTP/1.1 404 Not Found
Content-Type: application/json
```

```json
{
  "error": "not found"
}
```

An ID that cannot be parsed as an integer returns:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
```

```json
{
  "error": "invalid id"
}
```

## `GET /cpu`

Calculates Fibonacci(30) for every request.

Definition:

```text
fib(0) = 0
fib(1) = 1
fib(n) = fib(n - 1) + fib(n - 2)
```

The implementation must use direct recursion without memoization, caching, a lookup table, or a precomputed answer.

Response:

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "input": 30,
  "result": 832040
}
```

This test measures the complete API stack plus language runtime and compiler behavior. It is not a framework-only test.

## Contract verification

Before benchmarking, automated tests verify:

1. every endpoint is reachable;
2. status codes match;
3. JSON values and types match;
4. content types match;
5. the DB endpoint reads the fixture row;
6. missing and invalid DB IDs use the documented errors;
7. repeated CPU requests return the same value.

A failed implementation is reported clearly and excluded from performance results.
