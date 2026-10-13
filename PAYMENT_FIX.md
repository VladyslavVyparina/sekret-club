# Виправлення оплати (ERR_CONNECTION_REFUSED)

## 1. Відкрити порт 5000 на VPS

Запусти на сервері:

```bash
ufw allow 5000
ufw reload
ufw status
```

Або якщо використовуєш iptables:
```bash
iptables -A INPUT -p tcp --dport 5000 -j ACCEPT
```

## 2. Переконатися, що BASE_URL з портом

У `.env`:
```
BASE_URL=http://173.242.57.2:5000
```

## 3. Запустити обидва процеси

```bash
# Термінал 1
python3 run_bot.py

# Термінал 2
python3 run_web.py
```

## 4. Перевірка

Відкрий у браузері: http://173.242.57.2:5000/admin?secret=change_me_secret_key

Якщо адмінка відкривається — оплата теж буде працювати.
