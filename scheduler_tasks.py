"""
Планові завдання:
- Нагадування за 1 день до автосписання (день 13 trial / день 29 місяця)
- Нагадування за 3 дні до кінця підписки
- Retry при неуспішній оплаті
"""
import asyncio
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

import config
from database.database import async_session
from database.models import User, Subscription, PaymentFailure, Payment

_bot = None
RETRY_HOURS = [48, 48, 72, 96, 72]
MONTHS_UA = ["січня", "лютого", "березня", "квітня", "травня", "червня",
             "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = None


def set_bot(bot):
    global _bot
    _bot = _bot or bot


def send_telegram(chat_id: int, text: str):
    try:
        import requests
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram send error: {e}")


async def remind_charge_tomorrow():
    """За 1 день до end_date — нагадування про автосписання (день 13 trial / день 29 місяця)."""
    from services.payment_notifications import charge_tomorrow_message, send_payment_notification
    from services.settings_service import get_setting, set_setting

    tomorrow = (datetime.utcnow() + timedelta(days=1)).date()
    async with async_session() as session:
        result = await session.execute(
            select(User, Subscription)
            .join(Subscription, Subscription.user_id == User.id)
            .where(Subscription.is_active == True)
            .where(Subscription.cancelled == False)
            .where(Subscription.end_date > datetime.utcnow())
        )
        rows = result.all()

    for user, sub in rows:
        if sub.end_date.date() != tomorrow:
            continue
        dedupe_key = f"charge_remind:{user.id}:{sub.end_date.date().isoformat()}"
        async with async_session() as session:
            if await get_setting(session, dedupe_key, ""):
                continue
            text = charge_tomorrow_message(sub.end_date, is_trial_period=bool(sub.is_trial))
            try:
                if _bot:
                    await _bot.send_message(user.telegram_id, text)
                else:
                    send_payment_notification(user.telegram_id, text)
            except Exception as e:
                print(f"Charge tomorrow reminder error: {e}")
                continue
            await set_setting(session, dedupe_key, "1")


async def remind_subscription_ending():
    """Нагадування за 3 дні до кінця підписки"""
    target_date = (datetime.utcnow() + timedelta(days=3)).date()
    async with async_session() as session:
        result = await session.execute(
            select(User, Subscription)
            .join(Subscription, Subscription.user_id == User.id)
            .where(Subscription.is_active == True)
            .where(Subscription.cancelled == False)
        )
        for row in result.all():
            user, sub = row
            if sub.end_date.date() == target_date:
                try:
                    if _bot:
                        await _bot.send_message(
                            user.telegram_id,
                            f"⏰ Нагадування: ваша підписка закінчується через 3 дні ({sub.end_date.strftime('%d.%m.%Y')}). "
                            "Продовжіть, щоб не втратити доступ до клубу!",
                        )
                    else:
                        send_telegram(
                            user.telegram_id,
                            f"⏰ Нагадування: ваша підписка закінчується через 3 дні ({sub.end_date.strftime('%d.%m.%Y')}). "
                            "Продовжіть, щоб не втратити доступ до клубу!",
                        )
                except Exception as e:
                    print(f"Reminder error: {e}")


async def expire_ended_subscriptions():
    """Підписки що закінчились — перевести юзера в колишній підписник"""
    from database.models import UserStatus
    now = datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.end_date < now)
            .where(Subscription.is_active == True)
            .where(User.status == UserStatus.SUBSCRIBER.value)
        )
        for sub, user in result.all():
            sub.is_active = False
            user.status = UserStatus.FORMER_SUBSCRIBER.value
        await session.commit()


async def remove_expired_from_group():
    """
    Видалити з групи користувачів, у яких закінчилась підписка і вони не продовжили:
    - не оплатили автосписання
    - скасували підписку (видаляємо після end_date)
    - підписка закінчилась і не поновили
    """
    from services.user_service import user_has_group_access
    import requests

    if not config.CLUB_GROUP_ID:
        return
    chat_id = config.CLUB_GROUP_ID
    base_url = f"https://api.telegram.org/bot{config.BOT_TOKEN}"

    async with async_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

    for user in users:
        if user.telegram_id in (config.ADMIN_IDS or []):
            continue
        async with async_session() as session:
            has_access = await user_has_group_access(session, user)
        if not has_access:
            try:
                r = requests.post(
                    f"{base_url}/banChatMember",
                    json={"chat_id": chat_id, "user_id": user.telegram_id},
                    timeout=5,
                )
                if r.ok:
                    requests.post(
                        f"{base_url}/unbanChatMember",
                        json={"chat_id": chat_id, "user_id": user.telegram_id},
                        timeout=5,
                    )
            except Exception as e:
                pass


