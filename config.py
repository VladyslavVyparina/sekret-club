"""
Конфігурація бота Секрет Клуб
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "sekret_method_club_bot")
CLUB_GROUP_ID = int(os.getenv("CLUB_GROUP_ID", "-1003852181768"))
CLUB_GROUP_LINK = os.getenv("CLUB_GROUP_LINK", "https://t.me/+abufaCERr2I2ZWJi")

# Аудит — Google Forms
AUDIT_FORM_URL = os.getenv(
    "AUDIT_FORM_URL",
    "https://docs.google.com/forms/d/e/1FAIpQLSfiaY7J5t94v6ARlPR5jEPzOf963LCzJO_flLEEr9x8tFzeuA/viewform?usp=header",
)

# Текстові меню з посиланням у повідомленні (прев’ю як у базі знань)
INSTRUCTION_DOC_URL = os.getenv("INSTRUCTION_DOC_URL", "").strip()
OFFER_DOC_URL = os.getenv("OFFER_DOC_URL", "").strip()

# WayForPay
WAYFORPAY_MERCHANT_ACCOUNT = os.getenv("WAYFORPAY_MERCHANT", "")
WAYFORPAY_SECRET_KEY = os.getenv("WAYFORPAY_SECRET", "")
WAYFORPAY_DOMAIN = os.getenv("WAYFORPAY_DOMAIN", "sekret-club.com")
WAYFORPAY_MERCHANT_PASSWORD = os.getenv("WAYFORPAY_MERCHANT_PASSWORD", "")

PRICE_TRIAL_GRN = 1
TRIAL_DAYS = 14
SUBSCRIPTION_DAYS = 30
PRICE_STANDARD_GRN = 249

# Retry schedule (дні від основного списання)
RETRY_SCHEDULE = [0, 2, 4, 7, 11, 14]
RETRY_INTERVALS_HOURS = {0: 0, 2: 48, 4: 48, 7: 72, 11: 96, 14: 72}

# Google Sheets
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Admin
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
ADMIN_PANEL_SECRET = os.getenv("ADMIN_PANEL_SECRET", "change_me_secret_key")

# Public URLs / платежі
# Важливо: це має бути публічний https домен (без IP), напр. https://sekret-club.com
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip() or f"https://{os.getenv('WAYFORPAY_DOMAIN', 'sekret-club.com')}"
# Секрет для підписаних платіжних лінків (щоб не світити telegram_id в URL)
PAYLINK_SECRET = os.getenv("PAYLINK_SECRET", "").strip() or ADMIN_PANEL_SECRET

# Server — IP:порт де крутиться run_web.py (порт 5000)
BASE_URL = os.getenv("BASE_URL", "http://173.242.57.2:5000")
WEBHOOK_PATH = "/webhook/wayforpay"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///sekret_club.db")
