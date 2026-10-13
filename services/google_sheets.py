"""
Інтеграція з Google Sheets для лідів
"""
import os
from datetime import datetime
from typing import Optional
import gspread
from google.oauth2.service_account import Credentials
import config
from zoneinfo import ZoneInfo

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client():
    """Отримати клієнт Google Sheets"""
    creds_file = config.GOOGLE_CREDENTIALS_FILE
    if not os.path.exists(creds_file):
        return None
    credentials = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    return gspread.authorize(credentials)


def add_lead(
    date_time: str | datetime,
    name: str,
    username: str,
    phone: str,
    status: str,
    email: str = "",
    sheet_id: Optional[str] = None,
):
    """
    Додати лід в Google таблицю
    Колонки: Дата, Ім'я, Нік Telegram, Номер телефону, Статус оплати, Email
    """
    sheet_id = sheet_id or config.GOOGLE_SHEET_ID
    if not sheet_id:
        return
    try:
        client = _get_client()
        if not client:
            return
        sheet = client.open_by_key(sheet_id).sheet1
        kyiv = ZoneInfo("Europe/Kyiv")
        if isinstance(date_time, datetime):
            dt_str = date_time.astimezone(kyiv).strftime("%d.%m.%Y %H:%M")
        else:
            dt_str = (date_time or "").strip()
            if not dt_str:
                dt_str = datetime.now(tz=kyiv).strftime("%d.%m.%Y %H:%M")

        row = [dt_str, name, username, phone, status, email or "—"]

        try:
            records = sheet.get_all_records()
        except Exception:
            records = []

        existing_row_idx = None
        for idx, record in enumerate(records, start=2):
            nick_val = str(record.get("Нік Telegram", record.get("Нік", record.get("username", ""))))
            phone_val = str(record.get("Номер телефону", record.get("phone", "")))
            if username and nick_val == username:
                existing_row_idx = idx
                break
            if phone and phone not in ("", "—") and phone_val == phone:
                existing_row_idx = idx
                break

        if existing_row_idx:
            cell_range = f"A{existing_row_idx}:F{existing_row_idx}"
            sheet.update(cell_range, [row])
        else:
            sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"Google Sheets error: {e}")


def update_lead_status(telegram_id: int, new_status: str, sheet_id: Optional[str] = None):
    """Оновити статус ліда за telegram_id (якщо є відповідність)"""
    sheet_id = sheet_id or config.GOOGLE_SHEET_ID
    if not sheet_id:
        return
    try:
        client = _get_client()
        if not client:
            return
        sheet = client.open_by_key(sheet_id).sheet1
        # Пошук по колонці з username (нік може містити telegram_id)
        records = sheet.get_all_records()
        for i, record in enumerate(records):
            nick = str(record.get("Нік Telegram", record.get("Нік", record.get("username", ""))))
            if str(telegram_id) in nick:
                sheet.update_cell(i + 2, 5, new_status)
                break
    except Exception as e:
        print(f"Google Sheets update error: {e}")
