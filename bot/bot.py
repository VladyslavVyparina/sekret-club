"""
Telegram бот Секрет Клуб
"""
import asyncio
import logging
from collections import defaultdict
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from database.database import init_db, async_session
from database.models import UserStatus, Content, Lesson, ContentType
from services.user_service import (
    get_or_create_user,
    get_user,
    user_has_active_subscription,
    get_active_subscription,
    cancel_subscription,
    get_user_status,
)
from services.google_sheets import add_lead
from services.settings_service import get_setting
from keyboards import (
    inline_menu_kb,
    knowledge_base_main,
    courses_list,
    course_lessons,
    back_to_lessons_kb,
    back_to_menu_kb,
    audit_kb,
    streams_list,
    back_to_streams_kb,
    back_to_materials_kb,
    back_to_books_kb,
    subscription_kb,
    cancel_subscription_confirm,
    join_club_button,
)
from data.knowledge_base import KNOWLEDGE_BASE, get_course, get_lesson, find_lesson_and_course
from services.content_messages import (
    parse_attachments_json,
    send_content_bundle,
    clean_display_title,
    message_kwargs_for_link_preview,
)
from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        link_preview=LinkPreviewOptions(is_disabled=False),
    ),
)
dp = Dispatcher()
_TEMP_CONTENT_MSGS: dict[int, list[int]] = defaultdict(list)

# Унікальне посилання для trial: https://t.me/BOT_USERNAME?start=trial
TRIAL_START_PARAM = "trial"


def pay_url(telegram_id: int, trial: bool) -> str:
    """URL для оплати (HTTPS домен, без telegram_id у відкритому вигляді)."""
    from itsdangerous import URLSafeTimedSerializer

    base = (getattr(config, "PUBLIC_BASE_URL", "") or config.BASE_URL or "").rstrip("/")
    if not base:
        logger.warning("PUBLIC_BASE_URL/BASE_URL не задано в .env — оплата не працюватиме")
        return "https://example.com/configure-base-url"
    tariff = "trial" if trial else "standard"
    s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
    token = s.dumps({"tid": int(telegram_id), "tariff": tariff})
    return f"{base}/pay?token={token}"


def _show_main_menu(msg: Message, has_sub: bool):
    """Показати головне меню — inline меню замість reply keyboard"""
    kb = inline_menu_kb(has_sub)
    return msg.answer("Оберіть пункт меню:", reply_markup=kb, protect_content=False)


def _pay_kb(url: str, button_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=url)]])


AUDIT_MESSAGE_TEXT = (
    "🎯 Замовити аудит життя\n\n"
    "Заповніть заявку на Аудит-сесію — форма нижче (кнопка або посилання)."
)


def _display_course_title(title: str) -> str:
    """Назва курсу для відображення — без зайвого префіксу «Курс "»."""
    s = (title or "").strip()
    if s.startswith('Курс "') and s.endswith('"'):
        return s[6:-1].strip()
    return s


def _days_remaining(end_date) -> int:
    from datetime import datetime
    # ceil щоб для trial одразу показувалось 14 днів (а не 13 через різницю в годинах)
    import math
    delta = end_date - datetime.utcnow()
    seconds = delta.total_seconds()
    days = math.ceil(seconds / 86400) if seconds > 0 else 0
    return max(0, int(days))


def _std_price() -> int:
    return int(config.PRICE_STANDARD_GRN)


async def _cleanup_temp_content_messages(chat_id: int):
    ids = _TEMP_CONTENT_MSGS.get(chat_id) or []
    if not ids:
        return
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    _TEMP_CONTENT_MSGS[chat_id] = []


def _remember_temp_content_messages(chat_id: int, message_ids: list[int]):
    if not message_ids:
        return
    _TEMP_CONTENT_MSGS[chat_id].extend(message_ids)


