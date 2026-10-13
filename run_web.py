#!/usr/bin/env python3
"""
Запуск web-сервера (WayForPay callback + payment redirect)
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def init():
    from database.database import init_db
    asyncio.run(init_db())


if __name__ == "__main__":
    init()
    from web.wayforpay_server import app
    app.run(host="0.0.0.0", port=5000)
