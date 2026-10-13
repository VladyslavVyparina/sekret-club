"""
Підключення до БД
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from .models import Base
import config

engine = create_async_engine(config.DATABASE_URL, echo=False)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Ініціалізація таблиць + міграція email в users"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Мінімальні міграції для існуючих sqlite БД
        def _migrate(conn_sync):
            from sqlalchemy import text
            try:
                conn_sync.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
            except Exception:
                pass  # колонка вже є

            try:
                conn_sync.execute(text("ALTER TABLE lessons ADD COLUMN photo_file_id VARCHAR(255)"))
            except Exception:
                pass  # колонка вже є

            try:
                conn_sync.execute(text("ALTER TABLE content ADD COLUMN attachments_json TEXT"))
            except Exception:
                pass
            try:
                conn_sync.execute(text("ALTER TABLE lessons ADD COLUMN attachments_json TEXT"))
            except Exception:
                pass
            try:
                conn_sync.execute(text("ALTER TABLE lessons ADD COLUMN link VARCHAR(500)"))
            except Exception:
                pass

            # settings table може не існувати в старій БД
            try:
                conn_sync.execute(text("CREATE TABLE IF NOT EXISTS settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL DEFAULT '', updated_at DATETIME)"))
            except Exception:
                pass

            # tariffs table може не існувати
            try:
                conn_sync.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS tariffs ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "code VARCHAR(50) UNIQUE, "
                        "name VARCHAR(255) NOT NULL, "
                        "price_grn INTEGER NOT NULL, "
                        "is_recurring BOOLEAN NOT NULL DEFAULT 1, "
                        "created_at DATETIME)"
                    )
                )
            except Exception:
                pass

            # pay_links table для коротких посилань оплати
            try:
                conn_sync.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS pay_links ("
                        "code VARCHAR(64) PRIMARY KEY, "
                        "telegram_id INTEGER NOT NULL, "
                        "tariff VARCHAR(20) NOT NULL, "
                        "phone VARCHAR(50), "
                        "created_at DATETIME)"
                    )
                )
            except Exception:
                pass
        await conn.run_sync(_migrate)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
