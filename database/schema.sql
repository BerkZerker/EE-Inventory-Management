-- E-Bike Inventory Management System — Database Schema
-- All tables use CREATE TABLE IF NOT EXISTS for idempotent re-runs.

-- Products master list (one per bike model/color/size combo)
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL UNIQUE,                 -- TREK-VERVE3-BLU-M
    shopify_product_id TEXT,
    brand           TEXT NOT NULL,                        -- "Trek"
    model           TEXT NOT NULL,                        -- "Verve 3"
    color           TEXT,
    size            TEXT,
    retail_price    REAL NOT NULL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Invoice records
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_ref     TEXT NOT NULL UNIQUE,                 -- INV-2024-02-07-001
    supplier        TEXT NOT NULL,
    invoice_date    TEXT NOT NULL,
    total_amount    REAL,
    shipping_cost   REAL DEFAULT 0,
    discount        REAL DEFAULT 0,
    credit_card_fees REAL DEFAULT 0,
    tax             REAL DEFAULT 0,
    other_fees      REAL DEFAULT 0,
    file_path       TEXT,                                 -- Path to original PDF
    parsed_data     TEXT,                                 -- Raw JSON from AI parser
    status          TEXT NOT NULL DEFAULT 'pending'       -- pending | approved | rejected
                    CHECK (status IN ('pending', 'approved', 'rejected')),
    approved_by     TEXT,
    approved_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Parsed invoice line items (editable before approval)
CREATE TABLE IF NOT EXISTS invoice_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    product_id      INTEGER REFERENCES products(id),     -- NULL until matched
    description     TEXT NOT NULL,                        -- Raw text from parser
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_cost       REAL NOT NULL DEFAULT 0,
    total_cost      REAL NOT NULL DEFAULT 0,
    allocated_cost  REAL,                                 -- After shipping/discount allocation
    parsed_brand    TEXT,                                 -- Brand extracted by AI parser
    parsed_model    TEXT,                                 -- Model extracted by AI parser
    parsed_color    TEXT,                                 -- Color extracted by AI parser
    parsed_size     TEXT,                                 -- Size extracted by AI parser
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Individual bikes (one per physical unit)
CREATE TABLE IF NOT EXISTS bikes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    serial_number   TEXT NOT NULL UNIQUE,                 -- BIKE-00247
    product_id      INTEGER NOT NULL REFERENCES products(id),
    invoice_id      INTEGER REFERENCES invoices(id),
    shopify_variant_id TEXT,
    actual_cost     REAL NOT NULL DEFAULT 0,              -- What we paid for THIS bike
    date_received   TEXT NOT NULL DEFAULT (datetime('now')),
    status          TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN ('available', 'sold', 'returned', 'damaged')),
    date_sold       TEXT,
    sale_price      REAL,
    shopify_order_id TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Serial number counter (single-row table)
CREATE TABLE IF NOT EXISTS serial_counter (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    next_serial     INTEGER NOT NULL DEFAULT 1
);

-- Initialise counter if it doesn't exist
INSERT OR IGNORE INTO serial_counter (id, next_serial) VALUES (1, 1);

-- Webhook log for deduplication and audit
CREATE TABLE IF NOT EXISTS webhook_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id      TEXT NOT NULL UNIQUE,                 -- Shopify's X-Shopify-Webhook-Id
    topic           TEXT NOT NULL,                        -- e.g. orders/create
    status          TEXT NOT NULL DEFAULT 'received'
                    CHECK (status IN ('received', 'processed', 'failed')),
    payload         TEXT,                                 -- Raw JSON payload
    error           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_bikes_product ON bikes(product_id);
CREATE INDEX IF NOT EXISTS idx_bikes_status ON bikes(status);
CREATE INDEX IF NOT EXISTS idx_bikes_invoice ON bikes(invoice_id);
CREATE INDEX IF NOT EXISTS idx_bikes_serial ON bikes(serial_number);
CREATE INDEX IF NOT EXISTS idx_bikes_shopify_variant ON bikes(shopify_variant_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_webhook_log_webhook_id ON webhook_log(webhook_id);
