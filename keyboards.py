"""
Клавіатури бота
"""
import config
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def menu_keyboard(is_subscriber: bool) -> ReplyKeyboardMarkup:
    """Меню - різне для підписників та ні (без Підтримки)"""
    if is_subscriber:
        buttons = [
            [KeyboardButton(text="📚 База знань")],
            [KeyboardButton(text="📋 Підписка")],
            [KeyboardButton(text="📖 Інструкція")],
            [KeyboardButton(text="📄 Договір оферти")],
            [KeyboardButton(text="🎯 Замовити аудит життя")],
        ]
    else:
        buttons = [
            [KeyboardButton(text="📋 Підписка")],
            [KeyboardButton(text="📄 Договір оферти")],
        ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def inline_menu_kb(is_subscriber: bool) -> "InlineKeyboardMarkup":
    """Inline меню замість reply keyboard"""
    from aiogram.types import InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="📋 Підписка", callback_data="menu_sub")],
        [InlineKeyboardButton(text="📄 Договір оферти", callback_data="menu_offer")],
    ]
    if is_subscriber:
        buttons = [
            [InlineKeyboardButton(text="📚 База знань", callback_data="menu_kb")],
            [InlineKeyboardButton(text="📋 Підписка", callback_data="menu_sub")],
            [InlineKeyboardButton(text="📖 Інструкція", callback_data="menu_instruction")],
            [InlineKeyboardButton(text="📄 Договір оферти", callback_data="menu_offer")],
            [InlineKeyboardButton(text="🎯 Замовити аудит життя", callback_data="menu_audit")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]
    ])


def audit_kb(form_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Заявка на Аудит-сесію", url=form_url)],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")],
    ])


def knowledge_base_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📗 Курси", callback_data="kb_courses")],
        [InlineKeyboardButton(text="🎬 Ефіри", callback_data="kb_streams")],
        [InlineKeyboardButton(text="📎 Корисні матеріали", callback_data="kb_materials")],
        [InlineKeyboardButton(text="📚 Книги", callback_data="kb_books")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")],
    ])


def courses_list(courses: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in courses:
        builder.row(InlineKeyboardButton(text=c["title"], callback_data=f"course_{c['id']}"))
    builder.row(InlineKeyboardButton(text="⬅ Назад", callback_data="kb_main"))
    return builder.as_markup()


def course_lessons(lessons: list, course_id: str) -> InlineKeyboardMarkup:
    """Меню курсу з уроками — ▶️ Урок №N: [скорочена назва]"""
    builder = InlineKeyboardBuilder()
    for i, lesson in enumerate(lessons, 1):
        t = lesson['title']
        if ': ' in t:
            t = t.split(': ', 1)[1]
        t = (t or "").strip()
        short = (t[:35] + '...') if len(t) > 35 else t
        btn_text = f"▶️ Урок №{i}: {short}"
        builder.row(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"lesson_{course_id}_{lesson['id']}"
        ))
    builder.row(InlineKeyboardButton(text="⬅ Назад", callback_data="kb_courses"))
    return builder.as_markup()


def back_to_lessons_kb(course_id: str) -> InlineKeyboardMarkup:
    """Кнопка «Назад до лекцій» після відкриття лекції"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data=f"course_{course_id}")]
    ])


def streams_list(items: list, prefix: str = "stream") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(InlineKeyboardButton(text=item["title"], callback_data=f"{prefix}_{item['id']}"))
    builder.row(InlineKeyboardButton(text="⬅ Назад", callback_data="kb_main"))
    return builder.as_markup()


def back_to_streams_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="kb_streams")]
    ])


def back_to_materials_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="kb_materials")]
    ])


def back_to_books_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="kb_books")]
    ])


def subscription_kb(has_subscription: bool, pay_url: str = "") -> InlineKeyboardMarkup:
    if has_subscription:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати підписку", callback_data="sub_cancel")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")],
        ])
    buttons = [[InlineKeyboardButton(text="⬅ Назад", callback_data="menu_back")]]
    if pay_url:
        buttons.insert(
            0,
            [InlineKeyboardButton(text=f"Тариф «Стандарт» — {config.PRICE_STANDARD_GRN} грн", url=pay_url)],
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_subscription_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Так", callback_data="sub_cancel_yes")],
        [InlineKeyboardButton(text="❌ Ні", callback_data="sub_cancel_no")],
    ])


def payment_button(url: str) -> InlineKeyboardMarkup:
    """Тільки ціна + тариф на кнопці"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отримати доступ за 1 грн", url=url)],
    ])


def payment_button_standard(url: str) -> InlineKeyboardMarkup:
    """Тільки ціна + тариф на кнопці"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Тариф «Стандарт» — {config.PRICE_STANDARD_GRN} грн", url=url)],
    ])


def join_club_button(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти в групу Sekret Club", url=link)],
    ])