async def _show_subscription(message, user_id: int, status: str, has_sub: bool):
    """Показати розділ Підписка. Якщо скасовано — не показувати дату наступного списання."""
    if has_sub:
        async with async_session() as session:
            user = await get_user(session, user_id)
            sub = await get_active_subscription(session, user) if user else None
            tariff_standard = await get_setting(session, "tariff_standard_name", "Стандарт")
            tariff_trial = await get_setting(session, "tariff_trial_name", "Trial")
        if sub:
            end_str = sub.end_date.strftime("%d.%m.%Y")
            days_left = _days_remaining(sub.end_date)
            if sub.is_trial:
                sub_name = f"{tariff_trial} (14 днів)"
                price_line = "Вартість: 1 грн / 14 днів"
                remain_line = f"Залишилось днів: {days_left}"
            else:
                sub_name = tariff_standard
                price_line = f"Вартість: {_std_price()} грн / міс."
                remain_line = f"Залишилось днів: {days_left}"
            after_trial_standard = (not sub.is_trial) and bool(user and user.has_used_trial)
            text = (
                f"📋 Ваш пакет підписки «{sub_name}»\n\n"
                f"{price_line}\n"
                f"Строк дії до: {end_str}\n"
                f"{remain_line}"
            )
            if after_trial_standard:
                text += (
                    "\n\nℹ️ Тариф за 1 грн завершився. "
                    f"Підписку змінено на «{tariff_standard}» за {_std_price()} грн/міс."
                )
            if not sub.cancelled:
                text += f"\n\nДата наступного списання: {end_str}"
            text += ""
        else:
            text = f"Ваш пакет підписки «{tariff_standard}»\nВартість: {_std_price()} грн / міс."
        await message.answer(text, reply_markup=subscription_kb(True), protect_content=False)
    else:
        is_former = status == UserStatus.FORMER_SUBSCRIBER.value
        pay_u = pay_url(user_id, False)
        async with async_session() as session:
            tariff_standard = await get_setting(session, "tariff_standard_name", "Стандарт")
        if is_former:
            pay_text = (
                "Щоб повернутися до клубу — оформіть підписку.\n\n"
                f"{_std_price()} грн/міс — повний доступ."
            )
            await message.answer(
                pay_text,
                reply_markup=_pay_kb(pay_u, f"Тариф «{tariff_standard}» — {_std_price()} грн"),
                protect_content=False,
            )
        else:
            pay_text = (
                "Оформіть підписку.\n\n"
                f"{_std_price()} грн/міс — повний доступ до клубу."
            )
            await message.answer(
                pay_text,
                reply_markup=_pay_kb(pay_u, f"Тариф «{tariff_standard}» — {_std_price()} грн"),
                protect_content=False,
            )


@dp.message(CommandStart(deep_link=True))
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    # start param: /start trial → trial, /start → None
    start_payload = msg.text.split(maxsplit=1)[1] if msg.text and len(msg.text.split()) > 1 else ""
    from_trial_link = start_payload.lower() == TRIAL_START_PARAM

    async with async_session() as session:
        user = await get_or_create_user(
            session, msg.from_user.id,
            username=msg.from_user.username,
            first_name=msg.from_user.first_name,
            last_name=msg.from_user.last_name,
        )
        has_sub = await user_has_active_subscription(session, user)
        status = await get_user_status(session, msg.from_user.id)

    add_lead(
        msg.date if msg.date else "",
        f"{msg.from_user.first_name or ''} {msg.from_user.last_name or ''}".strip() or "—",
        msg.from_user.username or str(msg.from_user.id),
        "—",
        "не підписник" if status == UserStatus.NOT_SUBSCRIBER.value else ("підписник" if status == UserStatus.SUBSCRIBER.value else "колишній підписник"),
    )

    if has_sub:
        await _show_main_menu(msg, True)
        return

    # Не підписник або колишній
    is_former = status == UserStatus.FORMER_SUBSCRIBER.value

    # Trial (1 грн) тільки для тих, хто прийшов по унікальному посиланню
    if from_trial_link and not is_former and not user.has_used_trial:
        async with async_session() as session:
            tariff_trial = await get_setting(session, "tariff_trial_name", "Trial")
        pay_u = pay_url(msg.from_user.id, True)
        trial_text = (
            "Вітаю! 👋\n\n"
            "Це бот клубу Sekret Club.\n\n"
            "Отримайте 14 днів доступу за 1 грн."
        )
        await msg.answer(
            trial_text,
            reply_markup=_pay_kb(pay_u, "Отримати доступ за 1 грн"),
            protect_content=False,
        )
    else:
        async with async_session() as session:
            tariff_standard = await get_setting(session, "tariff_standard_name", "Стандарт")
        pay_u = pay_url(msg.from_user.id, False)
        if is_former:
            pay_text = (
                "Раді вас знову бачити!\n\n"
                "Оформіть підписку, щоб повернутися до клубу.\n\n"
                f"{_std_price()} грн/міс — повний доступ."
            )
            await msg.answer(
                pay_text,
                reply_markup=_pay_kb(pay_u, f"Тариф «{tariff_standard}» — {_std_price()} грн"),
                protect_content=False,
            )
        else:
            pay_text = (
                "Вітаю! 👋\n\n"
                "Це бот клубу Sekret Club.\n\n"
                "Оформіть підписку, щоб отримати повний доступ до матеріалів та групи."
            )
            await msg.answer(
                pay_text,
                reply_markup=_pay_kb(pay_u, f"Тариф «{tariff_standard}» — {_std_price()} грн"),
                protect_content=False,
            )

    # Для користувачів без підписки головне меню не показуємо (тільки команди /...)


