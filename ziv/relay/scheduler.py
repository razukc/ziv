"""ziv.relay.scheduler — ``tick(relay, now)``: one pass of the background work.

Claims due schedule rows under a lease and fires them through admission,
expires what passed ``expires``, fails over what no device started within
the handoff window, fails bodies that never came, assigns what is pending,
and prunes by retention. The lifespan loop calls it every ``ZIV_POLL_S``;
tests call it with their own ``now`` and never start the loop.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ziv.store import StoreBusy

if TYPE_CHECKING:
    from .service import Relay


async def tick(relay: "Relay", now: float) -> None:
    settings = relay.settings
    try:
        claimed = relay.store.schedule.claim_due(now, settings.lease_s)
    except StoreBusy:
        relay.event("claim_busy")
        claimed = []
    for row in claimed:
        relay.fire(row)
    relay.expire(now)
    relay.failover(now)
    relay.body_timeouts(now)
    for wearer in relay.store.outbox.wearers_with_active():
        relay._assign(wearer)
    if relay.prune_due(now):
        relay.prune(now)
