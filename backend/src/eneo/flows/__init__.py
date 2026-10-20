"""Flows: deterministic, ordered lists of typed steps that run unattended.

A flow is authored by the model through the loopback ``flows`` MCP server
(:mod:`eneo.internal_mcp.flows`) and executed by the worker
(:mod:`eneo.flows.flow_run_executor`). The definition is one JSON document
(:mod:`eneo.flows.definition`); the step kind decides what runs, never a
model at run time.
"""