@dp.message(Command("menu"))
async def cmd_menu(msg: Message):
    """Команда /menu — головне меню"""
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await msg.answer(
            "Головне меню доступне лише після оформлення підписки.\n\n"
            "Натискайте, щоб оформити підписку ⬇️\n"
            "/subscriptions"
        )
        return
    await _show_main_menu(msg, True)


@dp.message(Command("subscribe"))
@dp.message(Command("subscriptions"))
@dp.message(Command("podpyska"))
async def cmd_subscribe(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
        status = await get_user_status(session, msg.from_user.id)
    await _show_subscription(msg, msg.from_user.id, status, has_sub)


@dp.message(Command("knowledge"))
@dp.message(Command("baza"))
async def cmd_knowledge(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await msg.answer("База знань доступна лише підписникам.")
        return
    await msg.answer(
        "📚 База знань – це всі навчальні матеріали клубу. Оберіть, що вас цікавить:",
        reply_markup=knowledge_base_main(),
        protect_content=False,
    )


@dp.message(Command("instruction"))
@dp.message(Command("instructions"))
@dp.message(Command("instrukciya"))
async def cmd_instruction(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await msg.answer("Інструкція доступна лише підписникам.")
        return
    if getattr(config, "INSTRUCTION_DOC_URL", ""):
        t = f"📖 Інструкція до клубу та бота:\n\n{config.INSTRUCTION_DOC_URL}"
        await msg.answer(t, **message_kwargs_for_link_preview(t))
    else:
        await msg.answer("📖 Інструкція до клубу та бота:\n\n[Тут може бути відео або посилання]", protect_content=False)


@dp.message(Command("offer"))
@dp.message(Command("oferta"))
async def cmd_offer(msg: Message):
    if getattr(config, "OFFER_DOC_URL", ""):
        t = f"📄 Договір оферти:\n\n{config.OFFER_DOC_URL}"
        await msg.answer(t, **message_kwargs_for_link_preview(t))
    else:
        await msg.answer("📄 Договір оферти:\n\n[Посилання на документ]", protect_content=False)


@dp.message(Command("audit"))
async def cmd_audit(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await msg.answer("Аудит доступний лише підписникам.")
        return
    audit_text = f"{AUDIT_MESSAGE_TEXT}\n\n{config.AUDIT_FORM_URL}"
    await msg.answer(
        audit_text,
        reply_markup=audit_kb(config.AUDIT_FORM_URL),
        **message_kwargs_for_link_preview(audit_text),
    )


@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    """Адмін-панель — посилання для адмінів"""
    if msg.from_user.id not in (config.ADMIN_IDS or []):
        await msg.answer("⛔ Немає доступу до адмін-панелі.")
        return
    base = ((getattr(config, "PUBLIC_BASE_URL", "") or config.BASE_URL or "")).rstrip("/")
    secret = config.ADMIN_PANEL_SECRET or "change_me_secret_key"
    url = f"{base}/admin?secret={secret}" if base else "Вкажіть BASE_URL в .env"
    admin_text = f"🔐 Адмін-панель:\n{url}"
    if url.startswith("http"):
        await msg.answer(admin_text, **message_kwargs_for_link_preview(admin_text))
    else:
        await msg.answer(admin_text)


@dp.message(Command("admin_clear_me"))
async def cmd_admin_clear_me(msg: Message):
    """Адмін: скинути себе в «не підписник» для тесту оплати"""
    if msg.from_user.id not in (config.ADMIN_IDS or []):
        return
    from database.models import Subscription, UserStatus
    from sqlalchemy import delete, update
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        if user:
            await session.execute(delete(Subscription).where(Subscription.user_id == user.id))
            user.status = UserStatus.NOT_SUBSCRIBER.value
            user.rec_token = None
            user.order_reference = None
            user.has_used_trial = False
            await session.commit()
    await msg.answer("✅ Скинуто. Ви тепер «не підписник». Напишіть /start для перевірки оплати.")


@dp.message(Command("admin_test_sub"))
async def cmd_admin_test_sub(msg: Message):
    """Адмін-команда: отримати підписку для тесту без оплати"""
    if msg.from_user.id not in (config.ADMIN_IDS or []):
        return
    from datetime import datetime, timedelta
    from database.models import Subscription
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        if not user:
            await get_or_create_user(
                session, msg.from_user.id,
                username=msg.from_user.username,
                first_name=msg.from_user.first_name,
                last_name=msg.from_user.last_name,
            )
            user = await get_user(session, msg.from_user.id)
        sub = Subscription(
            user_id=user.id,
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=30),
            is_trial=False,
            is_active=True,
        )
        from database.models import UserStatus
        user.status = UserStatus.SUBSCRIBER.value
        session.add(sub)
        await session.commit()
    await msg.answer("✅ Тестова підписка активована на 30 днів. Напишіть /start")


# Кнопки меню (текст)
@dp.message(F.text == "📚 База знань")
async def kb_menu(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await msg.answer("База знань доступна лише підписникам. Оформіть підписку.")
        return
    await msg.answer(
        "📚 База знань – це всі навчальні матеріали клубу. Оберіть, що вас цікавить:",
        reply_markup=knowledge_base_main(),
        protect_content=False,
    )


@dp.message(F.text == "📋 Підписка")
async def sub_menu(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
        status = await get_user_status(session, msg.from_user.id)
    await _show_subscription(msg, msg.from_user.id, status, has_sub)


@dp.message(F.text == "📖 Інструкція")
async def instruction_menu(msg: Message):
    if getattr(config, "INSTRUCTION_DOC_URL", ""):
        t = f"📖 Інструкція до клубу та бота:\n\n{config.INSTRUCTION_DOC_URL}"
        await msg.answer(t, **message_kwargs_for_link_preview(t))
    else:
        await msg.answer("📖 Інструкція до клубу та бота:\n\n[Тут може бути відео або посилання]", protect_content=False)


@dp.message(F.text == "📄 Договір оферти")
async def offer_menu(msg: Message):
    if getattr(config, "OFFER_DOC_URL", ""):
        t = f"📄 Договір оферти:\n\n{config.OFFER_DOC_URL}"
        await msg.answer(t, **message_kwargs_for_link_preview(t))
    else:
        await msg.answer("📄 Договір оферти:\n\n[Посилання на документ]", protect_content=False)


@dp.message(F.text == "🎯 Замовити аудит життя")
async def audit_menu(msg: Message):
    async with async_session() as session:
        user = await get_user(session, msg.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await msg.answer("Аудит доступний лише підписникам.")
        return
    audit_text = f"{AUDIT_MESSAGE_TEXT}\n\n{config.AUDIT_FORM_URL}"
    await msg.answer(
        audit_text,
        reply_markup=audit_kb(config.AUDIT_FORM_URL),
        **message_kwargs_for_link_preview(audit_text),
    )


# Callbacks — inline меню
@dp.callback_query(F.data == "menu_sub")
async def cb_menu_sub(cb: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, cb.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
        status = await get_user_status(session, cb.from_user.id)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await _show_subscription(cb.message, cb.from_user.id, status, has_sub)
    await cb.answer()


@dp.callback_query(F.data == "menu_offer")
async def cb_menu_offer(cb: CallbackQuery):
    kb = back_to_menu_kb()
    if getattr(config, "OFFER_DOC_URL", ""):
        t = f"📄 Договір оферти:\n\n{config.OFFER_DOC_URL}"
        opts = message_kwargs_for_link_preview(t, for_edit_message=True)
        try:
            await cb.message.edit_text(t, reply_markup=kb, **opts)
        except Exception:
            await cb.message.delete()
            await cb.message.answer(t, reply_markup=kb, **message_kwargs_for_link_preview(t))
    else:
        try:
            await cb.message.edit_text("📄 Договір оферти:\n\n[Посилання на документ]", reply_markup=kb)
        except Exception:
            await cb.message.delete()
            await cb.message.answer("📄 Договір оферти:\n\n[Посилання на документ]", reply_markup=kb, protect_content=False)
    await cb.answer()


@dp.callback_query(F.data == "menu_instruction")
async def cb_menu_instruction(cb: CallbackQuery):
    kb = back_to_menu_kb()
    if getattr(config, "INSTRUCTION_DOC_URL", ""):
        t = f"📖 Інструкція до клубу та бота:\n\n{config.INSTRUCTION_DOC_URL}"
        opts = message_kwargs_for_link_preview(t, for_edit_message=True)
        try:
            await cb.message.edit_text(t, reply_markup=kb, **opts)
        except Exception:
            await cb.message.delete()
            await cb.message.answer(t, reply_markup=kb, **message_kwargs_for_link_preview(t))
    else:
        try:
            await cb.message.edit_text("📖 Інструкція до клубу та бота:\n\n[Тут може бути відео або посилання]", reply_markup=kb)
        except Exception:
            await cb.message.delete()
            await cb.message.answer("📖 Інструкція до клубу та бота:\n\n[Тут може бути відео або посилання]", reply_markup=kb, protect_content=False)
    await cb.answer()


@dp.callback_query(F.data == "menu_audit")
async def cb_menu_audit(cb: CallbackQuery):
    kb = audit_kb(config.AUDIT_FORM_URL)
    text = f"{AUDIT_MESSAGE_TEXT}\n\n{config.AUDIT_FORM_URL}"
    opts = message_kwargs_for_link_preview(text, for_edit_message=True)
    try:
        await cb.message.edit_text(text, reply_markup=kb, **opts)
    except Exception:
        await cb.message.delete()
        await cb.message.answer(text, reply_markup=kb, **message_kwargs_for_link_preview(text))
    await cb.answer()


@dp.callback_query(F.data == "menu_kb")
async def cb_menu_kb(cb: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, cb.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    if not has_sub:
        await cb.answer("База знань доступна лише підписникам.", show_alert=True)
        return
    try:
        await cb.message.edit_text(
            "📚 База знань – оберіть категорію:",
            reply_markup=knowledge_base_main(),
        )
    except Exception:
        await cb.message.delete()
        await cb.message.answer("📚 База знань – оберіть категорію:", reply_markup=knowledge_base_main(), protect_content=False)
    await cb.answer()


# Callbacks
@dp.callback_query(F.data == "join_group")
async def cb_join_group(cb: CallbackQuery):
    """Перейти в групу — віддаємо кнопку з URL після перевірки підписки."""
    async with async_session() as session:
        user = await get_user(session, cb.from_user.id)
        has_access = await user_has_active_subscription(session, user) if user else False
    if not has_access:
        await cb.answer("Доступ до групи потребує активної підписки.", show_alert=True)
        return
    club_link = getattr(config, "CLUB_GROUP_LINK", None)
    if club_link:
        group_text = f"Натисніть кнопку нижче, щоб перейти в групу:\n\n{club_link}"
        await cb.message.answer(
            group_text,
            reply_markup=join_club_button(club_link),
            **message_kwargs_for_link_preview(group_text),
        )
        await cb.answer()
        return
    await cb.answer("Помилка. Посилання на групу відсутнє.", show_alert=True)


@dp.callback_query(F.data == "menu_back")
async def cb_menu_back(cb: CallbackQuery):
    """Назад до головного меню — показуємо inline меню, видаляємо попереднє"""
    async with async_session() as session:
        user = await get_user(session, cb.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await cb.message.answer("Оберіть пункт меню:", reply_markup=inline_menu_kb(has_sub), protect_content=False)
    await cb.answer()


@dp.callback_query(F.data == "kb_main")
async def cb_kb_main(cb: CallbackQuery):
    """База знань — видаляємо попереднє меню, показуємо нове"""
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        await cb.message.edit_text(
            "📚 База знань – оберіть категорію:",
            reply_markup=knowledge_base_main(),
        )
    except Exception:
        await cb.message.delete()
        await cb.message.answer("📚 База знань – оберіть категорію:", reply_markup=knowledge_base_main(), protect_content=False)
    await cb.answer()


async def _load_content_list(content_type: str):
    """Допоміжний лоадер списку контенту (курси, ефіри, матеріали, книги)."""
    async with async_session() as session:
        result = await session.execute(
            select(Content)
            .where(Content.content_type == content_type)
            .order_by(Content.sort_order.asc(), Content.id.desc())
        )
        return list(result.scalars().all())


@dp.callback_query(F.data == "kb_courses")
async def cb_courses(cb: CallbackQuery):
    """Меню вибору курсу (з БД Content, а не зі статичного словника)."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    courses = await _load_content_list(ContentType.COURSE.value)
    if not courses:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="kb_main")]]
        )
        text = "Поки що курсів немає."
    else:
        items = [{"id": str(c.id), "title": c.title} for c in courses]
        kb = courses_list(items)
        text = "Оберіть курс:"

    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer(text, reply_markup=kb, protect_content=False)
    await cb.answer()


@dp.callback_query(F.data.startswith("course_"))
async def cb_course_detail(cb: CallbackQuery):
    """Всередині конкретного курсу — показ картки курсу + список уроків."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        _, raw_id = cb.data.split("_", 1)
        course_id = int(raw_id)
    except Exception:
        await cb.answer("Некоректний курс.", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Content).where(Content.id == course_id))
        course = result.scalar_one_or_none()
        if not course:
            await cb.answer("Курс не знайдено.", show_alert=True)
            return
        lessons_result = await session.execute(
            select(Lesson)
            .where(Lesson.content_id == course.id)
            .order_by(Lesson.sort_order.asc(), Lesson.id.desc())
        )
        lessons = list(lessons_result.scalars().all())

    atts = parse_attachments_json(getattr(course, "attachments_json", None))
    has_lessons = bool(lessons)
    lessons_kb = None
    if has_lessons:
        items = [{"id": str(l.id), "title": l.title} for l in lessons]
        lessons_kb = course_lessons(items, str(course.id))
    else:
        lessons_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="kb_courses")]]
        )

    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    sent = await send_content_bundle(
        bot,
        cb.from_user.id,
        course=None,
        title=clean_display_title(course.title),
        description=course.description,
        attachments=atts,
        legacy_video_file_id=course.file_id,
        legacy_photo_file_id=None,
        legacy_video_url=course.video_url,
        legacy_link=getattr(course, "link", None),
        reply_markup=lessons_kb,
    )
    _remember_temp_content_messages(cb.from_user.id, sent)
    await cb.answer()


@dp.callback_query(F.data.startswith("lesson_"))
async def cb_lesson(cb: CallbackQuery):
    """Показати урок курсу. Головне меню не показуємо, тільки кнопка «Назад до уроків»."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        _, course_raw, lesson_raw = cb.data.split("_", 2)
        course_id = int(course_raw)
        lesson_id = int(lesson_raw)
    except Exception:
        await cb.answer("Некоректний урок.", show_alert=True)
        return

    async with async_session() as session:
        l_result = await session.execute(
            select(Lesson).where(Lesson.id == lesson_id).where(Lesson.content_id == course_id)
        )
        lesson = l_result.scalar_one_or_none()
        c_result = await session.execute(select(Content).where(Content.id == course_id))
        course = c_result.scalar_one_or_none()

    if not lesson:
        await cb.answer("Урок не знайдено.", show_alert=True)
        return

    # При відкритті уроку попереднє меню видаляємо
    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    kb = back_to_lessons_kb(str(course_id))
    atts = parse_attachments_json(getattr(lesson, "attachments_json", None))
    sent = await send_content_bundle(
        bot,
        cb.from_user.id,
        course=None,
        title=clean_display_title(lesson.title),
        description=lesson.description,
        attachments=atts,
        legacy_video_file_id=lesson.file_id,
        legacy_photo_file_id=lesson.photo_file_id,
        legacy_video_url=lesson.video_url,
        legacy_link=getattr(lesson, "link", None),
        reply_markup=kb,
    )
    _remember_temp_content_messages(cb.from_user.id, sent)

    await cb.answer()


@dp.callback_query(F.data == "kb_streams")
async def cb_streams(cb: CallbackQuery):
    """Список ефірів."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    streams = await _load_content_list(ContentType.STREAM.value)
    if not streams:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="kb_main")]]
        )
        text = "Поки що ефірів немає."
    else:
        items = [{"id": str(s.id), "title": s.title} for s in streams]
        kb = streams_list(items, prefix="stream")
        text = "Оберіть ефір:"

    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer(text, reply_markup=kb, protect_content=False)
    await cb.answer()


