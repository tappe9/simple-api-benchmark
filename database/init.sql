CREATE TABLE items (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL
);

INSERT INTO items (id, name, price)
VALUES (42, 'Item 42', 4200);
