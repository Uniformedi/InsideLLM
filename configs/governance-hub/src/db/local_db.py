from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings

engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=2)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for framework parser and other sync operations
_sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
sync_engine = create_engine(_sync_url, pool_size=2, max_overflow=1)
SyncSessionLocal = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)


async def get_local_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
