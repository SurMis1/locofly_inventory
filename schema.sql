
-- ==============
-- Core tables
-- ==============

-- Main inventory table (you already have this; IF NOT EXISTS is safe)
CREATE TABLE IF NOT EXISTS inventory (
    id          SERIAL PRIMARY KEY,
    item_name   TEXT        NOT NULL,
    quantity    INT         NOT NULL,
    location_id INT         NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One item can appear only once per location
-- If this fails, you still have duplicates; see note below.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_indexes
        WHERE  schemaname = 'public'
        AND    indexname  = 'inventory_loc_item_uidx'
    ) THEN
        CREATE UNIQUE INDEX inventory_loc_item_uidx
        ON inventory(location_id, item_name);
    END IF;
END$$;


-- Barcode master: barcode -> item name
CREATE TABLE IF NOT EXISTS barcode_master (
    barcode   TEXT PRIMARY KEY,
    item_name TEXT NOT NULL
);

-- ==============
-- Change log
-- ==============

CREATE TABLE IF NOT EXISTS inventory_log (
    id            BIGSERIAL PRIMARY KEY,
    location_id   INT         NOT NULL,
    item_name     TEXT        NOT NULL,
    old_quantity  INT,
    new_quantity  INT         NOT NULL,
    action        VARCHAR(20) NOT NULL,  -- 'insert', 'update', 'delete'
    action_time   TIMESTAMPTZ NOT NULL DEFAULT now()
);