async def run_payment_retries():
    """Retry неуспішних платежів — Day 2, 4, 7, 11, 14"""
    from services.wayforpay import create_charge_request

    now = datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(
            select(PaymentFailure, User)
            .join(User, User.id == PaymentFailure.user_id)
            .where(PaymentFailure.next_retry_at <= now)
            .where(PaymentFailure.retry_index < 5)
        )
        rows = result.all()

    for pf, user in rows:
        req = create_charge_request(
            rec_token=pf.rec_token,
            amount=config.PRICE_STANDARD_GRN,
            order_reference=f"retry_{user.telegram_id}_{int(now.timestamp())}",
            product_name="Секрет Клуб — Стандарт 1 міс",
        )
        try:
            r = requests.post("https://api.wayforpay.com/api", json=req, timeout=15)
            data = r.json() if r.text else {}
        except Exception as e:
            print(f"Retry Charge error: {e}")
            continue

        if data.get("transactionStatus") == "Approved":
            from services.user_service import activate_subscription, get_active_subscription
            from services.payment_notifications import tariff_renewed_message, send_payment_notification
            async with async_session() as session:
                u = await session.get(User, user.id)
                if not u:
                    continue
                # Якщо під час retry був grace-період доступу, не додаємо його до нового циклу оплати.
                sub_rows = await session.execute(
                    select(Subscription)
                    .where(Subscription.user_id == u.id)
                    .where(Subscription.is_active == True)
                )
                for srow in sub_rows.scalars().all():
                    srow.is_active = False
                await activate_subscription(session, u, is_trial=False, rec_token=pf.rec_token)
                renewed_sub = await get_active_subscription(session, u)
                end_date = renewed_sub.end_date if renewed_sub else datetime.utcnow()

                # Прибираємо всі відкриті failure-записи користувача, щоб не було дубльованих retry.
                all_pf = await session.execute(select(PaymentFailure).where(PaymentFailure.user_id == u.id))
                for row in all_pf.scalars().all():
                    await session.delete(row)
                await session.commit()
            send_payment_notification(user.telegram_id, tariff_renewed_message(end_date))
        else:
            next_idx = pf.retry_index + 1
            if next_idx >= 5:
                # Фінал: якщо всі спроби вичерпані, вимикаємо доступ.
                from database.models import UserStatus
                send_telegram(
                    user.telegram_id,
                    "🚫 Всі спроби списання невдалі. Підписка припинена. Оформіть підписку заново через бота.",
                )
                async with async_session() as session:
                    u = await session.get(User, user.id)
                    if u:
                        sub_rows = await session.execute(
                            select(Subscription)
                            .where(Subscription.user_id == u.id)
                            .where(Subscription.is_active == True)
                        )
                        for srow in sub_rows.scalars().all():
                            srow.is_active = False
                            srow.end_date = datetime.utcnow()
                        u.status = UserStatus.FORMER_SUBSCRIBER.value
                    pf_obj = await session.get(PaymentFailure, pf.id)
                    if pf_obj:
                        await session.delete(pf_obj)
                    await session.commit()

                # Прибрати з групи після фінальної невдалої спроби.
                if config.CLUB_GROUP_ID:
                    chat_id = config.CLUB_GROUP_ID
                    base_url = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
                    try:
                        r = requests.post(
                            f"{base_url}/banChatMember",
                            json={"chat_id": chat_id, "user_id": user.telegram_id},
                            timeout=5,
                        )
                        if r.ok:
                            requests.post(
                                f"{base_url}/unbanChatMember",
                                json={"chat_id": chat_id, "user_id": user.telegram_id},
                                timeout=5,
                            )
                    except Exception:
                        pass
            else:
                hours = RETRY_HOURS[next_idx]
                next_retry = now + timedelta(hours=hours)
                dt = next_retry
                if KYIV_TZ:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(KYIV_TZ) if getattr(dt, "tzinfo", None) is None else dt.astimezone(KYIV_TZ)
                next_d = dt.day
                next_m = MONTHS_UA[dt.month - 1]
                send_telegram(
                    user.telegram_id,
                    "Платіж не пройшов, спробуйте ще раз 🔄\n"
                    "Або напишіть в підтримку @sekret_manager",
                )
                async with async_session() as session:
                    pf_obj = await session.get(PaymentFailure, pf.id)
                    if pf_obj:
                        pf_obj.retry_index = next_idx
                        pf_obj.next_retry_at = next_retry
                        await session.commit()


