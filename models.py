from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    id: int
    username: str
    created_at: datetime


@dataclass
class Queue:
    id: int
    name: str
    creator_id: int
    created_at: datetime


@dataclass
class QueueMember:
    queue_id: int
    user_id: int
    position: int
    joined_at: datetime
    user: Optional[User] = None
