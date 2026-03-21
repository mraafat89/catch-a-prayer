from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings


class Base(DeclarativeBase):
    pass


# Engine and session factory — tests can replace via set_engine()
_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            connect_args={"ssl": None},
        )
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            _get_engine(), class_=AsyncSession, expire_on_commit=False,
        )
    return _session_factory


def set_engine(new_engine, new_factory):
    """Replace engine and session factory (used by tests)."""
    global _engine, _session_factory
    _engine = new_engine
    _session_factory = new_factory


# Backward-compatible module-level names
class _EngineProxy:
    def __getattr__(self, name):
        return getattr(_get_engine(), name)

class _SessionFactoryProxy:
    def __call__(self, *args, **kwargs):
        return _get_session_factory()(*args, **kwargs)
    def __getattr__(self, name):
        return getattr(_get_session_factory(), name)

engine = _EngineProxy()
AsyncSessionLocal = _SessionFactoryProxy()


async def get_db() -> AsyncSession:
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
