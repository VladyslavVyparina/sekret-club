"""
Допоміжні функції для первинного заповнення Content з data.knowledge_base
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import Content, ContentType
from data.knowledge_base import KNOWLEDGE_BASE


async def ensure_streams_seeded(session: AsyncSession):
    from sqlalchemy import select

    r = await session.execute(select(Content).where(Content.content_type == ContentType.STREAM.value))
    if r.scalars().first():
        return
    for idx, s in enumerate(KNOWLEDGE_BASE.get("streams", [])):
        session.add(
            Content(
                content_type=ContentType.STREAM.value,
                title=s["title"],
                sort_order=idx,
            )
        )
    await session.commit()


async def ensure_materials_seeded(session: AsyncSession):
    r = await session.execute(select(Content).where(Content.content_type == ContentType.MATERIAL.value))
    if r.scalars().first():
        return
    for idx, m in enumerate(KNOWLEDGE_BASE.get("materials", [])):
        session.add(
            Content(
                content_type=ContentType.MATERIAL.value,
                title=m["title"],
                sort_order=idx,
            )
        )
    await session.commit()


async def ensure_books_seeded(session: AsyncSession):
    r = await session.execute(select(Content).where(Content.content_type == ContentType.BOOK.value))
    if r.scalars().first():
        return
    for idx, b in enumerate(KNOWLEDGE_BASE.get("books", [])):
        session.add(
            Content(
                content_type=ContentType.BOOK.value,
                title=b["title"],
                sort_order=idx,
            )
        )
    await session.commit()

