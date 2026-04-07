from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings

engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=2)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_local_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
