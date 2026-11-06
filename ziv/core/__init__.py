"""ziv.core — the pure domain.

No I/O, no asyncio, no clocks of its own. Every function takes the relevant
slice of state, an event and ``now`` (epoch seconds) and returns the new slice
plus a list of effects for an adapter to carry out (docs/ARCHITECTURE.md §4.1).
"""
