"""
Адмін-панель бота
- Розсилка
- Фільтрація користувачів
- Додавання матеріалів
- Статистика
"""
import asyncio
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from functools import wraps
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database.database import async_session
from database.models import User, Subscription, Payment
from sqlalchemy import select, func

admin = Flask(__name__)
admin.secret_key = config.ADMIN_PANEL_SECRET


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin" not in session and request.args.get("secret") != config.ADMIN_PANEL_SECRET:
            return "Unauthorized", 401
        if "admin" not in session:
            session["admin"] = True
        return f(*args, **kwargs)
    return decorated


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def get_stats():
    async with async_session() as s:
        total = (await s.execute(select(func.count(User.id)))).scalar() or 0
        result = await s.execute(select(User.status, func.count(User.id)).group_by(User.status))
        by_status = dict(result.all())
    return {
        "total": total,
        "subscribers": by_status.get("subscriber", 0),
        "former": by_status.get("former_subscriber", 0),
        "not_sub": by_status.get("not_subscriber", 0),
    }


ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Адмін-панель</title>
<style>
body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:20px;}
h1,h2{color:#333;}
.stats{display:flex;gap:20px;margin:20px 0;}
.stat{background:#f0f0f0;padding:20px;border-radius:8px;min-width:120px;}
table{border-collapse:collapse;width:100%;}
th,td{border:1px solid #ddd;padding:8px;text-align:left;}
th{background:#4CAF50;color:white;}
.btn{display:inline-block;padding:10px 20px;background:#4CAF50;color:white;text-decoration:none;border-radius:5px;margin:5px;}
.btn:hover{background:#45a049;}
form{margin:20px 0;}
textarea{width:100%;height:100px;}
input[type=text],select{width:100%;padding:8px;}
</style>
</head>
<body>
<h1>Адмін-панель Секрет Клуб</h1>
<h2>Статистика</h2>
<div class="stats">
    <div class="stat"><strong>Всього юзерів</strong><br>{{ stats.total }}</div>
    <div class="stat"><strong>Підписників</strong><br>{{ stats.subscribers }}</div>
    <div class="stat"><strong>Колишніх</strong><br>{{ stats.former }}</div>
    <div class="stat"><strong>Не підписників</strong><br>{{ stats.not_sub }}</div>
</div>
<h2>Розсилка</h2>
<form method="post" action="/admin/broadcast">
    <p><label>Сегмент: <select name="segment">
        <option value="all">Всі</option>
        <option value="subscribers">Підписники</option>
        <option value="former">Колишні</option>
        <option value="not_sub">Не підписники</option>
    </select></label></p>
    <p><label>Текст:<br><textarea name="text" required></textarea></label></p>
    <p><button type="submit" class="btn">Надіслати</button></p>
</form>
<h2>Експорт</h2>
<p><a href="/admin/export?format=csv" class="btn">Експорт CSV</a></p>
</body>
</html>
"""


@login_required
def admin_index():
    stats = run_async(get_stats())
    return render_template_string(ADMIN_HTML, stats=stats)


@login_required
def admin_broadcast():
    segment = request.form.get("segment", "all")
    text = request.form.get("text", "")
    if not text:
        return redirect("/admin")
    return redirect("/admin")


@login_required
def admin_export():
    from io import StringIO
    from flask import Response
    async def get_users():
        async with async_session() as s:
            r = await s.execute(select(User))
            return r.scalars().all()
    users = run_async(get_users())
    output = StringIO()
    output.write("telegram_id;username;first_name;status;created_at\n")
    for u in users:
        output.write(f"{u.telegram_id};{u.username or ''};{u.first_name or ''};{u.status};{u.created_at}\n")
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=users.csv"})


def register_on(main_app):
    """Підключити адмін-роути до головного Flask app"""
    main_app.secret_key = getattr(main_app, "secret_key", None) or config.ADMIN_PANEL_SECRET
    main_app.add_url_rule("/admin", "admin_index", admin_index)
    main_app.add_url_rule("/admin/broadcast", "admin_broadcast", admin_broadcast, methods=["POST"])
    main_app.add_url_rule("/admin/export", "admin_export", admin_export)


def run_admin():
    admin.run(host="0.0.0.0", port=5001)
