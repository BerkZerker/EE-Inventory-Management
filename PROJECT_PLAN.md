# E-Bike Inventory Management System - Implementation Plan

## Progress

- [x] Phase 1: Scaffolding
- [x] Phase 2: Database Layer
- [x] Phase 3: Serial Generator
- [x] Phase 4: Invoice Parser (Gemini)
- [x] Phase 5: Flask API (15 endpoints, error handling, tests)
- [ ] Phase 6: React Frontend
- [x] Phase 7: Shopify Sync (GraphQL Admin API, product sync, variant creation)
- [x] Phase 8: Barcode Generator (Code128 PNG, Avery 5160 PDF, thermal labels)
- [x] Phase 9: Webhook Listener (HMAC verification, dedup, order processing)
- [ ] Phase 10: CLI Commands
- [ ] Phase 11: Testing

## Context

Building the system described in PROJECT_SPEC.md from scratch (no code exists yet, just the spec and a git repo). This plan incorporates spec corrections and technology decisions made during review.

## Key Decisions

| Decision       | Choice                                              |
| -------------- | --------------------------------------------------- |
| Frontend       | Vite + React + TypeScript (SPA)                     |
| Backend        | Flask REST API (JSON)                               |
| AI parsing     | Google Gemini (`google-genai` SDK)                  |
| Barcode format | Code128                                             |
| Serial start   | Configurable via `STARTING_SERIAL` env var          |
| Shopify API    | GraphQL Admin API (REST is legacy as of April 2025) |

## Spec Corrections

These issues in PROJECT_SPEC.md are fixed in this plan:

1. **`google-generativeai` is EOL** (died Nov 2025). Use `google-genai>=1.62.0`. Gemini reads PDFs natively — no `pdf2image` or `Pillow` needed.
2. **Shopify REST API is legacy**. Must use GraphQL Admin API (`2025-10`). Variant limit is now 2,048 (not 100).
3. **`SELECT FOR UPDATE` doesn't work in SQLite**. Serial generator uses `BEGIN IMMEDIATE` instead.
4. **Products table PK**: Use `INTEGER PRIMARY KEY AUTOINCREMENT` with `sku` as `UNIQUE` index (not SKU as PK).
5. **Missing product creation flow**: Added `POST /api/products` and a "Create New Product" modal in the review UI.
6. **Missing webhook reliability**: Added `webhook_log` table + `/api/reconcile` endpoint.
7. **Added `invoice_items` table**: Parsed line items stored in their own table (not just a JSON blob), enabling UI editing.
8. **Bike status**: `bikes.sold BOOLEAN` replaced with `bikes.status TEXT` (`available`, `sold`, `returned`, `damaged`).

## Architecture

```text
Flask API (:5000)  <-- serves -->  React SPA (Vite dev :5173, prod: built static)
     |
     ├── /api/invoices/*        (upload, parse, review, approve)
     ├── /api/products/*        (CRUD, Shopify sync)
     ├── /api/bikes/*           (inventory queries)
     ├── /api/reports/*         (profit reporting)
     ├── /api/labels/*          (barcode PDFs)
     └── /api/reconcile         (Shopify reconciliation)

Webhook Listener (:5001)        (separate Flask process)
     └── /webhooks/orders/create
```

## Project Structure

```text
EE-Inventory-Management/
├── .gitignore
├── .env.example
├── requirements.txt
├── config.py
├── main.py                     # CLI entry point
├── database/
│   ├── __init__.py
│   ├── schema.sql
│   └── models.py               # All DB operations
├── services/
│   ├── __init__.py
│   ├── invoice_parser.py       # Gemini PDF parsing + cost allocation
│   ├── shopify_sync.py         # GraphQL variant creation + product sync
│   ├── barcode_generator.py    # Code128 labels (reportlab)
│   └── serial_generator.py     # Atomic serial generation
├── api/
│   ├── __init__.py
│   ├── app.py                  # Flask app factory
│   └── routes.py               # All API endpoints
├── frontend/                   # Vite + React + TypeScript
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts          # Proxy /api to Flask in dev
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       ├── api/client.ts       # Axios API client
│       ├── types/index.ts      # TypeScript interfaces
│       ├── components/         # Reusable UI components
│       └── pages/              # UploadPage, ReviewPage, InventoryPage, etc.
├── webhook_server.py
├── data/
│   ├── invoices/
│   └── labels/
└── tests/
```

## Implementation Phases

### Phase 1: Scaffolding

Create: `.gitignore`, `requirements.txt`, `.env.example`, `config.py`, `database/schema.sql`, directory structure with `__init__.py` files, `data/` dirs with `.gitkeep`.

**requirements.txt** (key deps):

- `flask==3.1.2`, `flask-cors==5.0.1`
- `google-genai>=1.62.0` (NOT google-generativeai)
- `python-barcode[images]==0.15.1`, `reportlab==4.2.5`
- `pydantic==2.10.6`, `python-dotenv==1.0.1`, `requests==2.32.3`

### Phase 2: Database Layer

Create `database/models.py` with all CRUD operations. Add `init-db` command to `main.py`. Key functions: product CRUD, invoice + items CRUD, bike lifecycle, webhook log, profit reporting, inventory summary.

SQLite config: WAL mode, foreign keys ON, `row_factory = sqlite3.Row`.

### Phase 3: Serial Generator

