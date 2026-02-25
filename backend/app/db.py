import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "navigo.db")

async def init_db():
    """Initialize the database schema for user preferences and chat history."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT PRIMARY KEY,
                preferences_json TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                thread_id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_db_connection():
    """Yield a fresh async connection to the sqlite database."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
