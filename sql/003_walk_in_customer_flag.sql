ALTER TABLE customers ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE customers SET is_system = TRUE WHERE name = 'Consumidor Final';