@dp.callback_query(F.data.startswith("stream_"))
async def cb_stream(cb: CallbackQuery):
    """Показати конкретний ефір. Попереднє меню видаляємо."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        _, raw_id = cb.data.split("_", 1)
        stream_id = int(raw_id)
    except Exception:
        await cb.answer("Некоректний ефір.", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Content).where(Content.id == stream_id))
        item = result.scalar_one_or_none()

    if not item:
        await cb.answer("Ефір не знайдено.", show_alert=True)
        return

    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    atts = parse_attachments_json(getattr(item, "attachments_json", None))
    sent = await send_content_bundle(
        bot,
        cb.from_user.id,
        course=None,
        title=item.title,
        description=item.description,
        attachments=atts,
        legacy_video_file_id=item.file_id,
        legacy_photo_file_id=None,
        legacy_video_url=item.video_url,
        legacy_link=getattr(item, "link", None),
        reply_markup=back_to_streams_kb(),
    )
    _remember_temp_content_messages(cb.from_user.id, sent)
    await cb.answer()


@dp.callback_query(F.data == "kb_materials")
async def cb_materials(cb: CallbackQuery):
    """Корисні матеріали — список."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    materials = await _load_content_list(ContentType.MATERIAL.value)
    if not materials:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="kb_main")]]
        )
        text = "Поки що корисних матеріалів немає."
    else:
        items = [{"id": str(m.id), "title": m.title} for m in materials]
        kb = streams_list(items, prefix="material")
        text = "Оберіть матеріал:"

    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer(text, reply_markup=kb, protect_content=False)
    await cb.answer()


