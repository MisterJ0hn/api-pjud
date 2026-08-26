from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import settings

engine_async = create_async_engine(settings.database_url_async, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine_async, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
