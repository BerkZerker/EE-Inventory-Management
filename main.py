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
    print("Not yet implemented")


@cli.command()
@click.argument("pdf_path")
def receive_invoice(pdf_path: str) -> None:
    """Upload and parse a supplier invoice PDF."""
    print("Not yet implemented")


@cli.command()
@click.option("--count", default=1, help="Number of serials to generate.")
@click.option("--sku", required=True, help="Product SKU.")
def generate_serials(count: int, sku: str) -> None:
    """Generate serial numbers for a product."""
    print("Not yet implemented")


@cli.command()
@click.argument("serials", nargs=-1)
def print_labels(serials: tuple[str, ...]) -> None:
    """Generate barcode label PDF for the given serial numbers."""
    print("Not yet implemented")


@cli.command()
@click.option("--available", is_flag=True, help="Show only available bikes.")
@click.option("--sold", is_flag=True, help="Show only sold bikes.")
def inventory(available: bool, sold: bool) -> None:
    """View current inventory status."""
    print("Not yet implemented")


@cli.command()
@click.option("--start", required=True, help="Start date (YYYY-MM-DD).")
@click.option("--end", required=True, help="End date (YYYY-MM-DD).")
def report(start: str, end: str) -> None:
    """Generate a profit report for the given date range."""
    print("Not yet implemented")


@cli.command()
def reconcile() -> None:
    """Reconcile local inventory with Shopify."""
    print("Not yet implemented")


@cli.command()
def webhook() -> None:
    """Start the Shopify webhook listener."""
    print("Not yet implemented")


if __name__ == "__main__":
    cli()
