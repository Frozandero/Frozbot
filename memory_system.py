import sqlite3
import json
import datetime
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio
import os


class MemoryType(Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    CONVERSATION = "conversation"
    USER_INFO = "user_info"
    SERVER_INFO = "server_info"


@dataclass
class MemoryEntry:
    id: str
    user_id: int
    channel_id: int
    guild_id: Optional[int]
    question: str
    answer: str
    timestamp: datetime.datetime
    importance_score: float  # 0.0 to 1.0
    memory_type: str
    tags: List[str]
    context: Dict[str, Any]
    last_accessed: datetime.datetime
    access_count: int


class MemoryManager:
    def __init__(self, db_path: str = "bot_memory.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize the SQLite database with memory tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create memories table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                guild_id INTEGER,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                importance_score REAL NOT NULL,
                memory_type TEXT NOT NULL,
                tags TEXT NOT NULL,
                context TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER DEFAULT 0
            )
        """
        )

        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON memories(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_guild_id ON memories(guild_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_type ON memories(memory_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance_score)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_last_accessed ON memories(last_accessed)"
        )

        conn.commit()
        conn.close()

    def _serialize_datetime(self, dt: datetime.datetime) -> str:
        """Convert datetime to ISO format string for SQLite storage."""
        return dt.isoformat()

    def _deserialize_datetime(self, dt_str: str) -> datetime.datetime:
        """Convert ISO format string back to datetime."""
        return datetime.datetime.fromisoformat(dt_str)

    def _serialize_list(self, lst: List[str]) -> str:
        """Convert list to JSON string for SQLite storage."""
        return json.dumps(lst)

    def _deserialize_list(self, lst_str: str) -> List[str]:
        """Convert JSON string back to list."""
        return json.loads(lst_str)

    def _serialize_dict(self, dct: Dict[str, Any]) -> str:
        """Convert dict to JSON string for SQLite storage."""
        return json.dumps(dct)

    def _deserialize_dict(self, dct_str: str) -> Dict[str, Any]:
        """Convert JSON string back to dict."""
        return json.loads(dct_str)

    def store_memory(self, memory: MemoryEntry) -> bool:
        """Store a new memory entry in the database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO memories 
                (id, user_id, channel_id, guild_id, question, answer, timestamp, 
                 importance_score, memory_type, tags, context, last_accessed, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    memory.id,
                    memory.user_id,
                    memory.channel_id,
                    memory.guild_id,
                    memory.question,
                    memory.answer,
                    self._serialize_datetime(memory.timestamp),
                    memory.importance_score,
                    memory.memory_type,
                    self._serialize_list(memory.tags),
                    self._serialize_dict(memory.context),
                    self._serialize_datetime(memory.last_accessed),
                    memory.access_count,
                ),
            )

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing memory: {e}")
            return False

    def retrieve_memories(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        memory_type: Optional[str] = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> List[MemoryEntry]:
        """Retrieve memories based on various filters."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            query = "SELECT * FROM memories WHERE 1=1"
            params = []

            if user_id is not None:
                query += " AND user_id = ?"
                params.append(user_id)

            if guild_id is not None:
                query += " AND guild_id = ?"
                params.append(guild_id)

            if memory_type is not None:
                query += " AND memory_type = ?"
                params.append(memory_type)

            query += " AND importance_score >= ?"
            params.append(min_importance)

            query += " ORDER BY importance_score DESC, last_accessed DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            memories = []
            for row in rows:
                memory = MemoryEntry(
                    id=row[0],
                    user_id=row[1],
                    channel_id=row[2],
                    guild_id=row[3],
                    question=row[4],
                    answer=row[5],
                    timestamp=self._deserialize_datetime(row[6]),
                    importance_score=row[7],
                    memory_type=row[8],
                    tags=self._deserialize_list(row[9]),
                    context=self._deserialize_dict(row[10]),
                    last_accessed=self._deserialize_datetime(row[11]),
                    access_count=row[12],
                )
                memories.append(memory)

            conn.close()
            return memories
        except Exception as e:
            print(f"Error retrieving memories: {e}")
            return []

    def update_memory_access(self, memory_id: str) -> bool:
        """Update the last accessed time and access count for a memory."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE memories 
                SET last_accessed = ?, access_count = access_count + 1
                WHERE id = ?
            """,
                (self._serialize_datetime(datetime.datetime.now()), memory_id),
            )

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating memory access: {e}")
            return False

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting memory: {e}")
            return False

    def cleanup_old_memories(self, days_old: int = 30, max_memories: int = 1000) -> int:
        """Clean up old and less important memories."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get total count
            cursor.execute("SELECT COUNT(*) FROM memories")
            total_count = cursor.fetchone()[0]

            if total_count <= max_memories:
                conn.close()
                return 0

            # Calculate cutoff date
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
            cutoff_str = self._serialize_datetime(cutoff_date)

            # Delete old, low-importance memories
            cursor.execute(
                """
                DELETE FROM memories 
                WHERE timestamp < ? AND importance_score < 0.3
                ORDER BY importance_score ASC, timestamp ASC
                LIMIT ?
            """,
                (cutoff_str, total_count - max_memories),
            )

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            return deleted_count
        except Exception as e:
            print(f"Error cleaning up memories: {e}")
            return 0


class MemoryAnalyzer:
    """AI-powered memory analysis and importance scoring."""

    def __init__(self, gemini_client):
        self.gemini_client = gemini_client

    async def analyze_question_importance(
        self, question: str, context: Dict[str, Any]
    ) -> float:
        """Analyze the importance of a question for memory storage."""
        if not self.gemini_client:
            return 0.5  # Default medium importance

        try:
            prompt = f"""
            Analyze the importance of this question for long-term memory storage.
            Consider:
            1. Is this a factual question that could be useful later?
            2. Does it reveal user preferences or characteristics?
            3. Is it about a specific person, place, or thing?
            4. Could this information be valuable in future conversations?
            
            Question: {question}
            Context: {json.dumps(context, indent=2)}
            
            Rate importance from 0.0 (not worth remembering) to 1.0 (very important).
            Return only the number.
            """

            # Use your existing Gemini client
            response = await self._call_gemini(prompt)
            if response:
                try:
                    importance = float(response.strip())
                    return max(0.0, min(1.0, importance))  # Clamp between 0.0 and 1.0
                except ValueError:
                    pass

            return 0.5
        except Exception as e:
            print(f"Error analyzing question importance: {e}")
            return 0.5

    async def extract_memory_tags(self, question: str, answer: str) -> List[str]:
        """Extract relevant tags for memory categorization."""
        if not self.gemini_client:
            return ["general"]

        try:
            prompt = f"""
            Extract 3-5 relevant tags for categorizing this Q&A pair in memory.
            Focus on key topics, entities, or themes.
            
            Question: {question}
            Answer: {answer}
            
            Return only the tags, separated by commas.
            """

            response = await self._call_gemini(prompt)
            if response:
                tags = [tag.strip().lower() for tag in response.split(",")]
                return [
                    tag for tag in tags if tag and len(tag) < 50
                ]  # Filter valid tags

            return ["general"]
        except Exception as e:
            print(f"Error extracting memory tags: {e}")
            return ["general"]

    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Gemini API for memory analysis."""
        try:
            # This would integrate with your existing Gemini client
            # You'll need to adapt this to your current setup
            return None  # Placeholder
        except Exception as e:
            print(f"Error calling Gemini for memory analysis: {e}")
            return None


class MemoryContextBuilder:
    """Build context strings that include relevant memories."""

    def __init__(self, memory_manager: MemoryManager):
        self.memory_manager = memory_manager

    def build_memory_context(
        self,
        user_id: int,
        guild_id: Optional[int] = None,
        question: str = "",
        max_memories: int = 5,
    ) -> str:
        """Build a context string including relevant memories."""
        # Get relevant memories
        memories = self.memory_manager.retrieve_memories(
            user_id=user_id, guild_id=guild_id, limit=max_memories, min_importance=0.3
        )

        if not memories:
            return ""

        # Build memory context
        memory_context = "\n\n**Relevant Memories:**\n"
        for i, memory in enumerate(memories, 1):
            memory_context += f"{i}. **{memory.memory_type.title()}** (Importance: {memory.importance_score:.2f})\n"
            memory_context += f"   Q: {memory.question[:100]}{'...' if len(memory.question) > 100 else ''}\n"
            memory_context += f"   A: {memory.answer[:150]}{'...' if len(memory.answer) > 150 else ''}\n"
            memory_context += f"   Tags: {', '.join(memory.tags[:3])}\n"
            memory_context += (
                f"   Last accessed: {memory.timestamp.strftime('%Y-%m-%d')}\n\n"
            )

        return memory_context

    def should_store_memory(
        self, question: str, answer: str, context: Dict[str, Any]
    ) -> bool:
        """Determine if this Q&A should be stored in memory."""
        # Basic heuristics for memory storage
        question_lower = question.lower()
        answer_lower = answer.lower()

        # Don't store very short or very long exchanges
        if len(question) < 10 or len(answer) < 10:
            return False
        if len(question) > 500 or len(answer) > 1000:
            return False

        # Don't store greetings, thanks, etc.
        greetings = ["hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye"]
        if any(greeting in question_lower for greeting in greetings):
            return False

        # Don't store commands or bot responses
        if question.startswith("/") or answer.startswith("I am a bot"):
            return False

        return True
