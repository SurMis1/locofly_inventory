
DROP TABLE IF EXISTS inventory;

CREATE TABLE inventory (
    id SERIAL PRIMARY KEY,
    location_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity FLOAT,
    updated_at TIMESTAMP,
    UNIQUE(location_id, item_name)
);
