# Deploy the club bot

## 1. On the server

```bash
cd /path/to/sekret_club
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Environment

```bash
cp .env.example .env
```

Set these yourself. Do not commit the filled file.

- `BOT_TOKEN` from BotFather
- `BASE_URL` as `https://your-domain.com`, the host WayForPay can call
- `CLUB_GROUP_LINK` as the invite to the private group
- `WAYFORPAY_MERCHANT` and `WAYFORPAY_SECRET` from the WayForPay cabinet
- `WAYFORPAY_DOMAIN`

## 3. WayForPay cabinet

- Service URL: `https://your-domain.com/webhook/wayforpay`
- Return URL: `https://t.me/your_bot`, or the group link

## 4. screen

```bash
screen -S sekret_bot
source venv/bin/activate
python run_bot.py
# Ctrl+A, then D

screen -S sekret_web
source venv/bin/activate
python run_web.py
# Ctrl+A, then D

screen -ls
```

Both processes have to stay up. The bot sends people to pay. The web process is what hears that they did.

## 5. systemd

`/etc/systemd/system/sekret-bot.service`:

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

`/etc/systemd/system/sekret-web.service` is the same unit with `ExecStart` pointing at `run_web.py` and the description “Sekret Club Web Server (WayForPay)”.

```bash
sudo systemctl daemon-reload
sudo systemctl enable sekret-bot sekret-web
sudo systemctl start sekret-bot sekret-web
sudo systemctl status sekret-bot sekret-web
```

## 6. Nginx

WayForPay needs HTTPS for the callback.

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

## 7. Restart

```bash
screen -r sekret_bot
# Ctrl+C, then python run_bot.py, then Ctrl+A, D

sudo systemctl restart sekret-bot
sudo systemctl restart sekret-web
```