@dp.callback_query(F.data.startswith("material_"))
async def cb_material(cb: CallbackQuery):
    """Окремий корисний матеріал."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        _, raw_id = cb.data.split("_", 1)
        material_id = int(raw_id)
    except Exception:
        await cb.answer("Некоректний матеріал.", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Content).where(Content.id == material_id))
        item = result.scalar_one_or_none()

    if not item:
        await cb.answer("Матеріал не знайдено.", show_alert=True)
        return

    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    atts = parse_attachments_json(getattr(item, "attachments_json", None))
    sent = await send_content_bundle(
        bot,
        cb.from_user.id,
        course=None,
        title=item.title,
        description=item.description,
        attachments=atts,
        legacy_video_file_id=item.file_id,
        legacy_photo_file_id=None,
        legacy_video_url=item.video_url,
        legacy_link=getattr(item, "link", None),
        reply_markup=back_to_materials_kb(),
    )
    _remember_temp_content_messages(cb.from_user.id, sent)
    await cb.answer()


@dp.callback_query(F.data == "kb_books")
async def cb_books(cb: CallbackQuery):
    """Список книг."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    books = await _load_content_list(ContentType.BOOK.value)
    if not books:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="kb_main")]]
        )
        text = "Поки що книг немає."
    else:
        items = [{"id": str(b.id), "title": b.title} for b in books]
        kb = streams_list(items, prefix="book")
        text = "Книги рекомендовані автором:"

    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer(text, reply_markup=kb, protect_content=False)
    await cb.answer()


