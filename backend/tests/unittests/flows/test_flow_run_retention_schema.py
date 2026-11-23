from __future__ import annotations

from eneo.database.tables.flow_tables import Flows
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants


def test_only_the_space_time_and_the_flow_time_are_stored() -> None:
    assert hasattr(Spaces, "data_retention_days")
    assert hasattr(Flows, "flow_run_history_retention_days")

    for table in (Tenants, Spaces, Flows):
        assert not hasattr(table, "flow_run_history_retention_mode")
    assert not hasattr(Tenants, "flow_run_history_retention_days")
    assert not hasattr(Spaces, "flow_run_history_retention_days")
    assert not hasattr(Flows, "data_retention_days")
