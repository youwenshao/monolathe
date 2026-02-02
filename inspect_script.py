import asyncio
import json
from src.shared.database import get_session
from src.shared.orm_models import ScheduledContentORM
from sqlalchemy import select

async def main():
    async with get_session() as s:
        r = await s.execute(select(ScheduledContentORM).where(ScheduledContentORM.id == 'd949dc33-84ce-481e-9702-756f319cdba6'))
        c = r.scalar()
        if c:
            print(json.dumps(c.script_json, indent=2))
        else:
            print('None')

if __name__ == "__main__":
    asyncio.run(main())