async def run_trial_to_standard_autocharges():
    """
    Кастомна конвертація trial -> standard:
    після завершення trial автоматично списуємо стандартний тариф по rec_token.
    """
    from services.wayforpay import create_charge_request
    from services.user_service import activate_subscription

    now = datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.is_active == True)
            .where(Subscription.is_trial == True)
            .where(Subscription.end_date <= now)
        )
        rows = result.all()

    for sub, user in rows:
        # Захист від дубля списання: якщо стандарт вже успішно оплачений нещодавно,
        # не запускаємо fallback Charge.
        async with async_session() as session:
            recent_std = await session.execute(
                select(Payment)
                .where(Payment.user_id == user.id)
                .where((Payment.transaction_status == "Approved") | (Payment.status == "Approved"))
                .where(Payment.amount >= float(config.PRICE_STANDARD_GRN) - 0.01)
                .where(Payment.created_at >= now - timedelta(hours=36))
                .order_by(Payment.created_at.desc())
            )
            if recent_std.scalars().first():
                continue

        rec_token = (user.rec_token or "").strip()
        if not rec_token:
            async with async_session() as session:
                sub_obj = await session.get(Subscription, sub.id)
                user_obj = await session.get(User, user.id)
                if sub_obj:
                    sub_obj.is_active = False
                if user_obj:
                    from database.models import UserStatus
                    user_obj.status = UserStatus.FORMER_SUBSCRIBER.value
                await session.commit()
            send_telegram(
                user.telegram_id,
                "⚠️ Пробний період завершився, але автосписання недоступне. "
                "Оформіть тариф «Стандарт» у боті, щоб зберегти доступ.",
            )
            continue

        order_ref = f"trial2std_{user.telegram_id}_{int(now.timestamp())}"
        req = create_charge_request(
            rec_token=rec_token,
            amount=config.PRICE_STANDARD_GRN,
            order_reference=order_ref,
            product_name="Секрет Клуб — авто-перехід Trial -> Стандарт",
        )
        try:
            r = requests.post("https://api.wayforpay.com/api", json=req, timeout=15)
            data = r.json() if r.text else {}
        except Exception as e:
            print(f"Trial->Standard Charge error: {e}")
            continue

        if data.get("transactionStatus") == "Approved":
            from services.user_service import get_active_subscription
            from services.payment_notifications import tariff_renewed_message, send_payment_notification
            async with async_session() as session:
                sub_obj = await session.get(Subscription, sub.id)
                u = await session.get(User, user.id)
                if sub_obj:
                    sub_obj.is_active = False
                if u:
                    await activate_subscription(
                        session,
                        u,
                        is_trial=False,
                        rec_token=rec_token,
                        order_reference=order_ref,
                    )
                    renewed_sub = await get_active_subscription(session, u)
                    end_date = renewed_sub.end_date if renewed_sub else datetime.utcnow()
                else:
                    end_date = datetime.utcnow()
            send_payment_notification(user.telegram_id, tariff_renewed_message(end_date))
        else:
            next_retry = now + timedelta(hours=RETRY_HOURS[0])
            async with async_session() as session:
                sub_obj = await session.get(Subscription, sub.id)
                u = await session.get(User, user.id)
                if sub_obj:
                    sub_obj.is_active = False
                if u:
                    from database.models import UserStatus
                    u.status = UserStatus.FORMER_SUBSCRIBER.value
                session.add(
                    PaymentFailure(
                        user_id=user.id,
                        order_reference=order_ref,
                        rec_token=rec_token,
                        first_failure_at=now,
                        retry_index=0,
                        next_retry_at=next_retry,
                    )
                )
                await session.commit()
            dt = next_retry
            if KYIV_TZ:
                dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(KYIV_TZ) if getattr(dt, "tzinfo", None) is None else dt.astimezone(KYIV_TZ)
            next_d = dt.day
            next_m = MONTHS_UA[dt.month - 1]
            send_telegram(
                user.telegram_id,
                f"🚫 Автосписання після Trial відхилено.\n\n"
                f"Тариф: Стандарт\n"
                f"Вартість: {config.PRICE_STANDARD_GRN},00 ₴/міс\n"
                f"Наступна спроба: {next_d} {next_m}",
            )


