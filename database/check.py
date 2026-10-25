"""Run via `python -m database.check` to verify real PostgreSQL connectivity."""
import asyncio
from sqlalchemy import text
from config import Settings
from database.session import create_engine


async def main():
    engine = create_engine(Settings())
    try:
        async with engine.connect() as conn:
            version = await conn.scalar(text("SELECT current_setting('server_version')"))
            tables = (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
            print(f"PostgreSQL {version}; public tables: {', '.join(tables) or '(none)'}")
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
