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
        match_to_catalog,
        parse_invoice_with_retry,
    )
    from services.invoice_service import approve_invoice

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
        print(
            f"  {i}. {item.model} (qty {item.quantity}) @ ${item.unit_cost:.2f} = ${item.total_cost:.2f}"
        )

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
            credit_card_fees=parsed.credit_card_fees,
            tax=parsed.tax,
            other_fees=parsed.other_fees,
            file_path=str(path),
            parsed_data=parsed.model_dump_json(),
        )

        # Match items to catalog
        catalog = models.list_products(conn)
        item_dicts = []
        for item in parsed.items:
            product_id = match_to_catalog(item, catalog)
            item_dicts.append(
                {
                    "description": item.model,
                    "quantity": item.quantity,
                    "unit_cost": item.unit_cost,
                    "total_cost": item.total_cost,
                    "product_id": product_id,
                }
            )

        models.create_invoice_items_bulk(conn, invoice["id"], item_dicts)

        # Approve: allocate costs, generate serials, create bikes, push to Shopify
        result = approve_invoice(conn, invoice["id"], push_to_shopify=False, approved_by="cli")

        bikes = result["bikes"]
        print(f"\nInvoice approved. Created {len(bikes)} bikes:")
        for bike in bikes:
            print(f"  {bike['serial_number']}")
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

        print(
            f"Generated {count} serial(s) for {product.get('brand', '')} {product.get('model', '')} ({sku}):"
        )
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
            model_name = f"{bike.get('brand', '')} {bike.get('model', 'N/A')}".strip()
            print(
                f"{bike['serial_number']:<16} "
                f"{model_name:<30} "
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
            print(
                f"\n{'Product':<30} {'Sold':>6} {'Revenue':>12} {'Cost':>12} {'Profit':>12} {'Margin':>8}"
            )
            print("-" * 80)
            for row in by_product:
                product_name = f"{row.get('brand', '')} {row.get('model', '')}".strip()
                print(
                    f"{product_name:<30} "
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
    from services.reconciliation import reconcile_inventory

    conn = get_db(settings.database_path)
    try:
        results = reconcile_inventory(conn)

        if not results:
            print("Reconciliation complete: no mismatches found.")
            return

        for r in results:
            print(f"\n{r['brand']} {r['model']} ({r['sku']}):")
            if r["in_shopify_not_local"]:
                print(f"  In Shopify but not local: {', '.join(r['in_shopify_not_local'])}")
            if r["in_local_not_shopify"]:
                print(f"  In local but not Shopify: {', '.join(r['in_local_not_shopify'])}")

        print(f"\nReconciliation complete: {len(results)} product(s) with mismatches.")
    finally:
        conn.close()


@cli.command()
@click.argument("callback_url")
def register_webhook(callback_url: str) -> None:
    """Register the orders/create webhook with Shopify.

    CALLBACK_URL is the public HTTPS endpoint, e.g.
    https://abc123.ngrok-free.app/webhooks/orders/create
    """
    from services.shopify_sync import _graphql_request

    mutation = """
    mutation webhookSubscriptionCreate(
        $topic: WebhookSubscriptionTopic!,
        $webhookSubscription: WebhookSubscriptionInput!
    ) {
      webhookSubscriptionCreate(
          topic: $topic,
          webhookSubscription: $webhookSubscription
      ) {
        webhookSubscription {
          id
          topic
          endpoint {
            __typename
            ... on WebhookHttpEndpoint {
              callbackUrl
            }
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """

    data = _graphql_request(
        mutation,
        {
            "topic": "ORDERS_CREATE",
            "webhookSubscription": {"uri": callback_url},
        },
    )

    result = data["webhookSubscriptionCreate"]
    if result["userErrors"]:
        print("Failed to register webhook:")
        for err in result["userErrors"]:
            print(f"  {err['field']}: {err['message']}")
        return

    sub = result["webhookSubscription"]
    print(f"Webhook registered successfully!")
    print(f"  ID:    {sub['id']}")
    print(f"  Topic: {sub['topic']}")
    endpoint = sub.get("endpoint", {})
    if endpoint.get("callbackUrl"):
        print(f"  URL:   {endpoint['callbackUrl']}")

    print("\nNote: The webhook signing secret is tied to your app's Client Secret.")
    print(f"Set SHOPIFY_WEBHOOK_SECRET in .env to your Client Secret value.")


@cli.command()
def list_webhooks() -> None:
    """List currently registered webhooks on Shopify."""
    from services.shopify_sync import _graphql_request

    query = """
    query {
      webhookSubscriptions(first: 25) {
        edges {
          node {
            id
            topic
            endpoint {
              __typename
              ... on WebhookHttpEndpoint {
                callbackUrl
              }
            }
            createdAt
          }
        }
      }
    }
    """

    data = _graphql_request(query)
    edges = data["webhookSubscriptions"]["edges"]

    if not edges:
        print("No webhooks registered.")
        return

    print(f"{'Topic':<25} {'URL':<55} {'ID'}")
    print("-" * 120)
    for edge in edges:
        node = edge["node"]
        url = node.get("endpoint", {}).get("callbackUrl", "N/A")
        print(f"{node['topic']:<25} {url:<55} {node['id']}")


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
