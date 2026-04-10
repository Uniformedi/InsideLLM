"""
Central database connection — always synchronous.

The central DB (fleet management, cross-instance sync) uses sync SQLAlchemy
for all database types (PostgreSQL, MariaDB, MSSQL) because:
1. pymssql has no async driver
2. Fleet queries are low-throughput (no need for async)
3. All central DB operations run in a thread pool via run_central_query()
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings

logger = logging.getLogger("governance-hub.central-db")

T = TypeVar("T")

_central_engine = None
_CentralSession = None


def _build_sync_url(url: str) -> str:
    """Convert async driver URLs to sync equivalents."""
    return (url
            .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            .replace("mysql+aiomysql://", "mysql+pymysql://"))


def get_central_engine():
    global _central_engine
    if _central_engine is None and settings.central_db_url:
        sync_url = _build_sync_url(settings.central_db_url)
        connect_args = {}
        if "pymssql" in sync_url:
            connect_args = {"login_timeout": 10, "tds_version": "7.3"}
        elif "psycopg2" in sync_url:
            connect_args = {"connect_timeout": 10}

        _central_engine = create_engine(
            sync_url,
            pool_size=3,
            max_overflow=1,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        logger.info(f"Central DB engine created (sync): {settings.central_db_type}")
    return _central_engine


def get_central_session_factory():
    global _CentralSession
    if _CentralSession is None:
        eng = get_central_engine()
        if eng:
            _CentralSession = sessionmaker(eng, class_=Session, expire_on_commit=False)
    return _CentralSession


async def run_central_query(fn: Callable[[Session], T]) -> T | None:
    """Run a sync function with a central DB session in a thread pool.

    Usage:
        result = await run_central_query(lambda db: db.execute(text("SELECT 1")).scalar())
    """
    factory = get_central_session_factory()
    if factory is None:
        return None

    def _run():
        with factory() as db:
            return fn(db)

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, _run)
