"""CLI entry point for the E-Bike Inventory Management System."""

from __future__ import annotations

import click

from config import settings
from database import init_database


@click.group()
def cli() -> None:
    """E-Bike Inventory Management System."""


@cli.command()
def init_db() -> None:
    """Initialise the SQLite database (creates tables if missing)."""
    init_database(settings.database_path)
    print(f"Database initialised at {settings.database_path}")


@cli.command()
def web() -> None:
    """Start the Flask API server."""
    from api.app import create_app

    app = create_app()
    app.run(
        host=settings.flask_host,
        port=settings.flask_port,
        debug=settings.flask_debug,
    )


@cli.command()
def sync_products() -> None:
    """Sync product catalogue from Shopify."""
    from services.shopify_sync import sync_products_from_shopify

    count = sync_products_from_shopify()
    print(f"Synced {count} products from Shopify")


@cli.command()
@click.argument("pdf_path")
def receive_invoice(pdf_path: str) -> None:
    """Upload and parse a supplier invoice PDF."""
    from pathlib import Path

    from database.connection import get_db
    import database.models as models
    from services.invoice_parser import (
        ParseError,
        allocate_costs,
        match_to_catalog,
        parse_invoice_with_retry,
    )
    from services.serial_generator import generate_serial_numbers

    path = Path(pdf_path)
    if not path.exists():
        print(f"Error: file not found: {pdf_path}")
        return

    print(f"Parsing invoice: {path.name} ...")
    try:
        parsed = parse_invoice_with_retry(str(path))
    except ParseError as exc:
        print(f"Error parsing invoice: {exc}")
        return

    print(f"\nSupplier:   {parsed.supplier}")
    print(f"Invoice #:  {parsed.invoice_number}")
    print(f"Date:       {parsed.invoice_date}")
    print(f"Shipping:   ${parsed.shipping_cost:.2f}")
    print(f"Discount:   ${parsed.discount:.2f}")
    print(f"Total:      ${parsed.total:.2f}")
    print(f"\nItems ({len(parsed.items)}):")
    for i, item in enumerate(parsed.items, 1):
        print(f"  {i}. {item.model} (qty {item.quantity}) @ ${item.unit_cost:.2f} = ${item.total_cost:.2f}")

    if not click.confirm("\nApprove this invoice?"):
        print("Invoice not approved.")
        return

    conn = get_db(settings.database_path)
    try:
        # Create invoice record
        invoice = models.create_invoice(
            conn,
            invoice_ref=parsed.invoice_number,
            supplier=parsed.supplier,
            invoice_date=parsed.invoice_date,
            total_amount=parsed.total,
            shipping_cost=parsed.shipping_cost,
            discount=parsed.discount,
            file_path=str(path),
            parsed_data=parsed.model_dump_json(),
        )

        # Match items to catalog
        catalog = models.list_products(conn)
        item_dicts = []
        for item in parsed.items:
            product_id = match_to_catalog(item, catalog)
            item_dicts.append({
                "description": item.model,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "total_cost": item.total_cost,
                "product_id": product_id,
            })

        models.create_invoice_items_bulk(conn, invoice["id"], item_dicts)

        # Allocate costs
        per_unit_costs = allocate_costs(parsed.items, parsed.shipping_cost, parsed.discount)

        # Generate serials and create bikes
        total_count = sum(item.quantity for item in parsed.items)
        serials = generate_serial_numbers(total_count)

        bike_dicts = []
        serial_idx = 0
        for item_dict, alloc_cost in zip(item_dicts, per_unit_costs):
            for _ in range(item_dict["quantity"]):
                bike_dicts.append({
                    "serial_number": serials[serial_idx],
                    "product_id": item_dict["product_id"],
                    "actual_cost": alloc_cost,
                    "invoice_id": invoice["id"],
                })
                serial_idx += 1

        models.create_bikes_bulk(conn, bike_dicts)
        models.update_invoice_status(conn, invoice["id"], "approved", approved_by="cli")

        print(f"\nInvoice approved. Created {total_count} bikes:")
        for serial in serials:
            print(f"  {serial}")
    finally:
        conn.close()


@cli.command()
@click.option("--count", default=1, help="Number of serials to generate.")
@click.option("--sku", required=True, help="Product SKU.")
def generate_serials(count: int, sku: str) -> None:
    """Generate serial numbers for a product."""
    from database.connection import get_db
    import database.models as models
    from services.serial_generator import generate_serial_numbers

    conn = get_db(settings.database_path)
    try:
        product = models.get_product_by_sku(conn, sku)
        if product is None:
            print(f"Error: no product found with SKU '{sku}'")
            return

        serials = generate_serial_numbers(count)

        bike_dicts = [
            {
                "serial_number": serial,
                "product_id": product["id"],
                "actual_cost": 0.0,
            }
            for serial in serials
        ]
        models.create_bikes_bulk(conn, bike_dicts)

        print(f"Generated {count} serial(s) for {product['model_name']} ({sku}):")
        for serial in serials:
            print(f"  {serial}")
    finally:
        conn.close()


@cli.command()
@click.argument("serials", nargs=-1)
def print_labels(serials: tuple[str, ...]) -> None:
    """Generate barcode label PDF for the given serial numbers."""
    if not serials:
        print("Usage: print-labels SERIAL [SERIAL ...]")
        return
    from pathlib import Path

    from services.barcode_generator import create_label_sheet

    output = str(Path(settings.label_output_dir) / "labels.pdf")
    create_label_sheet(list(serials), output)
    print(f"Label sheet saved to {output}")


