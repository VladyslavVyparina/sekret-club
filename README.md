# Секрет Клуб

Бот закритого клубу: підписка через WayForPay, база знань, розклад і адмінка.

**Стек.** Python, aiogram, Flask, WayForPay, Google Sheets.

Публічний кейс. Робоча копія з паролями і базами лишається локально і сюди не входить.

---

# Секрет Клуб — Telegram бот

Бот для клубу з підпискою через WayForPay, базою знань та адмін-панеллю.

## Структура проекту

```
sekret_club/
├── bot/              # Telegram бот (aiogram)
├── database/         # Моделі та підключення БД
├── services/         # WayForPay, Google Sheets
├── web/              # Flask: WayForPay callback, адмін-панель
├── data/             # База знань (курси, уроки)
├── config.py
├── run_bot.py        # Запуск бота
├── run_web.py        # Запуск web (WayForPay)
└── requirements.txt
```

## Швидкий старт

### 1. Встановлення залежностей

```bash
cd /Users/macbookpro/Desktop/sekret_club
python3 -m venv venv
source venv/bin/activate   # Linux/Mac
# або: venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Налаштування

Скопіюйте `.env.example` в `.env` і вкажіть:
- `BOT_TOKEN` — токен бота
- `BASE_URL` — домен сервера (для посилань на оплату та webhook WayForPay)
- `CLUB_GROUP_LINK` — посилання-запрошення в ТГ-групу клубу
- `GOOGLE_CREDENTIALS_FILE` та `GOOGLE_SHEET_ID` — для інтеграції з Google Таблицями

### 3. WayForPay

У кабінеті WayForPay вкажіть:
- **Service URL (callback):** `https://ВАШ_ДОМЕН/webhook/wayforpay`
- **Return URL:** посилання на бота або групу

### 4. Запуск на сервері

**Бот (polling):**
```bash
python run_bot.py
```

**Web-сервер (WayForPay callback):**
```bash
python run_web.py
```

**Через systemd (Linux):**

Створіть `/etc/systemd/system/sekret-bot.service`:
```ini
[Unit]
Description=Sekret Club Telegram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/sekret_club
ExecStart=/path/to/sekret_club/venv/bin/python run_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Створіть `/etc/systemd/system/sekret-web.service`:
```ini
[Unit]
Description=Sekret Club Web (WayForPay)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/sekret_club
ExecStart=/path/to/sekret_club/venv/bin/python run_web.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Команди:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sekret-bot sekret-web
sudo systemctl start sekret-bot sekret-web
sudo systemctl status sekret-bot sekret-web
```

**Через screen (простий варіант):**
```bash
screen -S bot
source venv/bin/activate
python run_bot.py
# Ctrl+A, D — вийти з screen

screen -S web
source venv/bin/activate
python run_web.py
# Ctrl+A, D
```

### 5. Адмін-панель

Запустіть окремо на порту 5001:
```bash
python -c "from web.admin_panel import run_admin; run_admin()"
```

Або обʼєднайте з Flask-додатком у `run_web.py`. Доступ: `https://ВАШ_ДОМЕН:5001/admin?secret=ВАШ_ADMIN_PANEL_SECRET`

## Команди для продакшн-сервера

```bash
# 1. Клонування (якщо з git)
git clone <repo> sekret_club && cd sekret_club

# 2. Venv та залежності
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Конфіг
cp .env.example .env
nano .env   # відредагувати

# 4. Запуск у фоні (screen)
screen -S sekret_bot -dm bash -c "cd $(pwd) && source venv/bin/activate && python run_bot.py"
screen -S sekret_web -dm bash -c "cd $(pwd) && source venv/bin/activate && python run_web.py"

# Перевірка
screen -ls
```

## Nginx (якщо потрібен HTTPS для WayForPay)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