@dp.callback_query(F.data.startswith("book_"))
async def cb_book(cb: CallbackQuery):
    """Окрема книга."""
    await _cleanup_temp_content_messages(cb.from_user.id)
    try:
        _, raw_id = cb.data.split("_", 1)
        book_id = int(raw_id)
    except Exception:
        await cb.answer("Некоректна книга.", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Content).where(Content.id == book_id))
        item = result.scalar_one_or_none()

    if not item:
        await cb.answer("Книгу не знайдено.", show_alert=True)
        return

    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    atts = parse_attachments_json(getattr(item, "attachments_json", None))
    sent = await send_content_bundle(
        bot,
        cb.from_user.id,
        course=None,
        title=item.title,
        description=item.description,
        attachments=atts,
        legacy_video_file_id=item.file_id,
        legacy_photo_file_id=None,
        legacy_video_url=item.video_url,
        legacy_link=getattr(item, "link", None),
        reply_markup=back_to_books_kb(),
    )
    _remember_temp_content_messages(cb.from_user.id, sent)
    await cb.answer()


@dp.callback_query(F.data == "sub_cancel")
async def cb_sub_cancel(cb: CallbackQuery):
    """Показати підтвердження скасування підписки."""
    try:
        await cb.message.edit_text(
            "Ви впевнені, що хочете скасувати підписку?",
            reply_markup=cancel_subscription_confirm(),
        )
    except Exception:
        await cb.message.answer(
            "Ви впевнені, що хочете скасувати підписку?",
            reply_markup=cancel_subscription_confirm(),
        )
    await cb.answer()


