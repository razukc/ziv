"""ziv.store — SQLite persistence for the relay (docs/ARCHITECTURE.md §7).

One file per relay, WAL mode, numbered migrations, one transaction per core
transition, ``BEGIN IMMEDIATE`` around claims. A repository per aggregate
loads a slice, lets the core decide, and writes the result.
"""
from .db import RetentionPolicy, Store, StoreBusy, StoreError

__all__ = ["RetentionPolicy", "Store", "StoreBusy", "StoreError"]
