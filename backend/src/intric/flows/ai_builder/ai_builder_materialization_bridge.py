"""Materialization Bridge — single seam between AI Builder and the
flows-domain draft-write surface.

This module is the **only** place inside ``intric.flows.ai_builder``
that is permitted to import from ``intric.flows.api.flow_models``.
Every other AI Builder module must route draft-write type usage through
this bridge so the plugin package stays independent of the write-surface
topology.

A.5 scaffolds this module as docstring-only. The concrete bridge
implementation lands in Phase D (D.7), once the draft-write types
currently living in ``ai_builder_domain_models.py`` are extracted onto
the flows-domain surface.

Rule 6 of Phase A.5 — enforced by ``TestRule6MaterializationBridgeAcl``
in ``tests/unittests/flows/ai_builder/test_ai_builder_importlinter_rules.py``.
"""
