import asyncio
from src.shared.database import get_session
from src.shared.orm_models import ScheduledContentORM
from sqlalchemy import select

async def main():
    async with get_session() as s:
        r = await s.execute(select(ScheduledContentORM).limit(1))
        c = r.scalar()
        print(c.id if c else 'None')

if __name__ == "__main__":
    asyncio.run(main())
