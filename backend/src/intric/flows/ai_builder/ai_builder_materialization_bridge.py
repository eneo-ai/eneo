"""Materialization Bridge — single seam between AI Builder and the
flows-domain write surface.

This module is the **only** place inside ``intric.flows.ai_builder``
that is permitted to import from the ``intric.flows.api`` package — its
DTOs (``flow_models``), assemblers (``flow_assembler``), and routers
(``flow_router``). Every other AI Builder module must route write-surface
type usage through this bridge so the plugin package stays independent
of the flows-domain topology as DTOs, assemblers, and routers evolve.

The boundary is enforced by ``TestRule6MaterializationBridgeAcl`` in
``tests/unittests/flows/ai_builder/test_ai_builder_importlinter_rules.py``,
which scans the plugin package for any module importing from
``intric.flows.api.*`` and fails if anything other than this bridge
appears in the offender set.
"""
