# E-Bike Inventory Management System - Technical Specification

## 1. System Overview

A custom inventory management system that bridges invoice processing with Shopify POS, enabling per-unit cost tracking and serialized inventory for an e-bike retail store.

### Goals

- Parse supplier invoices to extract bike models, quantities, and costs
- Generate unique serial numbers (BIKE-##### format, incrementing)
- Create Shopify variants per physical bike with accurate cost data
- Enable barcode scanning at POS with zero-friction checkout
- Track profits with penny-accurate cost-of-goods-sold
- Maintain audit trail of all bikes received and sold

### Non-Goals (for MVP)

- Online store variant consolidation (future phase)
- Service/repair ticket tracking
- Accessory/parts inventory (use standard Shopify)
- Multi-location support

## 2. Architecture

```text

┌─────────────────┐
│ Invoice PDF │
└────────┬────────┘
│
▼
┌─────────────────────────────┐
│ Invoice Parser Service │
│ - PDF extraction │
│ - AI parsing (Gemini/Claude)│
│ - Data validation │
└────────┬────────────────────┘
│
▼
┌─────────────────────────────┐
│ Approval UI (Web) │
│ - Review parsed data │
│ - Edit if needed │
│ - Approve/reject │
└────────┬────────────────────┘
│
▼
┌─────────────────────────────┐
│ Core Database (SQLite) │
│ - Bikes table │
│ - Products table │
│ - Invoices table │
└────────┬────────────────────┘
│
├──────────────────┬──────────────────┐
▼ ▼ ▼
┌────────────────┐ ┌──────────────┐ ┌──────────────┐
│ Shopify Sync │ │ Barcode Gen │ │ Webhook │
│ - Create vars │ │ - Label PDF │ │ Listener │
│ - Set costs │ │ │ │ - Mark sold │
└────────────────┘ └──────────────┘ └──────────────┘

```

## 3. Database Schema

### SQLite Database: `ebike_inventory.db`

```sql
-- Products master list (one per bike model)
CREATE TABLE products (
    sku TEXT PRIMARY KEY,                -- TREK-VERVE-3-BLU-M
    shopify_product_id TEXT NOT NULL,
    shopify_variant_id TEXT,             -- Base variant (optional)
    model_name TEXT NOT NULL,            -- "Trek Verve 3"
    color TEXT,                          -- "Blue"
    size TEXT,                           -- "Medium"
    retail_price REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual bikes (one per physical unit)
CREATE TABLE bikes (
    serial_number TEXT PRIMARY KEY,      -- BIKE-00247
    sku TEXT NOT NULL,                   -- FK to products.sku
    shopify_variant_id TEXT,             -- Specific variant for this unit
    actual_cost REAL NOT NULL,           -- What we paid for THIS bike
    invoice_ref TEXT NOT NULL,           -- INV-2024-02-07-001
    date_received DATE NOT NULL,
    sold BOOLEAN DEFAULT FALSE,
    date_sold TIMESTAMP,
    sale_price REAL,
    shopify_order_id TEXT,
    notes TEXT,                          -- Keys location, charger ID, etc
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sku) REFERENCES products(sku)
);

-- Invoice records
CREATE TABLE invoices (
    invoice_ref TEXT PRIMARY KEY,        -- INV-2024-02-07-001
    supplier TEXT NOT NULL,
    invoice_date DATE NOT NULL,
    total_amount REAL,
    shipping_cost REAL,
    file_path TEXT,                      -- Path to original PDF
    parsed_data TEXT,                    -- JSON blob of parsed data
    approved BOOLEAN DEFAULT FALSE,
    approved_by TEXT,
    approved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Serial number counter
CREATE TABLE serial_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    next_serial INTEGER NOT NULL DEFAULT 1
);

-- Initialize counter
INSERT INTO serial_counter (id, next_serial) VALUES (1, 1);

-- Indexes
CREATE INDEX idx_bikes_sku ON bikes(sku);
CREATE INDEX idx_bikes_sold ON bikes(sold);
CREATE INDEX idx_bikes_invoice ON bikes(invoice_ref);
CREATE INDEX idx_bikes_shopify_variant ON bikes(shopify_variant_id);
```

## 4. Invoice Parser Service

### Component: `invoice_parser.py`

**Dependencies:**

- `pdf2image` - Convert PDF to images
- `google-generativeai` or `anthropic` - AI parsing
- `python-dotenv` - Environment variables
- `Pillow` - Image processing

**Core Functions:**

```python
def extract_text_from_pdf(pdf_path: str) -> list[str]:
    """
    Convert PDF pages to images and extract text.
    Returns list of image paths or base64 encoded images.
    """
    pass

def parse_invoice_with_ai(images: list, product_catalog: list) -> dict:
    """
    Send invoice images to AI API with structured prompt.

    Returns:
    {
        "supplier": "Trek Bicycles",
        "invoice_number": "INV-123456",
        "invoice_date": "2024-02-07",
        "items": [
            {
                "model": "Trek Verve 3",
                "color": "Blue",
                "size": "Medium",
                "quantity": 3,
                "unit_cost": 847.32,
                "total_cost": 2541.96
            }
        ],
        "shipping_cost": 125.00,
        "total": 2666.96
    }
    """
    pass

def match_to_catalog(parsed_item: dict, catalog: list) -> str:
    """
    Match parsed bike description to existing product SKU.
    Uses fuzzy matching on model/color/size.

    Returns SKU or None if no match.
    """
    pass

def allocate_costs(items: list, shipping_cost: float) -> list:
    """
    Allocate shipping and any discounts proportionally across items.

    Returns items with 'allocated_cost' field added.
    """
    pass
```

### AI Parsing Prompt Template

```python
INVOICE_PARSING_PROMPT = """
You are parsing a bicycle supplier invoice. Extract the following information:

1. Supplier name
2. Invoice number
3. Invoice date
4. Line items with:
   - Product model/name
   - Color (if specified)
   - Size (if specified)
   - Quantity
   - Unit price
   - Line total
5. Shipping cost (if separate)
6. Total amount

Known product catalog for matching:
{product_catalog}

Return ONLY valid JSON in this exact format:
{{
    "supplier": "string",
    "invoice_number": "string",
    "invoice_date": "YYYY-MM-DD",
    "items": [
        {{
            "model": "string",
            "color": "string or null",
            "size": "string or null",
            "quantity": number,
            "unit_cost": number,
            "total_cost": number
        }}
    ],
    "shipping_cost": number,
    "total": number
}}

Invoice image is provided. Parse it now.
"""
```

## 5. Shopify Integration

### Component: `shopify_sync.py`

**Dependencies:**

- `shopify_python_api` or `requests` for REST API
- `python-dotenv` for credentials

**Configuration:**

```python
# .env file
SHOPIFY_STORE_URL=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx
SHOPIFY_API_VERSION=2024-01
```

**Core Functions:**

```python
def get_product_by_sku(sku: str) -> dict:
    """
    Find Shopify product by SKU.
    Returns product object with variants.
    """
    pass

def create_variant_for_serial(
    product_id: str,
    serial_number: str,
    sku: str,
    cost: float,
    price: float
) -> str:
    """
    Create new variant for individual bike.

    Variant configuration:
    - Title: "Serial #{serial_number}"
    - SKU: {serial_number} (e.g., BIKE-00247)
    - Barcode: {serial_number}
    - Price: {price}
    - Cost: {cost}
    - Inventory: 1
    - Track inventory: true

    Returns variant_id
    """
    pass

def update_variant_cost(variant_id: str, cost: float):
    """
    Update the cost field on a variant.
    Uses inventoryItem API.
    """
    pass

def batch_create_variants(items: list[dict]) -> list[str]:
    """
    Create multiple variants efficiently.
    Uses GraphQL for better performance.

    items format:
    [
        {
            "product_id": "123",
            "serial": "BIKE-00247",
            "sku": "TREK-VERVE-3-BLU-M",
            "cost": 847.32,
            "price": 1299.99
        }
    ]

    Returns list of variant_ids
    """
    pass
```

### Shopify API Reference

**REST API - Create Variant:**

```text
POST /admin/api/2024-01/products/{product_id}/variants.json

{
  "variant": {
    "option1": "Serial #00247",
    "price": "1299.99",
    "sku": "BIKE-00247",
    "barcode": "BIKE-00247",
    "inventory_quantity": 1,
    "inventory_management": "shopify"
  }
}
```

**Update Inventory Item Cost:**

```text
PUT /admin/api/2024-01/inventory_items/{inventory_item_id}.json

{
  "inventory_item": {
    "cost": "847.32"
  }
}
```

**Get variant's inventory_item_id:**

```text
GET /admin/api/2024-01/variants/{variant_id}.json
// Response includes inventory_item_id
```

## 6. Barcode Generation

### Component: `barcode_generator.py`

**Dependencies:**

- `python-barcode` - Generate barcode images
- `reportlab` - Generate PDF labels

**Core Functions:**

```python
def generate_barcode_image(serial: str, format: str = 'code128') -> bytes:
    """
    Generate barcode image for serial number.
    Returns PNG bytes.
    """
    pass

def create_label_sheet(serials: list[str], output_path: str):
    """
    Create printable PDF sheet with multiple barcode labels.

    Label format (Avery 5160 compatible):
    ┌────────────────────┐
    │   BIKE-00247       │
    │   ▄▄▄ ▄ ▄▄ ▄▄     │
    │   ▄ ▄▄▄▄▄▄ ▄▄     │
    │                    │
    │ Trek Verve 3 Blue M│
    └────────────────────┘

    30 labels per sheet (3 columns × 10 rows)
    """
    pass

def print_single_label(serial: str, model_name: str) -> bytes:
    """
    Generate single 2"×1" label for thermal printer.
    """
    pass
```

## 7. Webhook Listener

### Component: `webhook_server.py`

**Dependencies:**

- `flask` - Web server
- `hmac` - Verify Shopify signatures

**Endpoints:**

```python
@app.route('/webhooks/orders/create', methods=['POST'])
def handle_order_created():
    """
    Triggered when order is completed in Shopify POS.

    1. Verify Shopify HMAC signature
    2. Extract line items with SKUs
    3. Find serials in database
    4. Mark as sold with order details
    5. Log transaction
    """
    pass

@app.route('/webhooks/inventory/update', methods=['POST'])
def handle_inventory_update():
    """
    Optional: Track manual inventory adjustments.
    """
    pass
```

**Webhook Configuration in Shopify:**

```text
Topic: orders/create
URL: https://your-domain.com/webhooks/orders/create
Format: JSON
```

**Signature Verification:**

```python
def verify_shopify_webhook(data: bytes, hmac_header: str) -> bool:
    """
    Verify webhook came from Shopify.
    """
    secret = os.getenv('SHOPIFY_WEBHOOK_SECRET')
    computed_hmac = base64.b64encode(
        hmac.new(
            secret.encode('utf-8'),
            data,
            hashlib.sha256
        ).digest()
    )
    return hmac.compare_digest(computed_hmac, hmac_header.encode('utf-8'))
```

## 8. Approval Web UI

### Component: `web_ui/` (Flask app)

**Pages:**

1. **Upload Invoice** (`/upload`)
   - Drag-drop PDF upload
   - Trigger parsing
   - Show loading spinner

2. **Review Parsed Data** (`/review/{invoice_id}`)

   ```text
   ┌────────────────────────────────────────┐
   │ Invoice: INV-2024-02-07-001            │
   │ Supplier: Trek Bicycles                │
   │ Date: Feb 7, 2024                      │
   │                                        │
   │ Items:                                 │
   │ ┌────────────────────────────────────┐ │
   │ │ Trek Verve 3 - Blue - Medium       │ │
   │ │ Quantity: 3                        │ │
   │ │ Unit Cost: $847.32                 │ │
   │ │ [Edit] [Remove]                    │ │
   │ └────────────────────────────────────┘ │
   │                                        │
   │ Next Serials: BIKE-00247, 00248, 00249│
   │                                        │
   │ [Approve & Create] [Reject]            │
   └────────────────────────────────────────┘
   ```

3. **Inventory Dashboard** (`/inventory`)
   - View all bikes (filterable by sold/available)
   - Search by serial
   - Manual entry option

**Frontend:**

- Simple HTML/CSS (no framework needed)
- HTMX for interactivity (optional)
- Or vanilla JavaScript

## 9. Complete Workflow Implementation

### Receiving Workflow

```python
# main.py - CLI orchestration

def receive_shipment(invoice_pdf_path: str):
    """
    Complete receiving workflow.
    """
    # 1. Parse invoice
    print("Parsing invoice...")
    images = extract_text_from_pdf(invoice_pdf_path)
    catalog = load_product_catalog()
    parsed = parse_invoice_with_ai(images, catalog)

    # 2. Save invoice record
    invoice_ref = save_invoice(parsed, invoice_pdf_path)

    # 3. Launch approval UI
    print(f"Review at: http://localhost:5000/review/{invoice_ref}")
    # (or auto-approve for CLI mode)

    # 4. On approval:
    approved_items = get_approved_items(invoice_ref)

    # 5. Generate serials
    serials = generate_serial_numbers(count=sum(item['quantity'] for item in approved_items))

    # 6. Create bike records
    bikes = []
    serial_idx = 0
    for item in approved_items:
        for _ in range(item['quantity']):
            bike = {
                'serial_number': serials[serial_idx],
                'sku': item['sku'],
                'actual_cost': item['allocated_cost'],
                'invoice_ref': invoice_ref,
                'date_received': datetime.now()
            }
            bikes.append(bike)
            serial_idx += 1

    save_bikes_to_db(bikes)

    # 7. Sync to Shopify
    print("Creating Shopify variants...")
    shopify_items = []
    for bike in bikes:
        product = get_product_by_sku(bike['sku'])
        variant_id = create_variant_for_serial(
            product_id=product['id'],
            serial_number=bike['serial_number'],
            sku=bike['sku'],
            cost=bike['actual_cost'],
            price=product['retail_price']
        )
        update_bike_shopify_variant(bike['serial_number'], variant_id)

    # 8. Generate barcode labels
    print("Generating barcodes...")
    label_path = f"labels/{invoice_ref}.pdf"
    create_label_sheet(serials, label_path)
    print(f"Labels ready: {label_path}")

    print(f"✓ Received {len(bikes)} bikes")
```

### Selling Workflow (Automatic)

```python
# webhook_server.py

@app.route('/webhooks/orders/create', methods=['POST'])
def handle_order_created():
    # Verify webhook
    if not verify_shopify_webhook(request.data, request.headers.get('X-Shopify-Hmac-SHA256')):
        return 'Unauthorized', 401

    order = request.json

    # Process each line item
    for item in order['line_items']:
        sku = item['sku']

        # Check if this is a bike serial
        if sku and sku.startswith('BIKE-'):
            mark_bike_sold(
                serial_number=sku,
                date_sold=order['created_at'],
                sale_price=item['price'],
                shopify_order_id=order['id']
            )

            log_sale(sku, order['id'])

    return 'OK', 200
```

## 10. Tech Stack

### Backend

- **Language**: Python 3.11+
- **Database**: SQLite (via `sqlite3` stdlib)
- **Web Framework**: Flask
- **AI SDK**: `google-generativeai` or `anthropic`

### Dependencies (`requirements.txt`)

```text
flask==3.0.0
python-dotenv==1.0.0
requests==2.31.0
pdf2image==1.16.3
Pillow==10.1.0
python-barcode==0.15.1
reportlab==4.0.7
google-generativeai==0.3.2  # or anthropic==0.7.0
shopify-python-api==12.3.0  # optional, can use requests
```

### System Requirements

- Python 3.11+
- Poppler (for pdf2image): `brew install poppler` or `apt-get install poppler-utils`
- 50MB disk space (database + labels)

## 11. Project Structure

```text
ebike-inventory/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
│
├── main.py                 # CLI entry point
├── config.py               # Configuration loader
│
├── database/
│   ├── __init__.py
│   ├── schema.sql
│   ├── models.py           # Database operations
│   └── migrations/
│
├── services/
│   ├── __init__.py
│   ├── invoice_parser.py
│   ├── shopify_sync.py
│   ├── barcode_generator.py
│   └── serial_generator.py
│
├── web_ui/
│   ├── __init__.py
│   ├── app.py              # Flask application
│   ├── routes.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── upload.html
│   │   ├── review.html
│   │   └── inventory.html
│   └── static/
│       ├── style.css
│       └── app.js
│
├── webhook_server.py       # Separate webhook listener
│
├── data/
│   ├── ebike_inventory.db  # SQLite database
│   ├── invoices/           # Uploaded PDFs
│   └── labels/             # Generated barcode PDFs
│
└── tests/
    ├── test_parser.py
    ├── test_shopify.py
    └── test_integration.py
```

## 12. Configuration

### `.env` file

```bash
# Shopify
SHOPIFY_STORE_URL=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxx
SHOPIFY_API_VERSION=2024-01
SHOPIFY_WEBHOOK_SECRET=your_webhook_secret

# AI Service (choose one)
GOOGLE_AI_API_KEY=xxxxx
# or
ANTHROPIC_API_KEY=xxxxx

# App
DATABASE_PATH=data/ebike_inventory.db
INVOICE_UPLOAD_DIR=data/invoices
LABEL_OUTPUT_DIR=data/labels

# Webhook Server
WEBHOOK_PORT=5001
WEBHOOK_HOST=0.0.0.0
```

## 13. CLI Commands

```bash
# Initialize database
python main.py init-db

# Load product catalog from Shopify
python main.py sync-products

# Process new invoice
python main.py receive-invoice data/invoices/trek-invoice-2024-02-07.pdf

# Generate serials for manual entry
python main.py generate-serials --count 5 --sku TREK-VERVE-3-BLU-M

# Print labels for specific serials
python main.py print-labels BIKE-00247 BIKE-00248

# View inventory status
python main.py inventory --available
python main.py inventory --sold --since 2024-02-01

# Export profit report
python main.py report --start 2024-01-01 --end 2024-02-07 --output report.csv

# Start web UI
python main.py web

# Start webhook listener
python webhook_server.py
```

## 14. Error Handling

### Invoice Parsing Failures

```python
class ParseError(Exception):
    """Raised when invoice parsing fails."""
    pass

def parse_invoice_with_retry(images, catalog, max_retries=3):
    """
    Retry parsing with exponential backoff.
    On failure, save partial results and flag for manual review.
    """
    pass
```

### Shopify API Failures

```python
def create_variant_with_retry(product_id, serial, cost, price):
    """
    Handle rate limits (429) and network errors.
    Implement exponential backoff.
    Log failures to database for later retry.
    """
    pass
```

### Duplicate Serial Protection

```python
def generate_serial_numbers(count):
    """
    Use database transaction with SELECT FOR UPDATE
    to prevent duplicate serials in concurrent requests.
    """
    with db.transaction():
        current = db.execute(
            "SELECT next_serial FROM serial_counter WHERE id=1 FOR UPDATE"
        ).fetchone()

        serials = [f"BIKE-{current + i:05d}" for i in range(count)]

        db.execute(
            "UPDATE serial_counter SET next_serial = ? WHERE id=1",
            (current + count,)
        )

        return serials
```

## 15. Testing Strategy

### Unit Tests

- Invoice parser with sample PDFs
- Cost allocation logic
- Serial number generation (concurrency)
- Barcode generation

### Integration Tests

- Shopify API mocking (use `responses` library)
- Full receiving workflow with test fixtures
- Webhook signature verification

### Manual Testing Checklist

```text
□ Upload and parse real invoice
□ Verify costs allocated correctly
□ Check Shopify variants created
□ Print barcode labels
□ Scan barcode in Shopify POS (test mode)
□ Verify webhook fires on test sale
□ Check bike marked sold in database
□ Generate profit report, verify accuracy
```

## 16. Deployment

### Local Development

```bash
# Terminal 1: Web UI
python main.py web

# Terminal 2: Webhook listener
python webhook_server.py

# Terminal 3: Process invoices
python main.py receive-invoice invoices/latest.pdf
```

### Production (Simple)

- Run on store computer (Windows/Mac/Linux)
- SQLite database on local disk
- Web UI accessible at `localhost:5000`
- Webhook via ngrok or Cloudflare Tunnel:

  ```bash
  ngrok http 5001
  # Update Shopify webhook URL to ngrok URL
  ```

### Production (Better)

- Deploy webhook listener to cloud (Fly.io, Railway, Heroku)
- Database synced to cloud backup (Dropbox, Google Drive)
- Web UI either local or cloud

## 17. Future Enhancements

### Phase 2

- [ ] Online store variant consolidation
- [ ] Batch update costs for existing products
- [ ] Advanced reporting dashboard
- [ ] Email notifications on low stock
- [ ] Multi-user access with permissions

### Phase 3

- [ ] Mobile app for receiving (scan bike, assign serial)
- [ ] Integration with accounting (QuickBooks, Xero)
- [ ] Predictive ordering based on sales velocity
- [ ] Customer-facing "bike history" lookup

## 18. Security Considerations

- Store API keys in `.env`, never commit
- Add `.env` to `.gitignore`
- Use HTTPS for webhook endpoint
- Verify Shopify webhook signatures
- Sanitize file uploads (PDF validation)
- Rate limit web UI endpoints
- Database backups encrypted

## 19. Performance Notes

- SQLite handles 50-200 bikes easily
- Invoice parsing: ~5-10 seconds per PDF
- Shopify variant creation: ~1-2 seconds per bike
- Webhook response time: <100ms
- Barcode PDF generation: <1 second

### Optimization if needed

- Batch Shopify API calls (GraphQL)
- Cache product catalog in memory
- Index database queries
- Async invoice processing (Celery)

## 20. Success Metrics

After MVP launch, track:

- Time to receive shipment (target: <5 minutes)
- POS checkout time per bike (target: <30 seconds)
- Invoice parsing accuracy (target: >95%)
- Profit report accuracy (target: 100%)
- System uptime (target: >99%)

## 21. Open Questions / Decisions Needed

- [ ] Which AI service: Gemini or Claude?
- [ ] Barcode format: Code128 or QR code?
- [ ] Label printer: Thermal or laser? (affects label generation)
- [ ] Webhook hosting: Local or cloud?
- [ ] Product catalog: Manual entry or Shopify import?
- [ ] Initial serial number: Start at 1 or current inventory count?

---

## Getting Started

1. Set up Python environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   ```

2. Configure environment:

   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. Initialize database:

   ```bash
   python main.py init-db
   ```

4. Load products from Shopify:

   ```bash
   python main.py sync-products
   ```

5. Process first invoice:

   ```bash
   python main.py receive-invoice data/invoices/sample.pdf
   ```
