# Sekret Club

A private-club Telegram bot: paid subscription through WayForPay, a knowledge base of courses, and a small admin site for the people who run the club.

## Problem

Members needed a paid gate, a place to read lessons, and a link into the club group. The owner needed the payment callback, the member list, and a sheet export without running SQL by hand.

## What was built

- `bot/` is the aiogram bot: subscription, lessons, and the group invite after payment.
- `database/` is the member and payment store.
- `services/` talks to WayForPay and Google Sheets.
- `web/` is a Flask app: the WayForPay callback and the admin panel.
- `data/` holds the course and lesson content.
- `scheduler_tasks.py` runs recurring jobs.
- `run_bot.py` and `run_web.py` are the two processes. Both have to be up in production, because the bot sends people to pay and the web process is what hears that they did.

## How it works

A guest opens the bot and is offered a plan. The bot creates a WayForPay invoice using `BASE_URL` so the return and the webhook land on this server. Flask receives the callback, marks the member paid, and the bot can then show `CLUB_GROUP_LINK`. Lessons are read from `data/`. Sheets receive a row through the service account file, which is not published here.

## Stack

Python, aiogram, Flask, WayForPay, Google Sheets.

## Run locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run_web.py
python run_bot.py
```

Set `BOT_TOKEN`, `BASE_URL`, `CLUB_GROUP_LINK`, and the Google sheet id in `.env`.

## What this public copy leaves out

`.env` and `credentials.json`.
