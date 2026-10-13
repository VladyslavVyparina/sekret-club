"""
Сервіс роботи з користувачами
"""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User, Subscription, Payment
from database.models import UserStatus
import config


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
) -> User:
    """Отримати або створити користувача"""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            status=UserStatus.NOT_SUBSCRIBER.value,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        user.phone = phone or user.phone
        if email:
            user.email = email
        user.last_activity = datetime.utcnow()
        await session.commit()
    return user


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    """Отримати користувача"""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def user_has_active_subscription(session: AsyncSession, user: User) -> bool:
    """Чи є активна підписка (в т.ч. скасована — доступ до кінця терміну)"""
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .where(Subscription.is_active == True)
        .where(Subscription.end_date > datetime.utcnow())
        .order_by(Subscription.end_date.desc())
        .limit(1)
    )
    return result.scalars().first() is not None


async def user_has_group_access(session: AsyncSession, user: User) -> bool:
    """Чи має доступ до групи — підписка з end_date > now (скасована теж дає доступ до кінця)"""
    return await user_has_active_subscription(session, user)


async def get_active_subscription(session: AsyncSession, user: User) -> Subscription | None:
    """Отримати поточну підписку (в т.ч. скасовану — для відображення до кінця терміну)"""
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .where(Subscription.is_active == True)
        .where(Subscription.end_date > datetime.utcnow())
        .order_by(Subscription.end_date.desc())
        .limit(1)
    )
    return result.scalars().first()


async def activate_subscription(
    session: AsyncSession,
    user: User,
    is_trial: bool,
    rec_token: str | None = None,
    order_reference: str | None = None,
) -> Subscription:
    """Активувати підписку після оплати"""
    now = datetime.utcnow()
    period = timedelta(days=int(config.SUBSCRIPTION_DAYS))

    if is_trial:
        end_date = now + timedelta(days=config.TRIAL_DAYS)
        sub = Subscription(
            user_id=user.id,
            start_date=now,
            end_date=end_date,
            is_trial=True,
            is_active=True,
        )
        session.add(sub)
        user.status = UserStatus.SUBSCRIBER.value
        user.has_used_trial = True
        if rec_token:
            user.rec_token = rec_token
        if order_reference:
            user.order_reference = order_reference
        await session.commit()
        await session.refresh(sub)
        return sub

    # Стандарт / рекурент: закрити trial і відкрити 30 днів, або продовжити активну стандартну.
    active = await get_active_subscription(session, user)
    if active and active.is_trial:
        active.is_active = False
        sub = Subscription(
            user_id=user.id,
            start_date=now,
            end_date=now + period,
            is_trial=False,
            is_active=True,
        )
        session.add(sub)
    elif active and not active.is_trial:
        base = active.end_date
        if getattr(base, "tzinfo", None):
            base = base.replace(tzinfo=None)
        active.end_date = max(base, now) + period
        active.is_trial = False
        sub = active
    else:
        sub = Subscription(
            user_id=user.id,
            start_date=now,
            end_date=now + period,
            is_trial=False,
            is_active=True,
        )
        session.add(sub)

    user.status = UserStatus.SUBSCRIBER.value
    if rec_token:
        user.rec_token = rec_token
    if order_reference:
        user.order_reference = order_reference

    await session.commit()
    await session.refresh(sub)
    return sub


async def cancel_subscription(session: AsyncSession, user: User) -> bool:
    """Скасувати підписку — не продовжувати, вимкнути auto-charge. Доступ залишається до end_date."""
    sub = await get_active_subscription(session, user)
    if sub and not sub.cancelled:
        sub.cancelled = True
        if user.order_reference:
            try:
                import requests
                from services.wayforpay import create_regular_delete_request
                req = create_regular_delete_request(user.order_reference)
                resp = requests.post("https://api.wayforpay.com/regularApi", json=req, timeout=10)
                # Успіх: reasonCode=4100, reason="Ok"
                try:
                    j = resp.json()
                    if str(j.get("reasonCode")) not in ("4100", "0"):
                        # Якщо WayForPay не підтвердив — не блокуємо, але логнемо
                        print(f"WayForPay REMOVE failed: {j}")
                except Exception:
                    pass
            except Exception:
                pass
        await session.commit()
        return True
    return False


async def expire_subscription(session: AsyncSession, user: User):
    """Підписка закінчилась - перевести в колишній підписник"""
    user.status = UserStatus.FORMER_SUBSCRIBER.value
    await session.execute(
        Subscription.__table__.update()
        .where(Subscription.user_id == user.id)
        .where(Subscription.end_date < datetime.utcnow())
        .values(is_active=False)
    )
    await session.commit()


async def get_user_status(session: AsyncSession, telegram_id: int) -> str:
    """Повертає статус: not_subscriber | subscriber | former_subscriber"""
    user = await get_user(session, telegram_id)
    if not user:
        return UserStatus.NOT_SUBSCRIBER.value
    if await user_has_active_subscription(session, user):
        return UserStatus.SUBSCRIBER.value
    return user.status