@dp.callback_query(F.data == "sub_cancel_no")
async def cb_sub_cancel_no(cb: CallbackQuery):
    """Не скасовувати підписку — повернутися до розділу Підписка."""
    async with async_session() as session:
        user = await get_user(session, cb.from_user.id)
        has_sub = await user_has_active_subscription(session, user) if user else False
        status = await get_user_status(session, cb.from_user.id)

    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    await _show_subscription(cb.message, cb.from_user.id, status, has_sub)
    await cb.answer("Скасування відмінено.")


@dp.callback_query(F.data == "sub_cancel_yes")
async def cb_sub_cancel_yes(cb: CallbackQuery):
    """Підтвердити скасування підписки та повернути користувача в головне меню."""
    async with async_session() as session:
        user = await get_user(session, cb.from_user.id)
        if not user:
            await cb.answer("Користувача не знайдено.", show_alert=True)
            return
        success = await cancel_subscription(session, user)
        has_sub = await user_has_active_subscription(session, user)

    try:
        await cb.message.delete()
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Текст-підтвердження
    await cb.message.answer("Підписку скасовано. Дякуємо!", protect_content=False)

    # Автоматичний перехід у головне меню (доступ залишається до кінця оплаченого періоду)
    if has_sub:
        await _show_main_menu(cb.message, True)

    await cb.answer()


