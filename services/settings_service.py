"""
Сервіс простих налаштувань (DB table settings)
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Setting


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    r = await session.execute(select(Setting).where(Setting.key == key))
    s = r.scalar_one_or_none()
    return s.value if s else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    r = await session.execute(select(Setting).where(Setting.key == key))
    s = r.scalar_one_or_none()
    if not s:
        s = Setting(key=key, value=value)
        session.add(s)
    else:
        s.value = value
    await session.commit()
