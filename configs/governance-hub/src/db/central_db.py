from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings

_central_engine = None
_CentralSession = None


def get_central_engine():
    global _central_engine
    if _central_engine is None and settings.central_db_url:
        _central_engine = create_async_engine(
            settings.central_db_url,
            pool_size=3,
            max_overflow=1,
            pool_pre_ping=True,
        )
    return _central_engine


def get_central_session_factory():
    global _CentralSession
    if _CentralSession is None:
        eng = get_central_engine()
        if eng:
            _CentralSession = sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return _CentralSession


async def get_central_db() -> AsyncSession | None:
    factory = get_central_session_factory()
    if factory is None:
        return None
    async with factory() as session:
        yield session