async def run_custom_standard_recurring_autocharges():
    """
    Кастомний рекурент стандарту для користувачів після trial-конвертації.
    Запускається на закінченні поточної підписки.
    """
    from services.wayforpay import create_charge_request
    from services.user_service import activate_subscription

    now = datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.is_active == True)
            .where(Subscription.is_trial == False)
            .where(Subscription.cancelled == False)
            .where(Subscription.end_date <= now)
        )
        rows = result.all()

    for sub, user in rows:
        # Беремо кастомний потік після trial-конвертації та його продовження.
        # `trial_` — нативний перший перехід trial -> standard, `trial2std_`/`customsub_` — наші кастомні чарджі.
        if not (user.order_reference or "").startswith(("trial_", "trial2std_", "customsub_")):
            continue

        rec_token = (user.rec_token or "").strip()
        if not rec_token:
            continue

        order_ref = f"customsub_{user.telegram_id}_{int(now.timestamp())}"
        req = create_charge_request(
            rec_token=rec_token,
            amount=config.PRICE_STANDARD_GRN,
            order_reference=order_ref,
            product_name="Секрет Клуб — Стандарт 1 міс (кастомний рекурент)",
        )
        try:
            r = requests.post("https://api.wayforpay.com/api", json=req, timeout=15)
            data = r.json() if r.text else {}
        except Exception as e:
            print(f"Custom recurring Charge error: {e}")
            continue

        if data.get("transactionStatus") == "Approved":
            from services.user_service import get_active_subscription
            from services.payment_notifications import tariff_renewed_message, send_payment_notification
            async with async_session() as session:
                sub_obj = await session.get(Subscription, sub.id)
                u = await session.get(User, user.id)
                if sub_obj:
                    sub_obj.is_active = False
                if u:
                    await activate_subscription(
                        session,
                        u,
                        is_trial=False,
                        rec_token=rec_token,
                        order_reference=order_ref,
                    )
                    renewed_sub = await get_active_subscription(session, u)
                    end_date = renewed_sub.end_date if renewed_sub else datetime.utcnow()
                else:
                    end_date = datetime.utcnow()
            send_payment_notification(user.telegram_id, tariff_renewed_message(end_date))
        else:
            next_retry = now + timedelta(hours=RETRY_HOURS[0])
            async with async_session() as session:
                sub_obj = await session.get(Subscription, sub.id)
                u = await session.get(User, user.id)
                if sub_obj:
                    sub_obj.is_active = False
                if u:
                    from database.models import UserStatus
                    u.status = UserStatus.FORMER_SUBSCRIBER.value
                session.add(
                    PaymentFailure(
                        user_id=user.id,
                        order_reference=order_ref,
                        rec_token=rec_token,
                        first_failure_at=now,
                        retry_index=0,
                        next_retry_at=next_retry,
                    )
                )
                await session.commit()
            dt = next_retry
            if KYIV_TZ:
                dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(KYIV_TZ) if getattr(dt, "tzinfo", None) is None else dt.astimezone(KYIV_TZ)
            next_d = dt.day
            next_m = MONTHS_UA[dt.month - 1]
            send_telegram(
                user.telegram_id,
                f"🚫 Автосписання відхилено.\n\n"
                f"Тариф: Стандарт\n"
                f"Вартість: {config.PRICE_STANDARD_GRN},00 ₴/міс\n"
                f"Наступна спроба: {next_d} {next_m}",
            )


