"""
Flask сервер: WayForPay + адмін-панель
"""
import asyncio
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, session, render_template_string
from functools import wraps

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from services.wayforpay import create_payment_link, verify_callback_signature
from database.database import async_session
from database.models import User, UserStatus, Subscription, Payment, PaymentFailure, PayLink
from services.user_service import get_user, activate_subscription, get_active_subscription
from services.google_sheets import add_lead
from database.models import Content, Lesson, Setting, ContentType, Tariff
from services.settings_service import get_setting, set_setting
from services.tariff_service import get_or_create_tariff
from services.content_seed import ensure_streams_seeded, ensure_materials_seeded, ensure_books_seeded
from data.knowledge_base import KNOWLEDGE_BASE
from services.content_messages import (
    attachments_to_json,
    parse_attachments_json,
    MAX_ATTACHMENTS_PER_SAVE,
    telegram_limits_hint,
)

# Retry: Day 0 (fail), 2, 4, 7, 11, 14 — інтервали в годинах після попередньої спроби
RETRY_HOURS = [48, 48, 72, 96, 72]
MONTHS_UA = ["січня", "лютого", "березня", "квітня", "травня", "червня",
             "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = None

app = Flask(__name__)
app.secret_key = config.ADMIN_PANEL_SECRET or "secret"

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

@app.route("/", methods=["GET"])
def index():
    """Лендінг-заглушка для домену (щоб не було 404 на головній)."""
    bot_link = f"https://t.me/{config.BOT_USERNAME}" if config.BOT_USERNAME else "https://t.me/sekret_club_bot"
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Sekret Club</title>
    <style>
      body {{
        margin:0;
        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background: radial-gradient(1200px 600px at 10% 10%, #223a6b 0%, rgba(34,58,107,0) 60%),
                    radial-gradient(900px 500px at 90% 30%, #1a2f57 0%, rgba(26,47,87,0) 55%),
                    linear-gradient(180deg, #0b1630 0%, #081022 100%);
        color:#fff;
        min-height:100vh;
        display:flex;
        align-items:center;
        justify-content:center;
        padding:24px;
      }}
      .card {{
        width:100%;
        max-width:560px;
        background:rgba(255,255,255,0.06);
        border:1px solid rgba(255,255,255,0.12);
        border-radius:18px;
        padding:22px 20px;
        box-shadow: 0 18px 60px rgba(0,0,0,0.35);
        backdrop-filter: blur(10px);
      }}
      h1 {{ margin:0 0 10px 0; font-size:22px; line-height:1.25; }}
      p {{ margin:0; opacity:0.9; line-height:1.55; }}
      a.btn {{
        display:inline-block;
        margin-top:14px;
        padding:10px 16px;
        border-radius:999px;
        background:#4CAF50;
        color:#fff;
        text-decoration:none;
        font-weight:600;
      }}
      .muted {{ margin-top:10px; font-size:13px; opacity:0.7; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Sekret Club</h1>
      <p>Оплата відкривається з бота після вибору тарифу.</p>
      <a class="btn" href="{bot_link}">Відкрити бота</a>
      <div class="muted">Якщо ви вже маєте посилання на оплату — відкрийте його напряму.</div>
    </div>
  </body>
</html>""", 200


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin" not in session and request.args.get("secret") != config.ADMIN_PANEL_SECRET:
            return "Unauthorized", 401
        if "admin" not in session:
            session["admin"] = True
        return f(*args, **kwargs)
    return decorated


ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Адмін-панель | Sekret Club</title>
<style>
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  max-width:1040px;
  margin:0 auto;
  padding:0;
  background:linear-gradient(135deg,#f5f7fa,#e4ecf7);
}
header{
  background:#262a3b;
  color:#fff;
  padding:18px 24px;
  border-radius:0 0 18px 18px;
  box-shadow:0 4px 16px rgba(0,0,0,0.25);
}
header h1{margin:0;font-size:22px;}
header p{margin:4px 0 0 0;font-size:13px;color:#d0d4e6;}
.wrapper{padding:24px;}
h2{color:#222;margin-top:0;margin-bottom:10px;}
.stats{display:flex;gap:20px;margin:20px 0;flex-wrap:wrap;}
.card{
  background:#fff;
  padding:18px 20px;
  border-radius:14px;
  box-shadow:0 2px 10px rgba(0,0,0,0.08);
  min-width:150px;
  position:relative;
  overflow:hidden;
}
.card::after{
  content:'';
  position:absolute;
  right:-40px;
  top:-40px;
  width:90px;height:90px;
  background:radial-gradient(circle at center,rgba(76,175,80,0.2),transparent 60%);
}
.card h3{margin:0 0 6px 0;font-size:13px;color:#777;text-transform:uppercase;letter-spacing:.06em;}
.card p{margin:0;font-size:22px;font-weight:700;color:#222;}
.box{
  background:#fff;
  padding:20px;
  border-radius:16px;
  box-shadow:0 2px 12px rgba(0,0,0,0.05);
  margin:20px 0;
}
label{font-weight:600;}
textarea{
  width:100%;height:120px;
  padding:8px;border-radius:8px;
  border:1px solid #cfd4e6;
  box-sizing:border-box;
  font-family:inherit;font-size:14px;
}
input[type=text],select,input[type=number]{
  width:100%;padding:8px;border-radius:8px;
  border:1px solid #cfd4e6;box-sizing:border-box;
  font-size:14px;
}
.segments{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;}
.segments label{font-weight:400;font-size:14px;}
.btn{
  display:inline-block;padding:10px 20px;
  background:#4CAF50;color:white;
  text-decoration:none;border-radius:999px;
  margin:5px 5px 0 0;border:none;cursor:pointer;
  font-size:14px;
}
.btn.secondary{background:#6c757d;}
.btn:hover{opacity:0.92;}
.info{margin-top:10px;color:#555;font-size:13px;}
.row{display:flex;gap:20px;flex-wrap:wrap;}
.col{flex:1 1 260px;}
</style>
</head>
<body>
<header>
  <h1>Адмін-панель Sekret Club</h1>
  <p>Управління базою, розсилками та статистикою</p>
</header>
<div class="wrapper">

<div class="box" style="margin-top:0;">
  <h2>Управління</h2>
  <p>
    <a class="btn secondary" href="/admin/content">Курси / уроки</a>
    <a class="btn secondary" href="/admin/streams_admin">Ефіри</a>
    <a class="btn secondary" href="/admin/materials_admin">Корисні матеріали</a>
    <a class="btn secondary" href="/admin/books_admin">Книги</a>
    <a class="btn secondary" href="/admin/tariffs">Тарифи (ціни)</a>
  </p>
</div>

<div class="stats">
  <div class="card">
    <h3>Всього юзерів</h3>
    <p>{{ stats.total }}</p>
  </div>
  <div class="card">
    <h3>Підписників</h3>
    <p>{{ stats.subscribers }}</p>
  </div>
  <div class="card">
    <h3>Колишніх</h3>
    <p>{{ stats.former }}</p>
  </div>
  <div class="card">
    <h3>Не підписників</h3>
    <p>{{ stats.not_sub }}</p>
  </div>
</div>

<div class="box">
  <h2>Розсилка</h2>
  <form method="post" action="/admin/broadcast" enctype="multipart/form-data">
    <div class="row">
      <div class="col">
        <label>Сегменти (можна кілька):</label>
        <div class="segments">
          {% set segs = selected_segments or ['subscribers'] %}
          <label><input type="checkbox" name="segments" value="subscribers" {% if 'subscribers' in segs %}checked{% endif %}> Підписники</label>
          <label><input type="checkbox" name="segments" value="former" {% if 'former' in segs %}checked{% endif %}> Колишні</label>
          <label><input type="checkbox" name="segments" value="not_sub" {% if 'not_sub' in segs %}checked{% endif %}> Не підписники</label>
        </div>
        <p class="info">Після вибору сегментів буде показано, скільки людей отримає розсилку.</p>
        {% if preview_count is not none %}
          <p class="info"><strong>Потрапить у розсилку:</strong> {{ preview_count }} користувачів.</p>
        {% endif %}
      </div>
      <div class="col">
        <label>Тип повідомлення:</label>
        {% set mt = msg_type or 'text' %}
        <select name="msg_type">
          <option value="text" {% if mt == 'text' %}selected{% endif %}>Текст</option>
          <option value="photo" {% if mt == 'photo' %}selected{% endif %}>Фото + текст</option>
          <option value="video" {% if mt == 'video' %}selected{% endif %}>Відео + текст</option>
        </select>
        <p style="margin-top:10px;">
          <label>Медіа (jpg, png, mp4):<br>
            <input type="file" name="media">
          </label>
        </p>
        <p class="info">Ліміт Telegram: до 4096 символів текст, ~1024 символи у підписі до фото/відео. Довгі тексти будуть розбиті на кілька повідомлень.</p>
      </div>
    </div>

    <p style="margin-top:15px;">
      <label>Текст повідомлення:</label><br>
      <textarea name="text" required>{{ last_text or "" }}</textarea>
    </p>
    <button type="submit" name="action" value="preview" class="btn secondary">Порахувати одержувачів</button>
    <button type="submit" name="action" value="send" class="btn">Надіслати розсилку</button>
  </form>
</div>

<div class="box">
  <h2>Експорт бази</h2>
  <p><a href="/admin/export" class="btn secondary">Експорт CSV</a></p>
</div>

<div class="box">
  <h2>Лід за нікнеймом</h2>
  <form method="get" action="/admin">
    <label>Telegram username (з @ або без)</label>
    <input type="text" name="lead_username" placeholder="@username" value="{{ lead_username or '' }}" required>
    <p style="margin-top:12px;">
      <button type="submit" class="btn secondary">Знайти ліда</button>
    </p>
  </form>
  {% if lead_message %}
    <p class="info">{{ lead_message }}</p>
  {% endif %}
  {% if lead %}
    <div style="margin-top:12px;padding:14px;border:1px solid #e5e7eb;border-radius:12px;background:#fafafa;">
      <p><strong>ID:</strong> {{ lead.id }}</p>
      <p><strong>Telegram ID:</strong> {{ lead.telegram_id }}</p>
      <p><strong>Username:</strong> @{{ lead.username or '—' }}</p>
      <p><strong>Ім'я:</strong> {{ lead.first_name or '—' }} {{ lead.last_name or '' }}</p>
      <p><strong>Телефон:</strong> {{ lead.phone or '—' }}</p>
      <p><strong>Email:</strong> {{ lead.email or '—' }}</p>
      <p><strong>Статус:</strong> {{ lead.status }}</p>
      <p><strong>Створено:</strong> {{ lead.created_at }}</p>
      <form method="post" action="/admin/lead/delete" style="margin-top:8px;">
        <input type="hidden" name="user_id" value="{{ lead.id }}">
        <button type="submit" class="btn secondary" onclick="return confirm('Видалити цього ліда з бази?');">Видалити ліда</button>
      </form>
    </div>
  {% endif %}
</div>
</div>
</body>
</html>
"""


CONTENT_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Курси | Sekret Club</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1040px;margin:0 auto;padding:24px;background:#f6f7fb;}
a{color:#2563eb;text-decoration:none;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
.btn{display:inline-block;padding:10px 16px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;}
.btn.secondary{background:#6c757d;}
table{width:100%;border-collapse:collapse;}
th,td{padding:10px;border-bottom:1px solid #eef0f6;text-align:left;}
</style></head>
<body>
<p><a class="btn secondary" href="/admin">⬅ Назад</a> <a class="btn" href="{{ add_url }}">{{ add_label }}</a></p>
<div class="box">
  <h2>{{ heading }}</h2>
  <table>
    <tr><th>ID</th><th>Назва</th><th>Сортування</th><th>Дії</th></tr>
    {% for c in items %}
    <tr>
      <td>{{ c.id }}</td>
      <td>{{ c.title }}</td>
      <td>{{ c.sort_order }}</td>
      <td>
        <a href="{{ c.edit_url }}">Редагувати</a>
        {% if c.lessons_url %}| <a href="{{ c.lessons_url }}">Уроки</a>{% endif %}
        | <a href="{{ c.delete_url }}" onclick="return confirm('Видалити?');">Видалити</a>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
</body></html>
"""


CONTENT_FORM_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Курс | Sekret Club</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:24px;background:#f6f7fb;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
input,textarea{width:100%;padding:10px;border-radius:10px;border:1px solid #dbe0ef;box-sizing:border-box;}
textarea{height:120px;}
.btn{display:inline-block;padding:10px 16px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;border:none;cursor:pointer;}
.btn.secondary{background:#6c757d;text-decoration:none;}
label{font-weight:600;display:block;margin-top:12px;margin-bottom:6px;}
.hint{color:#6b7280;font-size:12px;margin-top:6px;}
fieldset{border:1px solid #dbe0ef;border-radius:12px;padding:12px;margin-top:12px;}
legend{font-weight:600;padding:0 8px;}
</style></head>
<body>
<p><a class="btn secondary" href="/admin/content">⬅ Назад</a></p>
<div class="box">
  <h2>{{ title }}</h2>
  <form method="post" enctype="multipart/form-data">
    <label>Назва курсу</label>
    <input type="text" name="title" value="{{ item.title if item else '' }}" required>
    <label>Опис</label>
    <textarea name="description" maxlength="4096">{{ item.description if item and item.description else '' }}</textarea>
    <div class="hint">Текст у боті до 4096 символів. «Опис:» у боті лише якщо є текст.</div>
    <label>Посилання (необов’язково)</label>
    <input type="text" name="link" value="{{ item.link if item and item.link else '' }}" placeholder="https://…">
    <div class="hint">У боті — один блок повідомлення з «▶️ Відео:» і прев’ю; не дублюйте URL у описі.</div>
    <label>Сортування (менше = вище)</label>
    <input type="number" name="sort_order" value="{{ item.sort_order if item else 0 }}">
    <fieldset>
      <legend>Медіа (як у розсилці)</legend>
      <div class="hint">{{ media_hint }}</div>
      <label>Режим завантаження</label>
      <select name="media_mode">
        <option value="text" {% if (media_mode or 'text') == 'text' %}selected{% endif %}>Лише текст (без нових файлів)</option>
        <option value="photo" {% if media_mode == 'photo' %}selected{% endif %}>Фото + текст (оберіть фото нижче)</option>
        <option value="video" {% if media_mode == 'video' %}selected{% endif %}>Відео + текст (оберіть відео нижче)</option>
        <option value="mixed" {% if media_mode == 'mixed' %}selected{% endif %}>Кілька файлів (фото / відео / документи)</option>
      </select>
      <label>Файли (можна кілька)</label>
      <input type="file" name="media_files" multiple accept="image/*,video/*,.pdf,.doc,.docx,.zip">
      <label><input type="checkbox" name="clear_media" value="1"> Очистити всі прикріплені файли курсу</label>
    </fieldset>
    <p style="margin-top:14px;">
      <button class="btn" type="submit">Зберегти</button>
    </p>
  </form>
</div>
</body></html>
"""


LESSONS_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Уроки | Sekret Club</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1040px;margin:0 auto;padding:24px;background:#f6f7fb;}
a{color:#2563eb;text-decoration:none;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
.btn{display:inline-block;padding:10px 16px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;}
.btn.secondary{background:#6c757d;}
table{width:100%;border-collapse:collapse;}
th,td{padding:10px;border-bottom:1px solid #eef0f6;text-align:left;}
.muted{color:#6b7280;font-size:12px;}
</style></head>
<body>
<p>
  <a class="btn secondary" href="/admin/content">⬅ Назад</a>
  <a class="btn" href="/admin/content/{{ course.id }}/lessons/new">+ Додати урок</a>
</p>
<div class="box">
  <h2>Уроки: {{ course.title }}</h2>
  <table>
    <tr><th>ID</th><th>Назва</th><th>Сортування</th><th>Медіа</th><th>Дії</th></tr>
    {% for l in lessons %}
    <tr>
      <td>{{ l.id }}</td>
      <td>{{ l.title }}<div class="muted">{{ (l.description or '')[:80] }}</div></td>
      <td>{{ l.sort_order }}</td>
      <td>{% if l.attachments_json %}вкладення{% elif l.file_id or l.photo_file_id %}file_id{% elif l.link or l.video_url %}посилання{% else %}—{% endif %}</td>
      <td>
        <a href="/admin/lesson/{{ l.id }}/edit">Редагувати</a> |
        <a href="/admin/lesson/{{ l.id }}/delete" onclick="return confirm('Видалити урок?');">Видалити</a>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
</body></html>
"""


LESSON_FORM_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Урок | Sekret Club</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:24px;background:#f6f7fb;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
input,textarea{width:100%;padding:10px;border-radius:10px;border:1px solid #dbe0ef;box-sizing:border-box;}
textarea{height:140px;}
.btn{display:inline-block;padding:10px 16px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;border:none;cursor:pointer;}
.btn.secondary{background:#6c757d;text-decoration:none;}
label{font-weight:600;display:block;margin-top:12px;margin-bottom:6px;}
.hint{color:#6b7280;font-size:12px;margin-top:6px;}
fieldset{border:1px solid #dbe0ef;border-radius:12px;padding:12px;margin-top:12px;}
legend{font-weight:600;padding:0 8px;}
</style></head>
<body>
<p><a class="btn secondary" href="/admin/content/{{ course.id }}/lessons">⬅ Назад</a></p>
<div class="box">
  <h2>{{ title }}</h2>
  <form method="post" enctype="multipart/form-data">
    <label>Назва уроку</label>
    <input type="text" name="title" value="{{ item.title if item else '' }}" required>
    <label>Опис</label>
    <textarea name="description" maxlength="4096">{{ item.description if item and item.description else '' }}</textarea>
    <div class="hint">Текст у боті до 4096 символів. «Опис:» у боті лише якщо є текст.</div>
    <label>Посилання (необов’язково)</label>
    <input type="text" name="link" value="{{ item.link if item and item.link else '' }}" placeholder="https://…">
    <div class="hint">У боті з’явиться рядок «▶️ Відео:» + посилання в одному повідомленні з прев’ю. Старі URL у полі «відео» в БД теж підхоплюються; не дублюйте лінк у описі.</div>
    <label>Сортування (менше = вище)</label>
    <input type="number" name="sort_order" value="{{ item.sort_order if item else 0 }}">
    <fieldset>
      <legend>Медіа (як у розсилці)</legend>
      <div class="hint">{{ media_hint }}</div>
      <label>Режим завантаження</label>
      <select name="media_mode">
        <option value="text" {% if (media_mode or 'text') == 'text' %}selected{% endif %}>Лише текст</option>
        <option value="photo" {% if media_mode == 'photo' %}selected{% endif %}>Фото + текст</option>
        <option value="video" {% if media_mode == 'video' %}selected{% endif %}>Відео + текст</option>
        <option value="mixed" {% if media_mode == 'mixed' %}selected{% endif %}>Кілька файлів</option>
      </select>
      <label>Файли (можна кілька)</label>
      <input type="file" name="media_files" multiple accept="image/*,video/*,.pdf,.doc,.docx,.zip">
      <label><input type="checkbox" name="clear_media" value="1"> Очистити всі прикріплені файли уроку</label>
    </fieldset>
    <p style="margin-top:14px;">
      <button class="btn" type="submit">Зберегти</button>
    </p>
  </form>
</div>
</body></html>
"""


SETTINGS_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Налаштування | Sekret Club</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:24px;background:#f6f7fb;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
input{width:100%;padding:10px;border-radius:10px;border:1px solid #dbe0ef;box-sizing:border-box;}
.btn{display:inline-block;padding:10px 16px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;border:none;cursor:pointer;}
.btn.secondary{background:#6c757d;text-decoration:none;}
label{font-weight:600;display:block;margin-top:12px;margin-bottom:6px;}
.hint{color:#6b7280;font-size:12px;margin-top:6px;}
</style></head>
<body>
<p><a class="btn secondary" href="/admin">⬅ Назад</a></p>
<div class="box">
  <h2>Тарифи (назви для кнопок і текстів)</h2>
  <form method="post">
    <label>Назва тарифу Trial</label>
    <input type="text" name="tariff_trial_name" value="{{ tariff_trial_name }}">
    <div class="hint">Приклад: Trial</div>
    <label>Назва тарифу Стандарт</label>
    <input type="text" name="tariff_standard_name" value="{{ tariff_standard_name }}">
    <div class="hint">Приклад: Стандарт</div>
    <p style="margin-top:14px;">
      <button class="btn" type="submit">Зберегти</button>
    </p>
  </form>
</div>
</body></html>
"""


TARIFFS_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Тарифи | Sekret Club</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:860px;margin:0 auto;padding:24px;background:#f6f7fb;}
table{width:100%;border-collapse:collapse;}
th,td{padding:10px;border-bottom:1px solid #eef0f6;text-align:left;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
.btn{display:inline-block;padding:8px 14px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;text-decoration:none;}
.btn.secondary{background:#6c757d;}
input{width:100%;padding:8px;border-radius:8px;border:1px solid #dbe0ef;box-sizing:border-box;}
label{font-weight:600;display:block;margin-top:8px;margin-bottom:4px;}
</style></head>
<body>
<p><a class="btn secondary" href="/admin">⬅ Назад</a></p>
<div class="box">
  <h2>Тарифи</h2>
  <table>
    <tr><th>ID</th><th>Код</th><th>Назва</th><th>Ціна, грн</th><th>Рекурентний</th><th>Дії</th></tr>
    {% for t in tariffs %}
    <tr>
      <td>{{ t.id }}</td>
      <td>{{ t.code }}</td>
      <td>{{ t.name }}</td>
      <td>{{ t.price_grn }}</td>
      <td>{{ 'так' if t.is_recurring else 'ні' }}</td>
      <td>
        <a href="/admin/tariffs?id={{ t.id }}">Редагувати</a> |
        <a href="/admin/tariff/{{ t.id }}/delete" onclick="return confirm('Видалити тариф?');">Видалити</a>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>

<div class="box">
  <h2>{% if edit_id %}Редагувати тариф #{{ edit_id }}{% else %}Новий тариф{% endif %}</h2>
  <form method="post">
    <label>Код (латиницею, унікальний)</label>
    <input type="text" name="code" value="{{ form.code or '' }}" {% if edit_id %}readonly{% endif %}>
    <label>Назва</label>
    <input type="text" name="name" value="{{ form.name or '' }}" required>
    <label>Ціна, грн</label>
    <input type="number" name="price_grn" value="{{ form.price_grn or 0 }}" min="0" required>
    <label>Рекурентний</label>
    <input type="checkbox" name="is_recurring" value="1" {% if form.is_recurring %}checked{% endif %}>
    <p style="margin-top:12px;">
      <button class="btn" type="submit">Зберегти</button>
    </p>
  </form>
</div>
</body></html>
"""


def _admin_upload_to_telegram(media, media_type: str) -> str | None:
    """Завантажити файл у Telegram та отримати file_id (фото / відео / документ)."""
    if not media or not getattr(config, "ADMIN_IDS", None):
        return None
    admin_chat_id = (config.ADMIN_IDS or [None])[0]
    if not admin_chat_id:
        return None
    if media_type == "document":
        method = "sendDocument"
        files_key = "document"
    elif media_type == "video":
        method = "sendVideo"
        files_key = "video"
    else:
        method = "sendPhoto"
        files_key = "photo"
    url = TELEGRAM_API.format(token=config.BOT_TOKEN, method=method)
    files = {files_key: (media.filename, media.stream, media.mimetype)}
    data = {"chat_id": admin_chat_id, "caption": "admin upload"}
    try:
        r = requests.post(url, data=data, files=files, timeout=60)
        j = r.json()
        if not j.get("ok"):
            return None
        if media_type == "video":
            return j["result"]["video"]["file_id"]
        if media_type == "document":
            return j["result"]["document"]["file_id"]
        return j["result"]["photo"][-1]["file_id"]
    except Exception:
        return None


def _admin_guess_media_kind(file_storage) -> str:
    fn = (getattr(file_storage, "filename", None) or "").lower()
    mt = (getattr(file_storage, "mimetype", None) or "").lower()
    if mt.startswith("video/") or fn.endswith((".mp4", ".mov", ".webm", ".mkv")):
        return "video"
    if mt.startswith("image/") or fn.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "photo"
    return "document"


def _admin_collect_uploaded_attachments() -> list[dict]:
    out: list[dict] = []
    for f in request.files.getlist("media_files"):
        if not f or not getattr(f, "filename", None):
            continue
        if len(out) >= MAX_ATTACHMENTS_PER_SAVE:
            break
        kind = _admin_guess_media_kind(f)
        fid = _admin_upload_to_telegram(f, kind)
        if fid:
            out.append({"type": kind, "file_id": fid})
    return out


def _admin_merge_attachments_json(existing_json: str | None, new_items: list[dict], clear: bool) -> str | None:
    if clear:
        merged = list(new_items)
    else:
        merged = list(parse_attachments_json(existing_json)) + list(new_items)
    return attachments_to_json(merged) if merged else None


def _admin_sync_content_legacy_file_id(item: Content | None, merged_list: list[dict]):
    if not item:
        return
    videos = [x for x in merged_list if x.get("type") == "video"]
    if videos:
        item.file_id = videos[0]["file_id"]
    else:
        item.file_id = None


def _admin_sync_lesson_legacy_fields(lesson: Lesson | None, merged_list: list[dict], clear: bool):
    if not lesson:
        return
    if clear and not merged_list:
        lesson.file_id = None
        lesson.photo_file_id = None
        return
    videos = [x for x in merged_list if x.get("type") == "video"]
    photos = [x for x in merged_list if x.get("type") == "photo"]
    if videos:
        lesson.file_id = videos[0]["file_id"]
    elif clear:
        lesson.file_id = None
    if photos:
        lesson.photo_file_id = photos[0]["file_id"]
    elif clear:
        lesson.photo_file_id = None


def send_telegram_message(chat_id: int, text: str, reply_markup=None):
    """Відправити повідомлення через Telegram API (sync для Flask)"""
    url = TELEGRAM_API.format(token=config.BOT_TOKEN, method="sendMessage")
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send error: {e}")


def ban_from_club_group(telegram_id: int) -> None:
    """Видалити з групи клубу (kick через ban+unban), як у scheduler_tasks.remove_expired_from_group."""
    if not getattr(config, "CLUB_GROUP_ID", None) or not getattr(config, "BOT_TOKEN", None):
        return
    if telegram_id in (config.ADMIN_IDS or []):
        return
    chat_id = config.CLUB_GROUP_ID
    base_url = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
    try:
        r = requests.post(
            f"{base_url}/banChatMember",
            json={"chat_id": chat_id, "user_id": telegram_id},
            timeout=8,
        )
        if r.ok:
            requests.post(
                f"{base_url}/unbanChatMember",
                json={"chat_id": chat_id, "user_id": telegram_id},
                timeout=8,
            )
    except Exception as e:
        print(f"ban_from_club_group error: {e}")


def payment_failed_text(next_retry_date) -> str:
    """Текст повідомлення при неуспішній оплаті"""
    return (
        "Платіж не пройшов, спробуйте ще раз 🔄\n"
        "Або напишіть в підтримку @sekret_manager"
    )


def _failed_payment_retry_markup(telegram_id: int, tariff_code: str) -> dict:
    """Кнопка повторної оплати під неуспішним платежем (trial/standard)."""
    pay_url = _pay_url_for(int(telegram_id), "trial" if tariff_code == "trial" else "standard")
    button_text = (
        "Отримати доступ за 1 грн"
        if tariff_code == "trial"
        else f"Тариф «Стандарт» — {config.PRICE_STANDARD_GRN} грн"
    )
    return {"inline_keyboard": [[{"text": button_text, "url": pay_url}]]}


def _return_url():
    # Не редіректимо на групу, щоб не було доступу без оплати.
    if config.BOT_USERNAME:
        return f"https://t.me/{config.BOT_USERNAME}"
    return "https://t.me/sekret_method_club_bot"


def _service_url():
    base = (config.BASE_URL or "").rstrip("/")
    return f"{base}/webhook/wayforpay" if base else ""


def _public_base_url() -> str:
    return (getattr(config, "PUBLIC_BASE_URL", "") or "").rstrip("/") or (config.BASE_URL or "").rstrip("/")


def _pay_url_for(telegram_id: int, tariff: str) -> str:
    """Згенерувати короткий публічний URL без token у рядку."""
    import secrets

    base = _public_base_url()
    code = secrets.token_urlsafe(18).replace("-", "").replace("_", "")

    async def _save():
        async with async_session() as s_db:
            s_db.add(PayLink(code=code, telegram_id=int(telegram_id), tariff=tariff))
            await s_db.commit()

    try:
        asyncio.run(_save())
    except Exception:
        # fallback: якщо БД недоступна, повертаємо старий формат
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
        t = s.dumps({"tid": int(telegram_id), "tariff": tariff})
        return f"{base}/pay?token={t}"

    return f"{base}/p/{code}"


@app.route("/p/<string:code>")
def pay_short(code: str):
    """Коротке посилання на оплату: /p/<code>"""
    code = (code or "").strip()
    if not code:
        return "Not found", 404

    async def _load_and_delete():
        from sqlalchemy import select, delete
        async with async_session() as s_db:
            pl = (await s_db.execute(select(PayLink).where(PayLink.code == code))).scalar_one_or_none()
            if not pl:
                return None
            # одноразове (щоб не можна було шарити)
            await s_db.execute(delete(PayLink).where(PayLink.code == code))
            await s_db.commit()
            return pl

    pl = asyncio.run(_load_and_delete())
    if not pl:
        return "Link expired", 410

    # Прокидуємо в /pay через POST (token не світиться в URL)
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
    token = s.dumps({"tid": int(pl.telegram_id), "tariff": (pl.tariff or "standard")})
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Оплата</title></head>
<body>
  <form id="f" method="POST" action="/pay">
    <input type="hidden" name="token" value="{token}">
  </form>
  <script>document.getElementById('f').submit();</script>
</body></html>"""


def _render_autosubmit_form(d: dict, amount: int, product_name: str, title: str, is_trial: bool) -> str:
    """Мінімальна сторінка-автосабміт у WayForPay (без кастомного UI)."""
    su = f'<input type="hidden" name="serviceUrl" value="{_service_url()}">' if _service_url() else ""
    recurring = ""
    if str(d.get("regularOn", "")).strip() == "1":
        regular_behavior = str(d.get("regularBehavior", "preset")).strip() or "preset"
        regular_mode = str(d.get("regularMode", "monthly")).strip() or "monthly"
        regular_amount = d.get("regularAmount", amount)
        date_next = str(d.get("dateNext", "")).strip()
        date_end = str(d.get("dateEnd", "")).strip()
        recurring = (
            f'<input type="hidden" name="regularBehavior" value="{regular_behavior}">'
            f'<input type="hidden" name="regularMode" value="{regular_mode}">'
            f'<input type="hidden" name="regularOn" value="1">'
            f'<input type="hidden" name="regularAmount" value="{regular_amount}">'
            + (f'<input type="hidden" name="dateNext" value="{date_next}">' if date_next else "")
            + (f'<input type="hidden" name="dateEnd" value="{date_end}">' if date_end else "")
        )
        rc = d.get("regularCount", None)
        if rc is not None:
            recurring += f'<input type="hidden" name="regularCount" value="{int(rc)}">'
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Redirecting…</title>
  </head>
  <body>
    <form id="f" method="POST" action="https://secure.wayforpay.com/pay">
      <input type="hidden" name="merchantAccount" value="{d['merchantAccount']}">
      <input type="hidden" name="merchantDomainName" value="{d['merchantDomainName']}">
      <input type="hidden" name="merchantSignature" value="{d['merchantSignature']}">
      <input type="hidden" name="merchantAuthType" value="SimpleSignature">
      <input type="hidden" name="orderReference" value="{d['orderReference']}">
      <input type="hidden" name="orderDate" value="{d['orderDate']}">
      <input type="hidden" name="amount" value="{d['amount']}">
      <input type="hidden" name="currency" value="{d['currency']}">
      <input type="hidden" name="productName[]" value="{product_name}">
      <input type="hidden" name="productPrice[]" value="{amount}">
      <input type="hidden" name="productCount[]" value="1">
      <input type="hidden" name="language" value="UA">
      <input type="hidden" name="returnUrl" value="{_return_url()}">
      {su}
      {recurring}
    </form>
    <script>document.getElementById('f').submit();</script>
  </body>
</html>"""

@app.route("/pay", methods=["GET", "POST"])
def pay():
    """Оплата по підписаному token (GET або POST)."""
    token = (request.form.get("token") or request.args.get("token") or "").strip()
    if not token:
        return "Missing token", 400

    try:
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
        payload = s.loads(token, max_age=60 * 60 * 24 * 7)  # 7 днів
    except Exception:
        return "Invalid token", 400

    try:
        telegram_id = int(payload.get("tid"))
    except Exception:
        return "Invalid token payload", 400
    tariff = (payload.get("tariff") or "standard").strip().lower()
    if tariff not in ("trial", "standard"):
        tariff = "standard"

    # Серверна заборона повторного trial: навіть якщо хтось відкриє старе/ручне trial-посилання,
    # після використаного trial (або для колишнього підписника) примусово вмикаємо стандартний тариф.
    async def _resolve_tariff_for_user(tid: int, requested_tariff: str) -> str:
        if requested_tariff != "trial":
            return requested_tariff
        async with async_session() as s_db:
            u = await get_user(s_db, tid)
            if not u:
                return requested_tariff
            if getattr(u, "has_used_trial", False) or getattr(u, "status", "") == "former_subscriber":
                return "standard"
        return requested_tariff

    tariff = asyncio.run(_resolve_tariff_for_user(telegram_id, tariff))

    # Телефон користувач вводить безпосередньо на стороні WayForPay.
    # Ми не підставляємо phone/email у форму, щоб не з'являлись зайві поля на нашому боці.
    phone = ""

    is_trial = tariff == "trial"
    amount = int(config.PRICE_TRIAL_GRN if is_trial else config.PRICE_STANDARD_GRN)
    standard_amount = int(config.PRICE_STANDARD_GRN)
    product_name = "Підписка на Sekret Club Пробний період" if is_trial else "Підписка на Sekret Club Стандарт"
    # Розділяємо ручну стандартну оплату і автосписання в логах:
    # - ручна оплата з кнопки: manual_sub_...
    # - автосписання/внутрішні recurring-потоки: sub_...
    order_prefix = "trial" if is_trial else "manual_sub"
    order_reference = f"{order_prefix}_{telegram_id}_{int(datetime.utcnow().timestamp())}"

    # Фіксуємо факт відкриття сторінки оплати. Використовується для одного нагадування через 5 хв,
    # якщо оплата не перейшла в Approved.
    async def _register_payment_open():
        from sqlalchemy import select
        async with async_session() as s_db:
            u = await get_user(s_db, telegram_id)
            if not u:
                return
            existing = (await s_db.execute(select(Payment).where(Payment.order_reference == order_reference))).scalar_one_or_none()
            if existing:
                return
            s_db.add(
                Payment(
                    user_id=u.id,
                    order_reference=order_reference,
                    amount=float(amount),
                    currency="UAH",
                    status="Initiated",
                    transaction_status="Initiated",
                )
            )
            await s_db.commit()

    try:
        asyncio.run(_register_payment_open())
    except Exception:
        pass

    date_next = ""
    date_end = ""
    regular_count = None
    regular_mode = "monthly"
    # Для стандартного recurring задаємо кінцеву дату, інакше правило може не створитися.
    date_end = (datetime.utcnow() + timedelta(days=3650)).strftime("%d.%m.%Y")
    if is_trial:
        # Після trial перше списання стандарту — через TRIAL_DAYS (14 днів), далі — monthly.
        dt = datetime.utcnow() + timedelta(days=int(config.TRIAL_DAYS))
        date_next = dt.strftime("%d.%m.%Y")
        regular_mode = "monthly"
        # На платіжній сторінці WayForPay: строк регулярки 30 днів після першого автосписання.
        date_end = (dt + timedelta(days=int(config.SUBSCRIPTION_DAYS))).strftime("%d.%m.%Y")

    result = create_payment_link(
        amount=amount,
        product_name=product_name,
        order_reference=order_reference,
        client_email="",
        client_phone=phone,
        is_trial=is_trial,
        # Для trial передаємо recurring (перше списання з dateNext, далі — monthly).
        regular_mode=regular_mode,
        regular_amount=standard_amount if is_trial else amount,
        date_next=date_next,
        date_end=date_end,
        regular_count=regular_count,
        return_url=_return_url(),
        service_url=_service_url(),
    )
    try:
        print(
            "WFP pay payload "
            f"orderReference={order_reference} "
            f"is_trial={is_trial} "
            f"amount={amount} "
            f"regularMode={result['data'].get('regularMode', '')} "
            f"regularAmount={result['data'].get('regularAmount', '')} "
            f"dateNext={result['data'].get('dateNext', '')} "
            f"dateEnd={result['data'].get('dateEnd', '')} "
            f"regularCount={result['data'].get('regularCount', '')}"
        )
    except Exception:
        pass
    d = result["data"]
    title = "Підписка на Sekret Club Пробний період" if is_trial else "Підписка на Sekret Club"
    return _render_autosubmit_form(d, amount=amount, product_name=product_name, title=title, is_trial=is_trial)


# Backward compatibility (старі URL з telegram_id) — редіректимо на /pay?token=...
@app.route("/pay/trial/<int:telegram_id>")
def pay_trial(telegram_id):
    from itsdangerous import URLSafeTimedSerializer
    base = (getattr(config, "PUBLIC_BASE_URL", "") or config.BASE_URL or "").rstrip("/")
    s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
    t = s.dumps({"tid": int(telegram_id), "tariff": "trial"})
    return redirect(f"{base}/pay?token={t}")


@app.route("/pay/standard/<int:telegram_id>")
def pay_standard(telegram_id):
    from itsdangerous import URLSafeTimedSerializer
    base = (getattr(config, "PUBLIC_BASE_URL", "") or config.BASE_URL or "").rstrip("/")
    s = URLSafeTimedSerializer(getattr(config, "PAYLINK_SECRET", "") or config.ADMIN_PANEL_SECRET, salt="paylink")
    t = s.dumps({"tid": int(telegram_id), "tariff": "standard"})
    return redirect(f"{base}/pay?token={t}")


@app.route("/admin")
@admin_required
def admin_index():
    from database.models import User
    from sqlalchemy import select, func
    async def _stats():
        async with async_session() as s:
            total = (await s.execute(select(func.count(User.id)))).scalar() or 0
            result = await s.execute(select(User.status, func.count(User.id)).group_by(User.status))
            by_status = dict(result.all())
        return {"total": total, "subscribers": by_status.get("subscriber", 0),
                "former": by_status.get("former_subscriber", 0), "not_sub": by_status.get("not_subscriber", 0)}

    lead_username = (request.args.get("lead_username") or "").strip()
    lead_message = (request.args.get("lead_message") or "").strip()
    lead = None

    async def _find_lead(username_q: str):
        if not username_q:
            return None
        uname = username_q.lstrip("@").strip()
        if not uname:
            return None
        async with async_session() as s:
            return (await s.execute(select(User).where(User.username == uname))).scalar_one_or_none()

    if lead_username:
        lead = asyncio.run(_find_lead(lead_username))
        if not lead and not lead_message:
            lead_message = "Ліда з таким username не знайдено."

    stats = asyncio.run(_stats())
    # значення за замовчуванням для форми
    return render_template_string(
        ADMIN_HTML,
        stats=stats,
        preview_count=None,
        last_text="",
        selected_segments=["subscribers"],
        msg_type="text",
        lead=lead,
        lead_username=lead_username,
        lead_message=lead_message,
    )


@app.route("/admin/broadcast", methods=["POST"])
@admin_required
def admin_broadcast():
    from database.models import User, UserStatus
    from sqlalchemy import select

    text = (request.form.get("text") or "").strip()
    msg_type = request.form.get("msg_type", "text")
    segments = request.form.getlist("segments") or ["subscribers"]
    action = request.form.get("action", "preview")
    media = request.files.get("media")

    async def _recipients():
        async with async_session() as s:
            q = select(User)
            statuses = []
            if "subscribers" in segments:
                statuses.append(UserStatus.SUBSCRIBER.value)
            if "former" in segments:
                statuses.append(UserStatus.FORMER_SUBSCRIBER.value)
            if "not_sub" in segments:
                statuses.append(UserStatus.NOT_SUBSCRIBER.value)
            if statuses:
                q = q.where(User.status.in_(statuses))
            r = await s.execute(q)
            return r.scalars().all()

    users = asyncio.run(_recipients())
    preview_count = len(users)

    # Якщо тільки попередній перегляд — показати кількість та зберегти вибір
    if action == "preview" or not users:
        from database.models import User as U
        from sqlalchemy import func, select as s_select

        async def _stats():
            async with async_session() as s:
                total = (await s.execute(s_select(func.count(U.id)))).scalar() or 0
                result = await s.execute(s_select(U.status, func.count(U.id)).group_by(U.status))
                by_status = dict(result.all())
            return {
                "total": total,
                "subscribers": by_status.get("subscriber", 0),
                "former": by_status.get("former_subscriber", 0),
                "not_sub": by_status.get("not_subscriber", 0),
            }

        stats = asyncio.run(_stats())
        return render_template_string(
            ADMIN_HTML,
            stats=stats,
            preview_count=preview_count,
            last_text=text,
            selected_segments=segments,
            msg_type=msg_type,
            lead=None,
            lead_username="",
            lead_message="",
        )

    # Надсилання розсилки
    file_id = None
    if msg_type in ("photo", "video") and media:
        method = "sendPhoto" if msg_type == "photo" else "sendVideo"
        url = TELEGRAM_API.format(token=config.BOT_TOKEN, method=method)
        files = {"photo" if msg_type == "photo" else "video": (media.filename, media.stream, media.mimetype)}
        data = {"chat_id": users[0].telegram_id, "caption": text[:1000]}
        try:
            resp = requests.post(url, data=data, files=files, timeout=20)
            j = resp.json()
            if j.get("ok"):
                if msg_type == "photo":
                    file_id = j["result"]["photo"][-1]["file_id"]
                else:
                    file_id = j["result"]["video"]["file_id"]
        except Exception as e:
            print(f"Broadcast media upload error: {e}")

    def _send_text(uid: int, body: str):
        send_telegram_message(uid, body)

    def _chunk_text(full: str, limit: int):
        if not full:
            return []
        res = []
        while full:
            res.append(full[:limit])
            full = full[limit:]
        return res

    for user in users:
        try:
            if msg_type == "text" or not file_id:
                parts = _chunk_text(text, 4096)
                if not parts:
                    continue
                for part in parts:
                    _send_text(user.telegram_id, part)
            else:
                method = "sendPhoto" if msg_type == "photo" else "sendVideo"
                url = TELEGRAM_API.format(token=config.BOT_TOKEN, method=method)
                for part in _chunk_text(text, 1000) or [""]:
                    payload = {
                        "chat_id": user.telegram_id,
                        "caption": part,
                        "photo" if msg_type == "photo" else "video": file_id,
                    }
                    requests.post(url, json=payload, timeout=15)
        except Exception as e:
            print(f"Broadcast send error to {user.telegram_id}: {e}")

    return redirect("/admin")


@app.route("/admin/export")
@admin_required
def admin_export():
    from io import StringIO
    from flask import Response
    from database.models import User
    from sqlalchemy import select
    async def _users():
        async with async_session() as s:
            r = await s.execute(select(User))
            return r.scalars().all()
    users = asyncio.run(_users())
    output = StringIO()
    output.write("telegram_id;username;first_name;status;created_at\n")
    for u in users:
        output.write(f"{u.telegram_id};{u.username or ''};{u.first_name or ''};{u.status};{u.created_at}\n")
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=users.csv"})


@app.route("/admin/lead/delete", methods=["POST"])
@admin_required
def admin_lead_delete():
    from sqlalchemy import select, delete
    user_id_raw = (request.form.get("user_id") or "").strip()
    username_raw = (request.form.get("username") or "").strip()
    username = username_raw.lstrip("@").strip()
    if not user_id_raw and not username:
        return redirect("/admin?lead_message=Вкажіть%20username%20або%20user_id")

    async def _delete_lead():
        async with async_session() as s:
            u = None
            if user_id_raw.isdigit():
                u = (await s.execute(select(User).where(User.id == int(user_id_raw)))).scalar_one_or_none()
            if not u and username:
                u = (await s.execute(select(User).where(User.username == username))).scalar_one_or_none()
            if not u:
                return False
            await s.execute(delete(PaymentFailure).where(PaymentFailure.user_id == u.id))
            await s.execute(delete(Payment).where(Payment.user_id == u.id))
            await s.execute(delete(Subscription).where(Subscription.user_id == u.id))
            await s.execute(delete(User).where(User.id == u.id))
            await s.commit()
            return True

    try:
        ok = bool(asyncio.run(_delete_lead()))
    except Exception:
        ok = False
    if ok:
        return redirect("/admin?lead_message=Ліда%20успішно%20видалено")
    return redirect("/admin?lead_message=Ліда%20не%20знайдено")


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    async def _load():
        async with async_session() as s:
            trial = await get_setting(s, "tariff_trial_name", "Trial")
            standard = await get_setting(s, "tariff_standard_name", "Стандарт")
            return trial, standard

    async def _save(trial: str, standard: str):
        async with async_session() as s:
            await set_setting(s, "tariff_trial_name", trial.strip() or "Trial")
            await set_setting(s, "tariff_standard_name", standard.strip() or "Стандарт")

    if request.method == "POST":
        asyncio.run(_save(
            request.form.get("tariff_trial_name", ""),
            request.form.get("tariff_standard_name", ""),
        ))
        return redirect("/admin/settings")

    tariff_trial_name, tariff_standard_name = asyncio.run(_load())
    return render_template_string(
        SETTINGS_HTML,
        tariff_trial_name=tariff_trial_name,
        tariff_standard_name=tariff_standard_name,
    )


@app.route("/admin/tariffs", methods=["GET", "POST"])
@admin_required
def admin_tariffs():
    from sqlalchemy import select, delete

    async def _load_all():
        async with async_session() as s:
            # гарантуємо наявність базових тарифів
            await get_or_create_tariff(s, "trial", "Trial", config.PRICE_TRIAL_GRN, is_recurring=True)
            await get_or_create_tariff(s, "standard", "Стандарт", config.PRICE_STANDARD_GRN, is_recurring=True)
            r = await s.execute(select(Tariff).order_by(Tariff.id.asc()))
            return r.scalars().all()

    if request.method == "POST":
        edit_id = request.args.get("id")
        code = (request.form.get("code") or "").strip()
        name = (request.form.get("name") or "").strip()
        price_grn = int(request.form.get("price_grn") or 0)
        is_recurring = bool(request.form.get("is_recurring"))

        async def _save():
            async with async_session() as s:
                if edit_id:
                    r = await s.execute(select(Tariff).where(Tariff.id == int(edit_id)))
                    t = r.scalar_one_or_none()
                    if not t:
                        return
                    t.name = name
                    t.price_grn = price_grn
                    t.is_recurring = is_recurring
                else:
                    if not code:
                        return
                    existing = await s.execute(select(Tariff).where(Tariff.code == code))
                    if existing.scalar_one_or_none():
                        return
                    t = Tariff(code=code, name=name, price_grn=price_grn, is_recurring=is_recurring)
                    s.add(t)
                await s.commit()

        asyncio.run(_save())
        return redirect("/admin/tariffs")

    # GET
    edit_id = request.args.get("id")
    tariffs = asyncio.run(_load_all())
    form = {"code": "", "name": "", "price_grn": 0, "is_recurring": True}
    if edit_id:
        try:
            eid = int(edit_id)
        except ValueError:
            eid = None
        if eid:
            for t in tariffs:
                if t.id == eid:
                    form = {
                        "code": t.code,
                        "name": t.name,
                        "price_grn": t.price_grn,
                        "is_recurring": t.is_recurring,
                    }
                    break
    return render_template_string(
        TARIFFS_HTML,
        tariffs=tariffs,
        edit_id=int(edit_id) if edit_id else None,
        form=form,
    )


@app.route("/admin/tariff/<int:tariff_id>/delete")
@admin_required
def admin_tariff_delete(tariff_id: int):
    from sqlalchemy import delete

    async def _delete():
        async with async_session() as s:
            # не даємо видалити базові trial/standard
            await s.execute(
                delete(Tariff).where(Tariff.id == tariff_id).where(Tariff.code.not_in(["trial", "standard"]))
            )
            await s.commit()

    asyncio.run(_delete())
    return redirect("/admin/tariffs")


@app.route("/admin/content")
@admin_required
def admin_content_list():
    from sqlalchemy import select

    async def _load():
        async with async_session() as s:
            # Якщо в БД ще немає курсів — ініціалізувати їх з KNOWLEDGE_BASE
            r = await s.execute(
                select(Content).where(Content.content_type == ContentType.COURSE.value)
            )
            existing = r.scalars().all()
            if not existing:
                for idx, c in enumerate(KNOWLEDGE_BASE.get("courses", [])):
                    content = Content(
                        content_type=ContentType.COURSE.value,
                        title=c["title"],
                        description=None,
                        sort_order=idx,
                    )
                    s.add(content)
                    await s.flush()
                    for les in c.get("lessons", []):
                        lesson = Lesson(
                            content_id=content.id,
                            title=les.get("title", ""),
                            description=les.get("description"),
                            video_url=les.get("video_url"),
                            sort_order=les.get("num", 0),
                        )
                        s.add(lesson)
                await s.commit()
            else:
                # Backfill: якщо курс є в KNOWLEDGE_BASE і має уроки, але в БД їх немає — додати
                for kb_course in KNOWLEDGE_BASE.get("courses", []):
                    if not kb_course.get("lessons"):
                        continue
                    r_match = await s.execute(
                        select(Content)
                        .where(Content.content_type == ContentType.COURSE.value)
                        .where(Content.title == kb_course["title"])
                    )
                    content = r_match.scalar_one_or_none()
                    if not content:
                        continue
                    existing_lessons = (await s.execute(
                        select(Lesson).where(Lesson.content_id == content.id).order_by(Lesson.sort_order.asc())
                    )).scalars().all()
                    for les in kb_course["lessons"]:
                        sort_order = les.get("num", 0)
                        matched = next((l for l in existing_lessons if l.sort_order == sort_order), None)
                        if matched:
                            # Не перезаписуємо існуючі уроки: інакше кожен візит /admin/content
                            # відкочує зміни з форми редагування (опис, посилання тощо).
                            continue
                        lesson = Lesson(
                            content_id=content.id,
                            title=les.get("title", ""),
                            description=les.get("description"),
                            video_url=les.get("video_url"),
                            sort_order=sort_order,
                        )
                        s.add(lesson)
                await s.commit()
            r2 = await s.execute(
                select(Content)
                .where(Content.content_type == ContentType.COURSE.value)
                .order_by(Content.sort_order.asc(), Content.id.desc())
            )
            items = []
            for c in r2.scalars().all():
                items.append(
                    type("Row", (), {
                        "id": c.id,
                        "title": c.title,
                        "sort_order": c.sort_order,
                        "edit_url": f"/admin/content/{c.id}/edit",
                        "lessons_url": f"/admin/content/{c.id}/lessons",
                        "delete_url": f"/admin/content/{c.id}/delete",
                    })
                )
            return items

    items = asyncio.run(_load())
    return render_template_string(
        CONTENT_LIST_HTML,
        items=items,
        heading="Курси",
        add_url="/admin/content/new",
        add_label="+ Додати курс",
    )


@app.route("/admin/content/new", methods=["GET", "POST"])
@admin_required
def admin_content_new():
    if request.method == "POST":
        form, aj, _clear = _admin_bundle_attachments_from_request(None)
        asyncio.run(_admin_save_course(None, form, aj))
        return redirect("/admin/content")

    return render_template_string(
        CONTENT_FORM_HTML,
        title="Новий курс",
        item=None,
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/content/<int:content_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_content_edit(content_id: int):
    from sqlalchemy import select

    async def _get():
        async with async_session() as s:
            r = await s.execute(select(Content).where(Content.id == content_id))
            return r.scalar_one_or_none()

    if request.method == "POST":
        item_prev = asyncio.run(_get())
        if not item_prev:
            return "Not found", 404
        form, aj, _clear = _admin_bundle_attachments_from_request(item_prev.attachments_json)
        asyncio.run(_admin_save_course(content_id, form, aj))
        return redirect("/admin/content")

    item = asyncio.run(_get())
    if not item:
        return "Not found", 404
    return render_template_string(
        CONTENT_FORM_HTML,
        title=f"Редагувати курс #{item.id}",
        item=item,
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/content/<int:content_id>/delete")
@admin_required
def admin_content_delete(content_id: int):
    from sqlalchemy import select, delete

    async def _delete():
        async with async_session() as s:
            # видалити уроки, потім курс
            await s.execute(delete(Lesson).where(Lesson.content_id == content_id))
            await s.execute(delete(Content).where(Content.id == content_id))
            await s.commit()

    asyncio.run(_delete())
    return redirect("/admin/content")


@app.route("/admin/content/<int:content_id>/lessons")
@admin_required
def admin_lessons_list(content_id: int):
    from sqlalchemy import select

    async def _load():
        async with async_session() as s:
            c = (await s.execute(select(Content).where(Content.id == content_id))).scalar_one_or_none()
            lessons = (await s.execute(
                select(Lesson).where(Lesson.content_id == content_id).order_by(Lesson.sort_order.asc(), Lesson.id.desc())
            )).scalars().all()
            return c, lessons

    course, lessons = asyncio.run(_load())
    if not course:
        return "Not found", 404
    return render_template_string(LESSONS_LIST_HTML, course=course, lessons=lessons)


@app.route("/admin/content/<int:content_id>/lessons/new", methods=["GET", "POST"])
@admin_required
def admin_lesson_new(content_id: int):
    from sqlalchemy import select

    async def _course():
        async with async_session() as s:
            return (await s.execute(select(Content).where(Content.id == content_id))).scalar_one_or_none()

    course = asyncio.run(_course())
    if not course:
        return "Not found", 404

    if request.method == "POST":
        form, aj, clear = _admin_bundle_attachments_from_request(None)
        asyncio.run(_admin_save_lesson(content_id, None, form, aj, clear))
        return redirect(f"/admin/content/{content_id}/lessons")

    return render_template_string(
        LESSON_FORM_HTML,
        title="Новий урок",
        item=None,
        course=course,
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/lesson/<int:lesson_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_lesson_edit(lesson_id: int):
    from sqlalchemy import select

    async def _load():
        async with async_session() as s:
            l = (await s.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
            c = (await s.execute(select(Content).where(Content.id == l.content_id))).scalar_one_or_none() if l else None
            return l, c

    item, course = asyncio.run(_load())
    if not item or not course:
        return "Not found", 404

    if request.method == "POST":
        form, aj, clear = _admin_bundle_attachments_from_request(item.attachments_json)
        asyncio.run(_admin_save_lesson(course.id, lesson_id, form, aj, clear))
        return redirect(f"/admin/content/{course.id}/lessons")

    return render_template_string(
        LESSON_FORM_HTML,
        title=f"Редагувати урок #{item.id}",
        item=item,
        course=course,
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/lesson/<int:lesson_id>/delete")
@admin_required
def admin_lesson_delete(lesson_id: int):
    from sqlalchemy import select, delete

    async def _delete():
        async with async_session() as s:
            l = (await s.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
            if not l:
                return None
            cid = l.content_id
            await s.execute(delete(Lesson).where(Lesson.id == lesson_id))
            await s.commit()
            return cid

    cid = asyncio.run(_delete())
    if not cid:
        return "Not found", 404
    return redirect(f"/admin/content/{cid}/lessons")


@app.route("/admin/streams_admin")
@admin_required
def admin_streams_admin():
    from sqlalchemy import select

    async def _load():
        async with async_session() as s:
            await ensure_streams_seeded(s)
            r = await s.execute(
                select(Content)
                .where(Content.content_type == ContentType.STREAM.value)
                .order_by(Content.sort_order.asc(), Content.id.desc())
            )
            items = []
            for c in r.scalars().all():
                items.append(
                    type("Row", (), {
                        "id": c.id,
                        "title": c.title,
                        "sort_order": c.sort_order,
                        "edit_url": f"/admin/stream/{c.id}/edit",
                        "lessons_url": None,
                        "delete_url": f"/admin/stream/{c.id}/delete",
                    })
                )
            return items

    items = asyncio.run(_load())
    return render_template_string(
        CONTENT_LIST_HTML,
        items=items,
        heading="Ефіри",
        add_url="/admin/stream/new",
        add_label="+ Додати ефір",
    )


@app.route("/admin/materials_admin")
@admin_required
def admin_materials_admin():
    from sqlalchemy import select

    async def _load():
        async with async_session() as s:
            await ensure_materials_seeded(s)
            r = await s.execute(
                select(Content)
                .where(Content.content_type == ContentType.MATERIAL.value)
                .order_by(Content.sort_order.asc(), Content.id.desc())
            )
            items = []
            for c in r.scalars().all():
                items.append(
                    type("Row", (), {
                        "id": c.id,
                        "title": c.title,
                        "sort_order": c.sort_order,
                        "edit_url": f"/admin/material/{c.id}/edit",
                        "lessons_url": None,
                        "delete_url": f"/admin/material/{c.id}/delete",
                    })
                )
            return items

    items = asyncio.run(_load())
    return render_template_string(
        CONTENT_LIST_HTML,
        items=items,
        heading="Корисні матеріали",
        add_url="/admin/material/new",
        add_label="+ Додати матеріал",
    )


@app.route("/admin/books_admin")
@admin_required
def admin_books_admin():
    from sqlalchemy import select

    async def _load():
        async with async_session() as s:
            await ensure_books_seeded(s)
            r = await s.execute(
                select(Content)
                .where(Content.content_type == ContentType.BOOK.value)
                .order_by(Content.sort_order.asc(), Content.id.desc())
            )
            items = []
            for c in r.scalars().all():
                items.append(
                    type("Row", (), {
                        "id": c.id,
                        "title": c.title,
                        "sort_order": c.sort_order,
                        "edit_url": f"/admin/book/{c.id}/edit",
                        "lessons_url": None,
                        "delete_url": f"/admin/book/{c.id}/delete",
                    })
                )
            return items

    items = asyncio.run(_load())
    return render_template_string(
        CONTENT_LIST_HTML,
        items=items,
        heading="Книги",
        add_url="/admin/book/new",
        add_label="+ Додати книгу",
    )


CONTENT_GENERIC_FORM_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{{ title }}</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:24px;background:#f6f7fb;}
.box{background:#fff;padding:18px;border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,0.06);margin:16px 0;}
input,textarea{width:100%;padding:10px;border-radius:10px;border:1px solid #dbe0ef;box-sizing:border-box;}
textarea{height:140px;}
.btn{display:inline-block;padding:10px 16px;border-radius:999px;background:#4CAF50;color:#fff;margin-right:8px;border:none;cursor:pointer;}
.btn.secondary{background:#6c757d;text-decoration:none;}
label{font-weight:600;display:block;margin-top:12px;margin-bottom:6px;}
.hint{color:#6b7280;font-size:12px;margin-top:6px;}
fieldset{border:1px solid #dbe0ef;border-radius:12px;padding:12px;margin-top:12px;}
legend{font-weight:600;padding:0 8px;}
</style></head>
<body>
<p><a class="btn secondary" href="{{ back_url }}">⬅ Назад</a></p>
<div class="box">
  <h2>{{ title }}</h2>
  <form method="post" enctype="multipart/form-data">
    <label>Назва</label>
    <input type="text" name="title" value="{{ item.title if item else '' }}" required>
    <label>Опис</label>
    <textarea name="description" maxlength="4096">{{ item.description if item and item.description else '' }}</textarea>
    <div class="hint">Текст у боті до 4096 символів. «Опис:» у боті лише якщо є текст.</div>
    <label>Посилання (необов’язково)</label>
    <input type="text" name="link" value="{{ item.link if item and item.link else '' }}" placeholder="https://…">
    <div class="hint">YouTube тощо — у боті в тому ж повідомленні з рядком «▶️ Відео:» і прев’ю; не дублюйте URL у описі.</div>
    <label>Сортування (менше = вище)</label>
    <input type="number" name="sort_order" value="{{ item.sort_order if item else 0 }}">
    <fieldset>
      <legend>Медіа (як у розсилці)</legend>
      <div class="hint">{{ media_hint }}</div>
      <label>Режим завантаження</label>
      <select name="media_mode">
        <option value="text" {% if (media_mode or 'text') == 'text' %}selected{% endif %}>Лише текст</option>
        <option value="photo" {% if media_mode == 'photo' %}selected{% endif %}>Фото + текст</option>
        <option value="video" {% if media_mode == 'video' %}selected{% endif %}>Відео + текст</option>
        <option value="mixed" {% if media_mode == 'mixed' %}selected{% endif %}>Кілька файлів</option>
      </select>
      <label>Файли (можна кілька)</label>
      <input type="file" name="media_files" multiple accept="image/*,video/*,.pdf,.doc,.docx,.zip">
      <label><input type="checkbox" name="clear_media" value="1"> Очистити всі прикріплені файли</label>
    </fieldset>
    <p style="margin-top:14px;">
      <button class="btn" type="submit">Зберегти</button>
    </p>
  </form>
</div>
</body></html>
"""


def _admin_back_url_for_type(content_type: str) -> str:
    if content_type == ContentType.STREAM.value:
        return "/admin/streams_admin"
    if content_type == ContentType.MATERIAL.value:
        return "/admin/materials_admin"
    if content_type == ContentType.BOOK.value:
        return "/admin/books_admin"
    return "/admin/content"


async def _admin_load_content_item(content_id: int) -> Content | None:
    from sqlalchemy import select
    async with async_session() as s:
        return (await s.execute(select(Content).where(Content.id == content_id))).scalar_one_or_none()


def _admin_content_form_from_request() -> dict:
    return {
        "title": (request.form.get("title") or "").strip(),
        "description": (request.form.get("description") or "").strip() or None,
        "link": (request.form.get("link") or "").strip() or None,
        "sort_order": int(request.form.get("sort_order") or 0),
    }


def _admin_bundle_attachments_from_request(existing_json: str | None) -> tuple[dict, str | None, bool]:
    clear = bool(request.form.get("clear_media"))
    new_items = _admin_collect_uploaded_attachments()
    aj = _admin_merge_attachments_json(existing_json, new_items, clear)
    return _admin_content_form_from_request(), aj, clear


async def _admin_save_content_item(
    content_type: str,
    content_id: int | None,
    form: dict,
    attachments_json: str | None,
):
    from sqlalchemy import select

    merged_list = parse_attachments_json(attachments_json)
    async with async_session() as s:
        if content_id:
            item = (await s.execute(select(Content).where(Content.id == content_id))).scalar_one_or_none()
            if not item:
                return None
            item.title = form["title"]
            item.description = form["description"]
            item.sort_order = form["sort_order"]
            item.attachments_json = attachments_json
            item.link = form["link"]
            _admin_sync_content_legacy_file_id(item, merged_list)
        else:
            item = Content(
                content_type=content_type,
                title=form["title"],
                description=form["description"],
                sort_order=form["sort_order"],
                attachments_json=attachments_json,
                link=form["link"],
                video_url=None,
            )
            s.add(item)
            await s.flush()
            _admin_sync_content_legacy_file_id(item, merged_list)
        await s.commit()
        return item


async def _admin_save_course(content_id: int | None, form: dict, attachments_json: str | None):
    from sqlalchemy import select

    merged_list = parse_attachments_json(attachments_json)
    async with async_session() as s:
        if content_id:
            c = (await s.execute(select(Content).where(Content.id == content_id))).scalar_one_or_none()
            if not c:
                return
            c.title = form["title"]
            c.description = form["description"]
            c.sort_order = form["sort_order"]
            c.attachments_json = attachments_json
            c.link = form["link"]
            _admin_sync_content_legacy_file_id(c, merged_list)
        else:
            c = Content(
                content_type=ContentType.COURSE.value,
                title=form["title"],
                description=form["description"],
                sort_order=form["sort_order"],
                attachments_json=attachments_json,
                link=form["link"],
                video_url=None,
            )
            s.add(c)
            await s.flush()
            _admin_sync_content_legacy_file_id(c, merged_list)
        await s.commit()


async def _admin_save_lesson(
    content_id: int,
    lesson_id: int | None,
    form: dict,
    attachments_json: str | None,
    clear_attachments: bool,
):
    from sqlalchemy import select

    merged_list = parse_attachments_json(attachments_json)
    async with async_session() as s:
        if lesson_id:
            l = (await s.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
            if not l:
                return
            l.title = form["title"]
            l.description = form["description"]
            l.sort_order = form["sort_order"]
            l.attachments_json = attachments_json
            l.link = form["link"]
            # Одне джерело URL для бота: поле «Посилання» в адмінці = і link, і video_url
            l.video_url = form["link"]
            _admin_sync_lesson_legacy_fields(l, merged_list, clear_attachments)
        else:
            l = Lesson(
                content_id=content_id,
                title=form["title"],
                description=form["description"],
                sort_order=form["sort_order"],
                attachments_json=attachments_json,
                link=form["link"],
                video_url=form["link"],
            )
            s.add(l)
            await s.flush()
            _admin_sync_lesson_legacy_fields(l, merged_list, clear_attachments)
        await s.commit()


async def _admin_delete_content_item(content_id: int, expected_type: str):
    from sqlalchemy import select, delete
    async with async_session() as s:
        item = (await s.execute(select(Content).where(Content.id == content_id))).scalar_one_or_none()
        if not item or item.content_type != expected_type:
            return
        await s.execute(delete(Content).where(Content.id == content_id))
        await s.commit()


@app.route("/admin/stream/new", methods=["GET", "POST"])
@admin_required
def admin_stream_new():
    if request.method == "POST":
        form, aj, _ = _admin_bundle_attachments_from_request(None)
        asyncio.run(_admin_save_content_item(ContentType.STREAM.value, None, form, aj))
        return redirect("/admin/streams_admin")
    return render_template_string(
        CONTENT_GENERIC_FORM_HTML,
        title="Новий ефір",
        item=None,
        back_url=_admin_back_url_for_type(ContentType.STREAM.value),
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/stream/<int:content_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_stream_edit(content_id: int):
    item = asyncio.run(_admin_load_content_item(content_id))
    if not item or item.content_type != ContentType.STREAM.value:
        return "Not found", 404
    if request.method == "POST":
        form, aj, _ = _admin_bundle_attachments_from_request(item.attachments_json)
        asyncio.run(_admin_save_content_item(ContentType.STREAM.value, content_id, form, aj))
        return redirect("/admin/streams_admin")
    return render_template_string(
        CONTENT_GENERIC_FORM_HTML,
        title=f"Редагувати ефір #{item.id}",
        item=item,
        back_url=_admin_back_url_for_type(ContentType.STREAM.value),
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/stream/<int:content_id>/delete")
@admin_required
def admin_stream_delete(content_id: int):
    asyncio.run(_admin_delete_content_item(content_id, ContentType.STREAM.value))
    return redirect("/admin/streams_admin")


@app.route("/admin/material/new", methods=["GET", "POST"])
@admin_required
def admin_material_new():
    if request.method == "POST":
        form, aj, _ = _admin_bundle_attachments_from_request(None)
        asyncio.run(_admin_save_content_item(ContentType.MATERIAL.value, None, form, aj))
        return redirect("/admin/materials_admin")
    return render_template_string(
        CONTENT_GENERIC_FORM_HTML,
        title="Новий матеріал",
        item=None,
        back_url=_admin_back_url_for_type(ContentType.MATERIAL.value),
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/material/<int:content_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_material_edit(content_id: int):
    item = asyncio.run(_admin_load_content_item(content_id))
    if not item or item.content_type != ContentType.MATERIAL.value:
        return "Not found", 404
    if request.method == "POST":
        form, aj, _ = _admin_bundle_attachments_from_request(item.attachments_json)
        asyncio.run(_admin_save_content_item(ContentType.MATERIAL.value, content_id, form, aj))
        return redirect("/admin/materials_admin")
    return render_template_string(
        CONTENT_GENERIC_FORM_HTML,
        title=f"Редагувати матеріал #{item.id}",
        item=item,
        back_url=_admin_back_url_for_type(ContentType.MATERIAL.value),
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/material/<int:content_id>/delete")
@admin_required
def admin_material_delete(content_id: int):
    asyncio.run(_admin_delete_content_item(content_id, ContentType.MATERIAL.value))
    return redirect("/admin/materials_admin")


@app.route("/admin/book/new", methods=["GET", "POST"])
@admin_required
def admin_book_new():
    if request.method == "POST":
        form, aj, _ = _admin_bundle_attachments_from_request(None)
        asyncio.run(_admin_save_content_item(ContentType.BOOK.value, None, form, aj))
        return redirect("/admin/books_admin")
    return render_template_string(
        CONTENT_GENERIC_FORM_HTML,
        title="Нова книга",
        item=None,
        back_url=_admin_back_url_for_type(ContentType.BOOK.value),
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/book/<int:content_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_book_edit(content_id: int):
    item = asyncio.run(_admin_load_content_item(content_id))
    if not item or item.content_type != ContentType.BOOK.value:
        return "Not found", 404
    if request.method == "POST":
        form, aj, _ = _admin_bundle_attachments_from_request(item.attachments_json)
        asyncio.run(_admin_save_content_item(ContentType.BOOK.value, content_id, form, aj))
        return redirect("/admin/books_admin")
    return render_template_string(
        CONTENT_GENERIC_FORM_HTML,
        title=f"Редагувати книгу #{item.id}",
        item=item,
        back_url=_admin_back_url_for_type(ContentType.BOOK.value),
        media_hint=telegram_limits_hint(),
        media_mode="text",
    )


@app.route("/admin/book/<int:content_id>/delete")
@admin_required
def admin_book_delete(content_id: int):
    asyncio.run(_admin_delete_content_item(content_id, ContentType.BOOK.value))
    return redirect("/admin/books_admin")


@app.route("/webhook/wayforpay", methods=["POST"])
def wayforpay_callback():
    """Callback від WayForPay після оплати"""
    # WayForPay може надсилати як JSON, так і form-urlencoded. Приймаємо обидва формати.
    data = None
    try:
        if request.is_json:
            data = request.get_json(silent=True)
    except Exception:
        data = None
    if not data:
        try:
            if request.form:
                # Деякі інтеграції WayForPay надсилають form-urlencoded як:
                #   "<json string>" = ""
                # Тому якщо рівно один ключ і він схожий на JSON — парсимо його.
                if len(request.form.keys()) == 1:
                    only_key = next(iter(request.form.keys()))
                    s = (only_key or "").strip()
                    if s.startswith("{") and s.endswith("}"):
                        import json as _json
                        data = _json.loads(s)
                    else:
                        data = request.form.to_dict(flat=True)
                else:
                    data = request.form.to_dict(flat=True)
        except Exception:
            data = None
    if not data:
        try:
            raw = (request.data or b"").decode("utf-8", errors="ignore").strip()
            if raw:
                import json as _json
                data = _json.loads(raw)
        except Exception:
            data = None
    if not data:
        return jsonify({"orderReference": "", "status": "accept", "time": int(datetime.utcnow().timestamp())}), 200

    try:
        # Лог для діагностики (не виводимо чутливі дані)
        try:
            safe_keys = [k for k in list(data.keys()) if k not in ("cardPan", "merchantSignature")]
            print(f"WFP callback content_type={request.content_type} keys={safe_keys[:40]}")
        except Exception:
            pass

        merchant = data.get("merchantAccount")
        order_ref = data.get("orderReference", "")
        amount_raw = data.get("amount", "")
        currency = data.get("currency", "UAH")
        auth_code = data.get("authCode", "")
        card_pan = data.get("cardPan", "****")
        status = data.get("transactionStatus", "")
        reason_raw = data.get("reason", "")
        reason_code_raw = data.get("reasonCode", "")
        rec_token = data.get("recToken", "")
        try:
            print(
                f"WFP orderReference={order_ref} transactionStatus={status} "
                f"amount={amount_raw} currency={currency} reason={reason_raw} reasonCode={reason_code_raw}"
            )
        except Exception:
            pass

        sig_valid = verify_callback_signature(
            merchant, order_ref, amount_raw, currency, auth_code, card_pan, status, reason_code_raw,
            data.get("merchantSignature", "")
        )
        if not sig_valid:
            # Не падаємо 400, щоб WayForPay не ретраїв безкінечно.
            print(f"WFP invalid signature for orderReference={order_ref}")
            return jsonify({"orderReference": order_ref, "status": "accept", "time": int(datetime.utcnow().timestamp())}), 200

        asyncio.run(process_payment(data, status, rec_token, order_ref))

        return jsonify({
            "orderReference": order_ref,
            "status": "accept",
            "time": int(datetime.utcnow().timestamp()),
        }), 200
    except Exception as e:
        print(f"WayForPay callback error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"orderReference": data.get("orderReference", ""), "status": "accept", "time": int(datetime.utcnow().timestamp())}), 200


async def process_payment(data: dict, status: str, rec_token: str, order_ref: str):
    """Обробити платіж"""
    telegram_id = None
    parts = order_ref.split("_")
    if len(parts) >= 2 and parts[0] in ("trial", "sub"):
        try:
            telegram_id = int(parts[1])
        except ValueError:
            pass
    elif len(parts) >= 3 and parts[0] == "manual" and parts[1] == "sub":
        try:
            telegram_id = int(parts[2])
        except ValueError:
            pass
    if telegram_id is None:
        from sqlalchemy import select
        async with async_session() as session:
            r = await session.execute(select(User).where(User.order_reference == order_ref))
            u = r.scalar_one_or_none()
            if u:
                telegram_id = u.telegram_id
    if telegram_id is None:
        return

    amount_val = float(str(data.get("amount", 0)).replace(",", ".")) if str(data.get("amount", 0)).strip() else 0.0
    is_trial = order_ref.startswith("trial_") and amount_val <= float(config.PRICE_TRIAL_GRN)
    incoming_processing_ts = 0
    try:
        incoming_processing_ts = int(data.get("processingDate") or 0)
    except Exception:
        incoming_processing_ts = 0

    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            return

        from sqlalchemy import select
        payment = (await session.execute(select(Payment).where(Payment.order_reference == order_ref))).scalar_one_or_none()
        # Idempotency + recurring safety:
        # WayForPay може прислати ще одну успішну транзакцію з тим самим orderReference
        # (регулярне списання/повторна обробка). Якщо відрізняється amount або processingDate,
        # створюємо окремий payment-запис, а не відкидаємо як дубль.
        if payment and status == "Approved":
            payment_approved = (
                (payment.status or "").lower() == "approved"
                or (payment.transaction_status or "").lower() == "approved"
            )
            if payment_approved:
                existing_amount = float(payment.amount or 0.0)
                same_amount = abs(existing_amount - amount_val) < 0.0001
                existing_processing_ts = int(payment.processed_at.timestamp()) if payment.processed_at else 0
                is_new_event = bool(
                    (incoming_processing_ts and existing_processing_ts and incoming_processing_ts > existing_processing_ts)
                    or (not same_amount)
                )
                if not is_new_event:
                    return

                recurring_ref = f"{order_ref}__r_{incoming_processing_ts or int(datetime.utcnow().timestamp())}"
                existing_recurring = (
                    await session.execute(select(Payment).where(Payment.order_reference == recurring_ref))
                ).scalar_one_or_none()
                if existing_recurring:
                    return
                payment = Payment(
                    user_id=user.id,
                    order_reference=recurring_ref,
                    amount=amount_val,
                    currency=data.get("currency", "UAH"),
                    status=status,
                    transaction_status=status,
                    auth_code=data.get("authCode"),
                    card_pan=data.get("cardPan"),
                    rec_token=rec_token or None,
                    processed_at=datetime.utcfromtimestamp(incoming_processing_ts) if incoming_processing_ts else datetime.utcnow(),
                )
                session.add(payment)
                try:
                    await session.flush()
                except Exception:
                    await session.rollback()
                    return

        if not payment:
            payment = Payment(
                user_id=user.id,
                order_reference=order_ref,
                amount=amount_val,
                currency=data.get("currency", "UAH"),
                status=status,
                transaction_status=status,
                auth_code=data.get("authCode"),
                card_pan=data.get("cardPan"),
                rec_token=rec_token or None,
                processed_at=datetime.utcfromtimestamp(incoming_processing_ts) if incoming_processing_ts else datetime.utcnow(),
            )
            session.add(payment)
            # Захист від race condition: якщо паралельно прилетів той самий callback,
            # UNIQUE(order_reference) може впасти на flush/commit. В такому разі просто
            # ігноруємо дубль (перший callback уже обробив оплату).
            try:
                await session.flush()
            except Exception:
                await session.rollback()
                return
        else:
            payment.amount = amount_val if amount_val else payment.amount
            payment.currency = data.get("currency", "UAH")
            payment.status = status
            payment.transaction_status = status
            payment.auth_code = data.get("authCode")
            payment.card_pan = data.get("cardPan")
            payment.rec_token = rec_token or payment.rec_token
            payment.processed_at = datetime.utcfromtimestamp(incoming_processing_ts) if incoming_processing_ts else datetime.utcnow()

        if status == "Approved":
            # Дедуплікація: якщо вже є approved подія з таким самим auth_code+amount для цього юзера,
            # повторний callback не повинен знову активувати підписку і слати "Оплата успішна".
            duplicate_approved = None
            auth_code_in = (data.get("authCode") or "").strip()
            if auth_code_in:
                duplicate_approved = (
                    await session.execute(
                        select(Payment)
                        .where(Payment.user_id == user.id)
                        .where(Payment.id != payment.id)
                        .where((Payment.transaction_status == "Approved") | (Payment.status == "Approved"))
                        .where(Payment.auth_code == auth_code_in)
                        .where(Payment.amount == amount_val)
                    )
                ).scalar_one_or_none()
            if duplicate_approved:
                payment.retry_count = max(int(payment.retry_count or 0), 1)
                await session.commit()
                return

            # Fallback-дедуплікація: деякі callback-и приходять без authCode,
            # тому захищаємося ще й по "нещодавно approved з тим самим amount".
            recent_duplicate = (
                await session.execute(
                    select(Payment)
                    .where(Payment.user_id == user.id)
                    .where(Payment.id != payment.id)
                    .where((Payment.transaction_status == "Approved") | (Payment.status == "Approved"))
                    .where(Payment.amount == amount_val)
                    .where(Payment.processed_at.is_not(None))
                    .where(Payment.processed_at >= datetime.utcnow() - timedelta(minutes=15))
                    .order_by(Payment.processed_at.desc())
                )
            ).scalar_one_or_none()
            if recent_duplicate:
                payment.retry_count = max(int(payment.retry_count or 0), 1)
                await session.commit()
                return

            # Оновити phone/email з WayForPay callback (clientPhone, clientEmail)
            wfp_phone = (
                data.get("clientPhone")
                or data.get("client_phone")
                or data.get("phone")
                or data.get("client_phone_number")
                or ""
            )
            wfp_phone = str(wfp_phone).strip()
            wfp_email = (data.get("clientEmail") or "").strip()
            if wfp_phone:
                user.phone = wfp_phone

            # Якщо оплата прийшла після невдалих retry — закриваємо failure-ланцюг
            # і не переносимо grace-період у новий 30-денний цикл.
            pending_failures = (
                await session.execute(select(PaymentFailure).where(PaymentFailure.user_id == user.id))
            ).scalars().all()
            had_pending_failures = bool(pending_failures)
            for pf_row in pending_failures:
                await session.delete(pf_row)
            if had_pending_failures:
                subs_r = await session.execute(
                    select(Subscription)
                    .where(Subscription.user_id == user.id)
                    .where(Subscription.is_active == True)
                )
                for srow in subs_r.scalars().all():
                    srow.is_active = False

            await activate_subscription(session, user, is_trial=is_trial, rec_token=rec_token or None, order_reference=order_ref)
            # retry_count=1 використовуємо як прапорець "успішне повідомлення вже відправлено"
            already_success_notified = bool(payment.retry_count and int(payment.retry_count) > 0)
            if not already_success_notified:
                payment.retry_count = 1
            await session.commit()
            try:
                print(f"WFP Approved processed telegram_id={telegram_id} phone={'yes' if bool(wfp_phone) else 'no'} trial={is_trial}")
            except Exception:
                pass

            sub = await get_active_subscription(session, user)
            is_trial_payment = is_trial and amount_val <= float(config.PRICE_TRIAL_GRN) + 0.0001
            is_standard_payment = amount_val >= float(config.PRICE_STANDARD_GRN) - 0.01

            if is_trial_payment and not already_success_notified:
                # Перша оплата trial (1 грн) — вітальне повідомлення з доступом до групи.
                group_link = (getattr(config, "CLUB_GROUP_LINK", "") or "").strip()
                join_button = (
                    {"text": "Перейти в групу", "url": group_link}
                    if group_link
                    else {"text": "Перейти в групу", "callback_data": "join_group"}
                )
                send_telegram_message(
                    telegram_id,
                    "✅ Оплата успішна!\n\n"
                    "Інструкція буде скоро.\n"
                    "[Тут буде відео-інструкція]",
                    reply_markup={"inline_keyboard": [[join_button]]},
                )
            elif is_standard_payment:
                from services.payment_notifications import tariff_renewed_message

                end_dt = sub.end_date if sub else datetime.utcnow()
                send_telegram_message(telegram_id, tariff_renewed_message(end_dt))

            add_lead(
                datetime.now(tz=KYIV_TZ) if KYIV_TZ else datetime.utcnow(),
                f"{user.first_name or ''} {user.last_name or ''}".strip() or "—",
                user.username or str(telegram_id),
                user.phone or "—",
                "підписник",
                email="—",
            )
        else:
            st_lower = str(status or "").strip().lower()
            is_failed = st_lower in ("declined", "expired")

            # Ручна оплата (trial/standard): якщо платіж реально відхилено банком —
            # шлемо повідомлення одразу і лише один раз.
            if order_ref.startswith("trial_") or order_ref.startswith("manual_sub_"):
                if is_failed:
                    already_failed_notified = bool(payment.retry_count and int(payment.retry_count) > 0)
                    payment.retry_count = 1
                    await session.commit()
                    if not already_failed_notified:
                        tariff_code = "trial" if order_ref.startswith("trial_") else "standard"
                        send_telegram_message(
                            telegram_id,
                            payment_failed_text(datetime.utcnow()),
                            reply_markup=_failed_payment_retry_markup(telegram_id, tariff_code),
                        )
                    return
                # Якщо це просто відкриття/закриття сторінки без фактичної невдалої транзакції,
                # повідомлення піде окремим job через 5 хв лише один раз.
                await session.commit()
                return

            # Відмова рекурентного списання стандарту.
            is_std_amount = abs(amount_val - float(config.PRICE_STANDARD_GRN)) < 0.01
            is_recurring_ref = order_ref.startswith(("trial_", "sub_", "retry_", "customsub_", "trial2std_"))
            if is_failed and is_std_amount and is_recurring_ref:
                token = rec_token or user.rec_token or ""
                if not token:
                    await session.commit()
                    send_telegram_message(telegram_id, payment_failed_text(datetime.utcnow()))
                    return

                now = datetime.utcnow()
                next_retry = now + timedelta(hours=RETRY_HOURS[0])
                grace_until = now + timedelta(hours=sum(RETRY_HOURS))

                # Поки тривають retry (6 спроб за регламентом) — доступ лишається.
                subs_r = await session.execute(
                    select(Subscription).where(Subscription.user_id == user.id).where(Subscription.is_active == True)
                )
                active_subs = subs_r.scalars().all()
                if active_subs:
                    for srow in active_subs:
                        if srow.end_date < grace_until:
                            srow.end_date = grace_until
                else:
                    session.add(
                        Subscription(
                            user_id=user.id,
                            start_date=now,
                            end_date=grace_until,
                            is_trial=False,
                            is_active=True,
                        )
                    )
                user.status = UserStatus.SUBSCRIBER.value

                existing_pf = (
                    await session.execute(
                        select(PaymentFailure)
                        .where(PaymentFailure.user_id == user.id)
                        .where(PaymentFailure.order_reference == order_ref)
                        .order_by(PaymentFailure.id.desc())
                    )
                ).scalars().first()
                if not existing_pf:
                    session.add(
                        PaymentFailure(
                            user_id=user.id,
                            order_reference=order_ref,
                            rec_token=token,
                            first_failure_at=now,
                            retry_index=0,
                            next_retry_at=next_retry,
                        )
                    )
                    await session.commit()
                    send_telegram_message(telegram_id, payment_failed_text(next_retry))
                else:
                    if not existing_pf.rec_token and token:
                        existing_pf.rec_token = token
                    await session.commit()
                return

            # Для рекурентних списань залишаємо поточну логіку retry.
            token = rec_token or user.rec_token or ""

            # Якщо підписка вже активна — ігноруємо fail callbacks (WayForPay може надсилати Expired паралельно)
            already_active = False
            try:
                already_active = bool(await get_active_subscription(session, user))
            except Exception:
                already_active = False
            if already_active:
                return

            if not token:
                send_telegram_message(telegram_id, payment_failed_text(datetime.utcnow()))
                return

            next_retry = datetime.utcnow() + timedelta(hours=RETRY_HOURS[0])
            pf = PaymentFailure(
                user_id=user.id,
                order_reference=order_ref,
                rec_token=token,
                first_failure_at=datetime.utcnow(),
                retry_index=0,
                next_retry_at=next_retry,
            )
            session.add(pf)
            await session.commit()
            send_telegram_message(telegram_id, payment_failed_text(next_retry))


def run():
    app.run(host="0.0.0.0", port=5000)