@cli.command()
@click.option("--available", is_flag=True, help="Show only available bikes.")
@click.option("--sold", is_flag=True, help="Show only sold bikes.")
@click.option("--damaged", is_flag=True, help="Show only damaged bikes.")
def inventory(available: bool, sold: bool, damaged: bool) -> None:
    """View current inventory status."""
    from database.connection import get_db
    import database.models as models

    status = None
    if available:
        status = "available"
    elif sold:
        status = "sold"
    elif damaged:
        status = "damaged"

    conn = get_db(settings.database_path)
    try:
        bikes = models.list_bikes(conn, status=status)
        if not bikes:
            label = f" ({status})" if status else ""
            print(f"No bikes found{label}.")
            return

        # Print header
        print(f"{'Serial':<16} {'Model':<30} {'Status':<10} {'Cost':>10} {'Sale':>10}")
        print("-" * 80)
        for bike in bikes:
            sale = f"${bike['sale_price']:.2f}" if bike.get("sale_price") else "-"
            print(
                f"{bike['serial_number']:<16} "
                f"{bike.get('model_name', 'N/A'):<30} "
                f"{bike['status']:<10} "
                f"${bike['actual_cost']:>9.2f} "
                f"{sale:>10}"
            )
        print(f"\nTotal: {len(bikes)} bike(s)")
    finally:
        conn.close()


@cli.command()
@click.option("--start", required=True, help="Start date (YYYY-MM-DD).")
@click.option("--end", required=True, help="End date (YYYY-MM-DD).")
def report(start: str, end: str) -> None:
    """Generate a profit report for the given date range."""
    from database.connection import get_db
    import database.models as models

    conn = get_db(settings.database_path)
    try:
        summary = models.get_profit_summary(conn, start, end)
        by_product = models.get_profit_report(conn, start, end)

        print(f"Profit Report: {start} to {end}")
        print("=" * 80)
        print(f"  Units Sold:    {summary['units_sold']}")
        print(f"  Revenue:       ${summary['total_revenue']:,.2f}")
        print(f"  Cost:          ${summary['total_cost']:,.2f}")
        print(f"  Profit:        ${summary['total_profit']:,.2f}")
        print(f"  Margin:        {summary['margin_pct']:.1f}%")

        if by_product:
            print(f"\n{'Product':<30} {'Sold':>6} {'Revenue':>12} {'Cost':>12} {'Profit':>12} {'Margin':>8}")
            print("-" * 80)
            for row in by_product:
                print(
                    f"{row['model_name']:<30} "
                    f"{row['units_sold']:>6} "
                    f"${row['total_revenue']:>11,.2f} "
                    f"${row['total_cost']:>11,.2f} "
                    f"${row['total_profit']:>11,.2f} "
                    f"{row['margin_pct']:>7.1f}%"
                )
        else:
            print("\nNo sold bikes in this date range.")
    finally:
        conn.close()


@cli.command()
def reconcile() -> None:
    """Reconcile local inventory with Shopify."""
    from database.connection import get_db
    import database.models as models
    from services.shopify_sync import _graphql_request

    conn = get_db(settings.database_path)
    try:
        products = models.list_products(conn)
        if not products:
            print("No products in database.")
            return

        mismatches = 0
        for product in products:
            shopify_pid = product.get("shopify_product_id")
            if not shopify_pid:
                continue

            # Query Shopify for variants of this product
            query = """
            query GetProductVariants($id: ID!) {
              product(id: $id) {
                variants(first: 100) {
                  edges { node { id sku } }
                }
              }
            }
            """
            try:
                data = _graphql_request(query, {"id": shopify_pid})
            except Exception as exc:
                print(f"  Error querying Shopify for {product['sku']}: {exc}")
                continue

            shopify_skus = set()
            for edge in data["product"]["variants"]["edges"]:
                sku = edge["node"].get("sku", "")
                if sku.startswith(settings.serial_prefix + "-"):
                    shopify_skus.add(sku)

            # Get local available bikes for this product
            local_bikes = models.list_bikes(conn, product_id=product["id"], status="available")
            local_serials = {b["serial_number"] for b in local_bikes}

            in_shopify_not_local = shopify_skus - local_serials
            in_local_not_shopify = local_serials - shopify_skus

            if in_shopify_not_local or in_local_not_shopify:
                mismatches += 1
                print(f"\n{product['model_name']} ({product['sku']}):")
                if in_shopify_not_local:
                    print(f"  In Shopify but not local: {', '.join(sorted(in_shopify_not_local))}")
                if in_local_not_shopify:
                    print(f"  In local but not Shopify: {', '.join(sorted(in_local_not_shopify))}")

        if mismatches == 0:
            print("Reconciliation complete: no mismatches found.")
        else:
            print(f"\nReconciliation complete: {mismatches} product(s) with mismatches.")
    finally:
        conn.close()


@cli.command()
def webhook() -> None:
    """Start the Shopify webhook listener."""
    from webhook_server import create_webhook_app

    app = create_webhook_app()
    app.run(
        host=settings.webhook_host,
        port=settings.webhook_port,
        debug=False,
    )


if __name__ == "__main__":
    cli()