Create `services/serial_generator.py`. Uses `BEGIN IMMEDIATE` for atomic counter increment. Functions: `generate_serial_numbers(count)`, `peek_next_serial()`, `peek_next_serials(count)`.

### Phase 4: Invoice Parser (Gemini)

Create `services/invoice_parser.py`. Uses `google-genai` SDK with Pydantic structured output (`response_schema=ParsedInvoice`). Upload PDF directly via `client.files.upload()`. Includes:

- `parse_invoice_pdf(pdf_path)` — main parsing function
- `allocate_costs(items, shipping, discount)` — proportional cost allocation with rounding remainder on last item
- `match_to_catalog(item, catalog)` — fuzzy SKU matching (model + color + size)
- `parse_invoice_with_retry()` — exponential backoff

### Phase 5: Flask API

Create `api/app.py` (factory) and `api/routes.py` (Blueprint under `/api`). Key endpoints:

- `POST /api/invoices/upload` — upload PDF, parse with Gemini, save to DB
- `GET /api/invoices/:id` — get invoice with items and preview serials
- `PUT /api/invoices/:id/items/:item_id` — edit parsed line item
- `POST /api/invoices/:id/approve` — **orchestrates full pipeline**: allocate costs, generate serials, create bikes, sync to Shopify, generate labels
- `POST /api/invoices/:id/reject`
- `GET/POST /api/products` — CRUD + Shopify import
- `GET /api/bikes` — filterable bike list with pagination
- `GET /api/inventory/summary` — aggregated per-product stats
- `GET /api/reports/profit` — date-filtered profit report
- `POST /api/labels/generate` — barcode PDF generation
- `POST /api/reconcile` — Shopify reconciliation

CORS enabled for `localhost:5173` (Vite dev server). In production, Flask serves the built React app at `/`.

### Phase 6: React Frontend

Init with `npm create vite@latest -- --template react-ts`. Install `axios`, `react-router-dom`. Proxy `/api` to Flask in `vite.config.ts`.

**Pages:**

- **UploadPage** — drag-drop PDF upload, parsing spinner, redirect to review
- **InvoiceListPage** — table of invoices with status filter tabs
- **ReviewPage** (most complex) — editable line items table, SKU selector dropdown, "Create New Product" modal for unmatched items, serial preview, cost allocation display, approve/reject buttons, post-approval result with label download
- **InventoryPage** — summary cards + per-product table with expandable bike rows, serial search, status filter
- **ProductsPage** — product catalog CRUD, "Sync from Shopify" button
- **ReportPage** — date range picker, profit summary, per-product breakdown

### Phase 7: Shopify Sync

Create `services/shopify_sync.py`. All GraphQL, no REST. Key operations:

- `sync_products_from_shopify()` — paginated product import
- `create_variants_for_bikes(bikes, product)` — uses `productVariantsBulkCreate` mutation with `barcode`, `inventoryItem.cost`, `inventoryItem.sku`, `inventoryQuantities`
- `ensure_serial_option(product_id)` — add "Serial" option to product if missing
- `archive_sold_variants()` — remove variants for sold bikes (when approaching 2048 limit)
- Rate limit handling with exponential backoff on 429

### Phase 8: Barcode Generator

Create `services/barcode_generator.py`. Uses `python-barcode` (Code128) + `reportlab`. Functions:

- `generate_barcode_image(serial)` — PNG bytes
- `create_label_sheet(serials, output_path)` — Avery 5160 compatible PDF (3x10 grid)
- `create_single_label(serial)` — 2"x1" thermal printer label

### Phase 9: Webhook Listener

Create `webhook_server.py` (separate Flask process on port 5001). HMAC-SHA256 signature verification. `orders/create` handler: verify signature, deduplicate via `webhook_log`, mark bikes as sold. Always returns 200 to Shopify (errors logged, not raised).

### Phase 10: CLI Commands

Complete `main.py` with all subcommands: `init-db`, `web`, `sync-products`, `receive-invoice`, `generate-serials`, `print-labels`, `inventory`, `report`, `reconcile`, `webhook`.

### Phase 11: Testing

`pytest` with fixtures for test DB, sample products/invoices. Test suites: serial generation (concurrency), cost allocation (rounding), database CRUD, Shopify sync (mocked), webhook handling (HMAC, dedup), integration (full receive + sell flow).

## Dependency Order

```text
Phase 1 → Phase 2 → Phase 3, 4, 7, 8, 9 (parallel)
                         ↓
                     Phase 5 (needs 3 + 4)
                         ↓
                     Phase 6 (needs 5)
                         ↓
                     Phase 10 (needs all services)
                         ↓
                     Phase 11 (alongside each phase)
```

## Verification

1. `python main.py init-db` — creates `data/ebike_inventory.db` with all tables
2. `python main.py web` + `cd frontend && npm run dev` — upload a test invoice PDF, review parsed data, edit items, approve
3. Verify bikes appear in inventory dashboard with correct serial numbers and allocated costs
4. Verify barcode label PDF downloads and scans correctly
5. Verify Shopify variants are created with correct cost, SKU, and barcode (requires Shopify credentials)
6. `curl -X POST localhost:5001/webhooks/orders/create` with test payload — verify bike marked sold
7. `python main.py report --start 2024-01-01 --end 2024-12-31` — verify profit calculations
8. `pytest tests/ -v` — all tests pass
