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
            CREATE TABLE IF NOT EXISTS user_preference_facts (
                user_id TEXT NOT NULL,
                pref_key TEXT NOT NULL,
                pref_value TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7,
                evidence TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, pref_key)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_preference_facts_user_updated
            ON user_preference_facts(user_id, updated_at DESC)
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
