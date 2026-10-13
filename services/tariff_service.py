"""
Сервіс для роботи з тарифами (таблиця tariffs)
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Tariff


async def get_tariff_by_code(session: AsyncSession, code: str) -> Tariff | None:
    r = await session.execute(select(Tariff).where(Tariff.code == code))
    return r.scalar_one_or_none()


async def get_or_create_tariff(
    session: AsyncSession,
    code: str,
    default_name: str,
    default_price_grn: int,
    is_recurring: bool = True,
) -> Tariff:
    t = await get_tariff_by_code(session, code)
    if t:
        return t
    t = Tariff(code=code, name=default_name, price_grn=default_price_grn, is_recurring=is_recurring)
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t

