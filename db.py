import aiosqlite
from config import DB_PATH
from datetime import datetime, timedelta

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                nick TEXT UNIQUE NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                discord_id TEXT,
                battle_id TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (discord_id, battle_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def log_action(user_id: str, action: str, details: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO audit_logs (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, details)
        )
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        await db.execute("DELETE FROM audit_logs WHERE timestamp < ?", (seven_days_ago,))
        await db.commit()

async def get_recent_logs(limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, action, details, timestamp FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
        data = await cursor.fetchall()
        await cursor.close()
        return data

# attendency
async def check_and_add_attendance(discord_id: str, battle_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO attendance (discord_id, battle_id) VALUES (?, ?)",
                (discord_id, battle_id)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def get_attendance_stats(days: int):
    """Считает стату за последние N дней и возвращает (всего_боев, список_игроков)"""
    async with aiosqlite.connect(DB_PATH) as db:

        cursor = await db.execute(
            "SELECT COUNT(DISTINCT battle_id) FROM attendance WHERE timestamp >= datetime('now', ?)",
            (f"-{days} days",)
        )
        total_battles_row = await cursor.fetchone()
        total_battles = total_battles_row[0] if total_battles_row else 0


        query = """
            SELECT u.discord_id, u.nick, COUNT(a.battle_id) as user_battles
            FROM users u
            LEFT JOIN attendance a ON u.discord_id = a.discord_id AND a.timestamp >= datetime('now', ?)
            GROUP BY u.discord_id
            ORDER BY user_battles DESC
        """
        cursor = await db.execute(query, (f"-{days} days",))
        data = await cursor.fetchall()
        await cursor.close()
        return total_battles, data


async def get_user_by_discord_id(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT nick FROM users WHERE discord_id=?", (discord_id,))
        data = await cursor.fetchone()
        await cursor.close()
        return data

async def get_user_by_nick(nick: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT discord_id, nick FROM users WHERE LOWER(nick)=?", (nick.lower(),))
        data = await cursor.fetchone()
        await cursor.close()
        return data

async def register_user(discord_id: str, nick: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (discord_id, nick) VALUES (?, ?)", (discord_id, nick))
        await db.commit()

async def get_all_registered_nicks():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT discord_id, nick FROM users")
        data = await cursor.fetchall()
        await cursor.close()
        return data

async def remove_user(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE discord_id=?", (discord_id,))
        await db.commit()


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        await db.commit()

async def get_setting(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        data = await cursor.fetchone()
        await cursor.close()
        return data[0] if data else None