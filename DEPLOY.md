# Команди для розгортання бота на сервері

## 1. Підготовка на сервері

```bash
# Перейти в директорію проекту
cd /path/to/sekret_club

# Створити віртуальне середовище
python3 -m venv venv

# Активувати (Linux/Mac)
source venv/bin/activate

# Встановити залежності
pip install -r requirements.txt
```

## 2. Налаштування .env

```bash
cp .env.example .env
nano .env
```

Обов'язково вкажіть:
- `BOT_TOKEN=8582743573:AAG4EPq0NIydAq7gMk8xa9H9vRX9OCrNukw`
- `BASE_URL=https://ваш-домен.com` (де буде доступний webhook WayForPay)
- `CLUB_GROUP_LINK=https://t.me/+xxx` (посилання-запрошення в ТГ-групу)
- `WAYFORPAY_MERCHANT=freelance_user_65cf444d78d4b`
- `WAYFORPAY_SECRET=73bff90ebaef23615ee044b658104f6ac3783874`

## 3. WayForPay

У кабінеті WayForPay вкажіть:
- **Service URL:** `https://ваш-домен.com/webhook/wayforpay`
- **Return URL:** `https://t.me/ваш_бот` (або посилання на групу)

## 4. Запуск через screen

```bash
# Бот
screen -S sekret_bot
source venv/bin/activate
python run_bot.py
# Натиснути Ctrl+A, потім D (відʼєднатися)

# Web-сервер (WayForPay)
screen -S sekret_web
source venv/bin/activate
python run_web.py
# Ctrl+A, D

# Перевірка
screen -ls
```

## 5. Запуск через systemd

Створіть файл `/etc/systemd/system/sekret-bot.service`:

```ini
[Unit]
Description=Sekret Club Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/sekret_club
Environment=PATH=/path/to/sekret_club/venv/bin
ExecStart=/path/to/sekret_club/venv/bin/python run_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Створіть `/etc/systemd/system/sekret-web.service`:

```ini
[Unit]
Description=Sekret Club Web Server (WayForPay)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/sekret_club
Environment=PATH=/path/to/sekret_club/venv/bin
ExecStart=/path/to/sekret_club/venv/bin/python run_web.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Команди:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sekret-bot sekret-web
sudo systemctl start sekret-bot
sudo systemctl start sekret-web
sudo systemctl status sekret-bot sekret-web
```

## 6. Nginx (проксування для HTTPS)

Щоб WayForPay міг надсилати callback по HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 7. Перезапуск

```bash
# Screen
screen -r sekret_bot   # підключитися
# Ctrl+C, потім python run_bot.py
# Ctrl+A, D

# Systemd
sudo systemctl restart sekret-bot
sudo systemctl restart sekret-web
```