async def remind_unpaid_after_5m_once():
    """Одне нагадування через 5 хв після старту оплати, якщо немає Approved."""
    from sqlalchemy import select

    now = datetime.utcnow()
    threshold = now - timedelta(minutes=5)

    async with async_session() as session:
        result = await session.execute(
            select(Payment, User)
            .join(User, User.id == Payment.user_id)
            .where(Payment.created_at <= threshold)
            .where(Payment.retry_count == 0)
        )
        rows = result.all()

        # Групуємо по користувачу: обираємо тільки найновіший unpaid-кандидат і шлемо максимум 1 нагадування.
        # Всі старі pending-записи цього користувача позначаємо як оброблені (retry_count=1), щоб не було спаму.
        per_user: dict[int, tuple[Payment, User, bool]] = {}
        for payment, user in rows:
            ref = (payment.order_reference or "")
            is_pay_open = ref.startswith("trial_") or ref.startswith("sub_") or ref.startswith("manual_sub_")
            if not is_pay_open:
                payment.retry_count = 1
                continue

            current = per_user.get(user.id)
            if current is None or (payment.created_at or datetime.min) > (current[0].created_at or datetime.min):
                per_user[user.id] = (payment, user, ref.startswith("trial_"))

        for uid, (latest_payment, user, is_trial) in per_user.items():
            # позначити всі необроблені нагадування юзера як оброблені (один пост-фактум sweep)
            for payment, row_user in rows:
                if row_user.id == uid:
                    payment.retry_count = 1

            if (latest_payment.transaction_status or "").lower() == "approved":
                continue
            if (user.status or "").lower() == "subscriber":
                continue

            tariff_code = "trial" if is_trial else "standard"
            base = (getattr(config, "PUBLIC_BASE_URL", "") or config.BASE_URL or "").rstrip("/")
            pay_url = "https://example.com/pay"
            try:
                from itsdangerous import URLSafeTimedSerializer
                s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
                token = s.dumps({"tid": int(user.telegram_id), "tariff": tariff_code})
                pay_url = f"{base}/pay?token={token}"
            except Exception:
                pass

            button_text = (
                "Отримати доступ за 1 грн"
                if is_trial
                else f"Тариф «Стандарт» — {config.PRICE_STANDARD_GRN} грн"
            )
            try:
                url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
                requests.post(
                    url,
                    json={
                        "chat_id": user.telegram_id,
                        "text": "Платіж не пройшов, спробуйте ще раз 🔄\n"
                                "Або напишіть в підтримку @sekret_manager",
                        "reply_markup": {"inline_keyboard": [[{"text": button_text, "url": pay_url}]]},
                    },
                    timeout=10,
                )
            except Exception:
                pass

        await session.commit()


def init_scheduler(bot_instance=None):
    if bot_instance:
        set_bot(bot_instance)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: asyncio.run(remind_charge_tomorrow()),
        "cron", hour=10, minute=0
    )
    scheduler.add_job(
        lambda: asyncio.run(remind_subscription_ending()),
        "cron", hour=10, minute=0
    )
    scheduler.add_job(
        lambda: asyncio.run(expire_ended_subscriptions()),
        "cron", hour=1, minute=0
    )
    scheduler.add_job(
        lambda: asyncio.run(remove_expired_from_group()),
        "cron", hour=2, minute=0
    )
    scheduler.add_job(
        lambda: asyncio.run(run_payment_retries()),
        "interval", minutes=10
    )
    # Fallback jobs: якщо native recurring WayForPay не спрацює, підхоплюємо списання самі.
    scheduler.add_job(
        lambda: asyncio.run(run_trial_to_standard_autocharges()),
        "interval", minutes=60,
    )
    scheduler.add_job(
        lambda: asyncio.run(run_custom_standard_recurring_autocharges()),
        "interval", minutes=60,
    )
    scheduler.add_job(
        lambda: asyncio.run(remind_unpaid_after_5m_once()),
        "interval", minutes=5
    )
    return scheduler
