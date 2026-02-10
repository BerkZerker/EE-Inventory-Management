"""Shopify webhook listener.

Runs as a separate Flask process on the webhook port.  Handles
orders/create webhooks with HMAC-SHA256 signature verification
and deduplication via the webhook_log table.

To be implemented in Phase 9.
"""
