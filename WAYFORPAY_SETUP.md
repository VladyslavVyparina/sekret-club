# Що потрібно для роботи WayForPay

## 1. У файлі .env на сервері

```env
BASE_URL=http://IP_ВАШОГО_VPS
WAYFORPAY_MERCHANT=freelance_user_65cf444d78d4b
WAYFORPAY_SECRET=73bff90ebaef23615ee044b658104f6ac3783874
WAYFORPAY_DOMAIN=sekret-club.com
```

**BASE_URL** — IP або домен VPS, де запущено `run_web.py`. Без нього оплата не працюватиме.

Для закритої групи **CLUB_GROUP_LINK** можна не вказувати — після оплати користувач отримає повідомлення, що адмін додасть його до групи.

## 2. Кабінет WayForPay

- **Service URL (callback):** `http://ВАШ_IP/webhook/wayforpay`
- **Return URL:** можна залишити порожнім або вказати `https://t.me/ваш_бот`

## 3. Запуск

Обовʼязково мають працювати **обидва** процеси:

```bash
# Термінал 1 — бот
python3 run_bot.py

# Термінал 2 — web для оплати
python3 run_web.py
```

## 4. Логіка

- **Скасування підписки** — викликається WayForPay REMOVE, автосписання припиняється.
- **Не скасовано** — WayForPay списує щомісяця автоматично.
- **Нагадування** — за 3 дні до кінця підписки.
- **Неуспішна оплата** — повторні спроби: Day 0, 2, 4, 7, 11, 14.
