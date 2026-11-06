"""Ziv — a haptic message channel for deaf-blind wearers.

Package map (see docs/ARCHITECTURE.md):

* ``ziv.wire``      — the wire contract: utterances, device frames, sender bodies.
* ``ziv.haptics``   — the generated timing tables and the reference renderer.
* ``ziv.core``      — the pure domain: outbox state machine, admission, schedule.
* ``ziv.store``     — SQLite repository and migrations.
* ``ziv.relay``     — the application: settings, factory, HTTP, WebSocket, scheduler, composer.
"""

__version__ = "0.1.0.dev0"