async def main():
    """Точка входу для run_bot.py"""
    from database.database import init_db
    from scheduler_tasks import init_scheduler

    await init_db()

    # Показуємо slash-команди всім, але доступ до розділів контролюється перевіркою підписки в хендлерах.
    try:
        from aiogram.types import BotCommandScopeDefault, BotCommandScopeAllPrivateChats

        commands = [
            BotCommand(command="start", description="Почати роботу з ботом"),
            BotCommand(command="menu", description="Головне меню"),
            BotCommand(command="subscriptions", description="Підписка"),
            BotCommand(command="baza", description="База знань"),
            BotCommand(command="instruction", description="Інструкція"),
            BotCommand(command="oferta", description="Договір оферти"),
            BotCommand(command="audit", description="Замовити аудит"),
        ]
        await bot.delete_my_commands(scope=BotCommandScopeDefault())
        await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(
            commands,
            scope=BotCommandScopeDefault(),
        )
        await bot.set_my_commands(
            commands,
            scope=BotCommandScopeAllPrivateChats(),
        )
    except Exception as e:
        logger.warning(f"Не вдалося встановити команди бота: {e}")

    # Запускаємо планувальник задач (expiry/removal/retries) в цьому ж процесі бота.
    try:
        scheduler = init_scheduler(bot)
        scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning(f"Не вдалося запустити scheduler: {e}")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
