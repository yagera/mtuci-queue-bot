import aiosqlite
import logging
from datetime import datetime
from typing import Optional, List
from models import User, Queue, QueueMember

logger = logging.getLogger(__name__)


class Database:
    
    def __init__(self, db_path: str = "queue_bot.db"):
        self.db_path = db_path
    
    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS queues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP DEFAULT (datetime('now', '+1 day')),
                    FOREIGN KEY (creator_id) REFERENCES users (id)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS queue_members (
                    queue_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (queue_id, user_id),
                    FOREIGN KEY (queue_id) REFERENCES queues (id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_queue_members_queue_id ON queue_members (queue_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_queue_members_position ON queue_members (queue_id, position)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_queues_expires_at ON queues (expires_at)")
            
            await db.commit()
            logger.info("База данных инициализирована")
    
    async def create_user(self, user_id: int, username: str) -> User:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (id, username) VALUES (?, ?)",
                (user_id, username)
            )
            await db.commit()
            return User(id=user_id, username=username, created_at=datetime.now())
    
    async def get_user(self, user_id: int) -> Optional[User]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(id=row[0], username=row[1], created_at=datetime.fromisoformat(row[2]))
                return None
    
    async def create_queue(self, name: str, creator_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO queues (name, creator_id) VALUES (?, ?)",
                (name, creator_id)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_queue(self, queue_id: int) -> Optional[Queue]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, name, creator_id, created_at, expires_at FROM queues WHERE id = ? AND expires_at > datetime('now')",
                (queue_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Queue(
                        id=row[0],
                        name=row[1],
                        creator_id=row[2],
                        created_at=datetime.fromisoformat(row[3]),
                        expires_at=datetime.fromisoformat(row[4])
                    )
                return None
    
    async def get_all_queues(self) -> List[Queue]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, name, creator_id, created_at, expires_at FROM queues WHERE expires_at > datetime('now') ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    Queue(
                        id=row[0],
                        name=row[1],
                        creator_id=row[2],
                        created_at=datetime.fromisoformat(row[3]),
                        expires_at=datetime.fromisoformat(row[4])
                    )
                    for row in rows
                ]
    
    async def add_to_queue(self, queue_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM queue_members WHERE queue_id = ?",
                (queue_id,)
            ) as cursor:
                position = (await cursor.fetchone())[0]
            
            await db.execute(
                "INSERT INTO queue_members (queue_id, user_id, position) VALUES (?, ?, ?)",
                (queue_id, user_id, position)
            )
            await db.commit()
            return position
    
    async def remove_from_queue(self, queue_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT position FROM queue_members WHERE queue_id = ? AND user_id = ?",
                (queue_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return
                removed_position = row[0]
            
            await db.execute(
                "DELETE FROM queue_members WHERE queue_id = ? AND user_id = ?",
                (queue_id, user_id)
            )
            
            await db.execute(
                "UPDATE queue_members SET position = position - 1 WHERE queue_id = ? AND position > ?",
                (queue_id, removed_position)
            )
            
            await db.commit()
    
    async def get_queue_member(self, queue_id: int, user_id: int) -> Optional[QueueMember]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT qm.queue_id, qm.user_id, qm.position, qm.joined_at, u.username
                FROM queue_members qm
                JOIN users u ON qm.user_id = u.id
                WHERE qm.queue_id = ? AND qm.user_id = ?
            """, (queue_id, user_id)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return QueueMember(
                        queue_id=row[0],
                        user_id=row[1],
                        position=row[2],
                        joined_at=datetime.fromisoformat(row[3]),
                        user=User(id=row[1], username=row[4], created_at=datetime.now())
                    )
                return None
    
    async def get_next_in_queue(self, queue_id: int) -> Optional[QueueMember]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT qm.queue_id, qm.user_id, qm.position, qm.joined_at, u.username
                FROM queue_members qm
                JOIN users u ON qm.user_id = u.id
                WHERE qm.queue_id = ?
                ORDER BY qm.position ASC
                LIMIT 1
            """, (queue_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return QueueMember(
                        queue_id=row[0],
                        user_id=row[1],
                        position=row[2],
                        joined_at=datetime.fromisoformat(row[3]),
                        user=User(id=row[1], username=row[4], created_at=datetime.now())
                    )
                return None
    
    async def get_queue_member_count(self, queue_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM queue_members WHERE queue_id = ?",
                (queue_id,)
            ) as cursor:
                return (await cursor.fetchone())[0]
    
    async def get_queue_members(self, queue_id: int) -> List[QueueMember]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT qm.queue_id, qm.user_id, qm.position, qm.joined_at, u.username
                FROM queue_members qm
                JOIN users u ON qm.user_id = u.id
                WHERE qm.queue_id = ?
                ORDER BY qm.position ASC
            """, (queue_id,)) as cursor:
                rows = await cursor.fetchall()
                return [
                    QueueMember(
                        queue_id=row[0],
                        user_id=row[1],
                        position=row[2],
                        joined_at=datetime.fromisoformat(row[3]),
                        user=User(id=row[1], username=row[4], created_at=datetime.now())
                    )
                    for row in rows
                ]
    
    async def delete_queue(self, queue_id: int, creator_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id FROM queues WHERE id = ? AND creator_id = ?",
                (queue_id, creator_id)
            ) as cursor:
                if not await cursor.fetchone():
                    return False
            
            await db.execute(
                "DELETE FROM queues WHERE id = ? AND creator_id = ?",
                (queue_id, creator_id)
            )
            await db.commit()
            return True
    
    async def remove_user_from_queue(self, queue_id: int, user_id: int, creator_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id FROM queues WHERE id = ? AND creator_id = ?",
                (queue_id, creator_id)
            ) as cursor:
                if not await cursor.fetchone():
                    return False
            
            async with db.execute(
                "SELECT position FROM queue_members WHERE queue_id = ? AND user_id = ?",
                (queue_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return False
                removed_position = row[0]
            
            await db.execute(
                "DELETE FROM queue_members WHERE queue_id = ? AND user_id = ?",
                (queue_id, user_id)
            )
            
            await db.execute(
                "UPDATE queue_members SET position = position - 1 WHERE queue_id = ? AND position > ?",
                (queue_id, removed_position)
            )
            
            await db.commit()
            return True
    
    async def cleanup_expired_queues(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM queues WHERE expires_at <= datetime('now')"
            )
            await db.commit()
    
    async def get_queue_with_members(self, queue_id: int) -> Optional[Queue]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, name, creator_id, created_at, expires_at FROM queues WHERE id = ? AND expires_at > datetime('now')",
                (queue_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Queue(
                        id=row[0],
                        name=row[1],
                        creator_id=row[2],
                        created_at=datetime.fromisoformat(row[3]),
                        expires_at=datetime.fromisoformat(row[4])
                    )
                return None
