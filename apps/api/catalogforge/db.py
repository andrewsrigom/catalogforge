from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

engine = create_async_engine(settings().database_url, pool_pre_ping=True, pool_size=8)
Session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    async with Session() as session, session.begin():
        yield session


async def session_dependency() -> AsyncIterator[AsyncSession]:
    async with transaction() as session:
        yield session
