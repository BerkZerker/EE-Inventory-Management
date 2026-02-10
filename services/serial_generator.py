"""Atomic serial number generation.

Uses BEGIN IMMEDIATE transactions against the serial_counter table
to guarantee unique, gap-free serial numbers even under concurrent access.

To be implemented in Phase 3.
"""
