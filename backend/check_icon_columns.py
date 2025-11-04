#!/usr/bin/env python
"""Check if icon_name columns exist in template tables."""

import asyncio
from sqlalchemy import text
from intric.database.db import async_engine


async def check_columns():
    """Verify icon_name columns exist in both template tables."""
    async with async_engine.connect() as conn:
        # Check current migration
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        current_migration = result.scalar()
        print(f"Current migration: {current_migration}\n")

        # Check columns in both tables
        for table in ['assistant_templates', 'app_templates']:
            result = await conn.execute(text(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name='{table}' AND column_name='icon_name'
            """))
            row = result.fetchone()
            if row:
                print(f"✓ {table}.icon_name: {row[0]} ({row[1]}) - nullable={row[2]}")
            else:
                print(f"✗ {table}.icon_name: NOT FOUND")


if __name__ == "__main__":
    asyncio.run(check_columns())
