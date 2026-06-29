from intric.database.tables import _TABLE_MODULES


def test_tables_package_registers_tenant_metadata_field_module():
    assert "intric.database.tables.tenant_metadata_field_table" in _TABLE_MODULES
