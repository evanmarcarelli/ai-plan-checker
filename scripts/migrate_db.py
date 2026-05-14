#!/usr/bin/env python3
"""
Database migration script.
Run with: python scripts/migrate_db.py
"""
import asyncio
import sys
sys.path.insert(0, "./backend")

from app.models.database import init_database
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def migrate():
    logger.info("Running database migrations...")
    await init_database()
    logger.info("Migrations complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
