#!/usr/bin/env python3
"""
Запуск Telegram бота
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.bot import main

if __name__ == "__main__":
    asyncio.run(main())
