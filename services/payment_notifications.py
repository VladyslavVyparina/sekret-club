"""
Повідомлення про автосписання та успішну оплату тарифу.
"""
from datetime import datetime

import config


def charge_tomorrow_message(charge_date: datetime, *, is_trial_period: bool) -> str:
    """За 1 день до автосписання (день 13 trial / день 29 місяця)."""
    date_str = charge_date.strftime("%d.%m.%Y")
    amount = int(config.PRICE_STANDARD_GRN)
    if is_trial_period:
        return (
            f"⏰ Нагадування: завтра ({date_str}) закінчується пробний період і буде "
            f"автоматичне списання {amount} грн за тариф «Стандарт»."
        )
    return (
        f"⏰ Нагадування: завтра ({date_str}) буде автоматичне списання {amount} грн "
        f"за продовження тарифу «Стандарт»."
    )


def tariff_renewed_message(end_date: datetime) -> str:
    """Після успішного списання / поновлення тарифу."""
    return (
        "✅ Ваш тариф було оплачено.\n\n"
        f"Тариф «Стандарт» оновлено. Доступ діє до {end_date.strftime('%d.%m.%Y')}."
    )


def send_payment_notification(chat_id: int, text: str) -> None:
    try:
        import requests

        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Payment notification send error: {e}")
