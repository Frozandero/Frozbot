import uuid
import datetime
from typing import Optional, Dict, Any
from memory_system import (
    MemoryManager,
    MemoryAnalyzer,
    MemoryContextBuilder,
    MemoryEntry,
    MemoryType,
)


class BotMemoryIntegration:
    """Integrates the memory system with the Discord bot."""

    def __init__(self, gemini_client=None):
        self.memory_manager = MemoryManager()
        self.memory_analyzer = MemoryAnalyzer(gemini_client)
        self.context_builder = MemoryContextBuilder(self.memory_manager)

        # Memory storage settings
        self.auto_store_memories = True
        self.min_importance_threshold = 0.3
        self.max_memories_per_user = 100
        self.max_memories_per_guild = 500

    async def process_question_answer(
        self,
        user_id: int,
        channel_id: int,
        guild_id: Optional[int],
        question: str,
        answer: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """Process a Q&A pair and decide whether to store it in memory."""
        if not self.auto_store_memories:
            return None

        # Check if we should store this memory
        if not self.context_builder.should_store_memory(question, answer, context):
            return None

        # Analyze importance
        importance = await self.memory_analyzer.analyze_question_importance(
            question, context
        )

        # Only store if importance meets threshold
        if importance < self.min_importance_threshold:
            return None

        # Extract tags
        tags = await self.memory_analyzer.extract_memory_tags(question, answer)

        # Determine memory type
        memory_type = self._determine_memory_type(question, answer, context)

        # Create memory entry
        memory = MemoryEntry(
            id=str(uuid.uuid4()),
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            question=question,
            answer=answer,
            timestamp=datetime.datetime.now(),
            importance_score=importance,
            memory_type=memory_type,
            tags=tags,
            context=context,
            last_accessed=datetime.datetime.now(),
            access_count=1,
        )

        # Store the memory
        if self.memory_manager.store_memory(memory):
            print(
                f"💾 Stored memory: {question[:50]}... (importance: {importance:.2f})"
            )
            return memory.id
        else:
            print(f"❌ Failed to store memory: {question[:50]}...")
            return None

    def _determine_memory_type(
        self, question: str, answer: str, context: Dict[str, Any]
    ) -> str:
        """Determine the type of memory based on content and context."""
        question_lower = question.lower()
        answer_lower = answer.lower()

        # Check for user preferences
        preference_keywords = [
            "like",
            "prefer",
            "favorite",
            "hate",
            "dislike",
            "enjoy",
            "love",
        ]
        if any(
            keyword in question_lower or keyword in answer_lower
            for keyword in preference_keywords
        ):
            return MemoryType.PREFERENCE.value

        # Check for user information
        user_info_keywords = [
            "name",
            "age",
            "birthday",
            "location",
            "job",
            "work",
            "school",
            "hobby",
        ]
        if any(
            keyword in question_lower or keyword in answer_lower
            for keyword in user_info_keywords
        ):
            return MemoryType.USER_INFO.value

        # Check for server information
        if "server" in question_lower or "guild" in question_lower:
            return MemoryType.SERVER_INFO.value

        # Check for factual information
        fact_keywords = [
            "what is",
            "who is",
            "when",
            "where",
            "how",
            "why",
            "definition",
            "meaning",
        ]
        if any(keyword in question_lower for keyword in fact_keywords):
            return MemoryType.FACT.value

        # Default to conversation
        return MemoryType.CONVERSATION.value

    def get_memory_context(
        self, user_id: int, guild_id: Optional[int] = None, question: str = ""
    ) -> str:
        """Get relevant memory context for a user."""
        return self.context_builder.build_memory_context(
            user_id=user_id, guild_id=guild_id, question=question
        )

    def search_memories(
        self,
        query: str,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        limit: int = 10,
    ) -> list:
        """Search memories by content."""
        # Simple text search - you could enhance this with vector embeddings later
        memories = self.memory_manager.retrieve_memories(
            user_id=user_id, guild_id=guild_id, limit=100  # Get more to search through
        )

        # Simple keyword matching
        query_lower = query.lower()
        relevant_memories = []

        for memory in memories:
            # Check if query appears in question or answer
            if (
                query_lower in memory.question.lower()
                or query_lower in memory.answer.lower()
                or any(tag.lower() in query_lower for tag in memory.tags)
            ):
                relevant_memories.append(memory)

        # Sort by relevance (importance + recency)
        relevant_memories.sort(
            key=lambda m: (m.importance_score, m.last_accessed.timestamp()),
            reverse=True,
        )

        return relevant_memories[:limit]

    def get_user_memory_stats(self, user_id: int) -> Dict[str, Any]:
        """Get memory statistics for a user."""
        memories = self.memory_manager.retrieve_memories(user_id=user_id, limit=1000)

        if not memories:
            return {
                "total_memories": 0,
                "memory_types": {},
                "average_importance": 0.0,
                "oldest_memory": None,
                "newest_memory": None,
            }

        # Count by type
        type_counts = {}
        importance_sum = 0.0
        oldest = memories[0].timestamp
        newest = memories[0].timestamp

        for memory in memories:
            # Type counts
            memory_type = memory.memory_type
            type_counts[memory_type] = type_counts.get(memory_type, 0) + 1

            # Importance
            importance_sum += memory.importance_score

            # Dates
            if memory.timestamp < oldest:
                oldest = memory.timestamp
            if memory.timestamp > newest:
                newest = memory.timestamp

        return {
            "total_memories": len(memories),
            "memory_types": type_counts,
            "average_importance": importance_sum / len(memories),
            "oldest_memory": oldest.strftime("%Y-%m-%d"),
            "newest_memory": newest.strftime("%Y-%m-%d"),
        }

    def cleanup_old_memories(self) -> int:
        """Clean up old and less important memories."""
        return self.memory_manager.cleanup_old_memories(days_old=30, max_memories=1000)

    def delete_user_memories(self, user_id: int) -> int:
        """Delete all memories for a specific user."""
        memories = self.memory_manager.retrieve_memories(user_id=user_id, limit=10000)
        deleted_count = 0

        for memory in memories:
            if self.memory_manager.delete_memory(memory.id):
                deleted_count += 1

        return deleted_count


# Memory commands for Discord bot
class MemoryCommands:
    """Discord slash commands for memory management."""

    def __init__(self, memory_integration: BotMemoryIntegration):
        self.memory = memory_integration

    async def memory_stats_command(self, interaction, user=None):
        """Show memory statistics for a user."""
        target_user = user if user else interaction.user

        stats = self.memory.get_user_memory_stats(target_user.id)

        if stats["total_memories"] == 0:
            await interaction.response.send_message(
                f"📊 **Memory Stats for {target_user.display_name}**\n\n"
                "No memories stored yet.",
                ephemeral=True,
            )
            return

        # Build stats message
        stats_msg = f"📊 **Memory Stats for {target_user.display_name}**\n\n"
        stats_msg += f"**Total Memories:** {stats['total_memories']}\n"
        stats_msg += f"**Average Importance:** {stats['average_importance']:.2f}\n"
        stats_msg += f"**Oldest Memory:** {stats['oldest_memory']}\n"
        stats_msg += f"**Newest Memory:** {stats['newest_memory']}\n\n"

        stats_msg += "**Memory Types:**\n"
        for memory_type, count in stats["memory_types"].items():
            stats_msg += f"• {memory_type.title()}: {count}\n"

        await interaction.response.send_message(stats_msg, ephemeral=True)

    async def search_memories_command(self, interaction, query: str):
        """Search through stored memories."""
        if len(query) < 3:
            await interaction.response.send_message(
                "❌ **Search Query Too Short**\n\n"
                "Please provide a search query of at least 3 characters.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        # Search memories
        memories = self.memory.search_memories(
            query=query,
            user_id=interaction.user.id,
            guild_id=interaction.guild.id if interaction.guild else None,
            limit=5,
        )

        if not memories:
            await interaction.followup.send(
                f"🔍 **Memory Search Results**\n\n"
                f"**Query:** {query}\n\n"
                "No memories found matching your search.",
                ephemeral=True,
            )
            return

        # Build search results
        results_msg = f"🔍 **Memory Search Results**\n\n"
        results_msg += f"**Query:** {query}\n"
        results_msg += f"**Found:** {len(memories)} memories\n\n"

        for i, memory in enumerate(memories, 1):
            results_msg += f"**{i}. {memory.memory_type.title()}** (Importance: {memory.importance_score:.2f})\n"
            results_msg += f"Q: {memory.question[:80]}{'...' if len(memory.question) > 80 else ''}\n"
            results_msg += (
                f"A: {memory.answer[:100]}{'...' if len(memory.answer) > 100 else ''}\n"
            )
            results_msg += f"Tags: {', '.join(memory.tags[:3])}\n"
            results_msg += f"Date: {memory.timestamp.strftime('%Y-%m-%d')}\n\n"

        await interaction.followup.send(results_msg, ephemeral=True)

    async def forget_me_command(self, interaction):
        """Delete all memories for the user."""
        await interaction.response.defer(thinking=True)

        # Confirm deletion
        confirm_msg = (
            "🗑️ **Delete All Memories**\n\n"
            "⚠️ **Warning:** This will permanently delete ALL your stored memories.\n"
            "This action cannot be undone.\n\n"
            "Are you sure you want to continue?"
        )

        # You could add confirmation buttons here
        # For now, just delete directly

        deleted_count = self.memory.delete_user_memories(interaction.user.id)

        await interaction.followup.send(
            f"🗑️ **Memories Deleted**\n\n"
            f"✅ Successfully deleted {deleted_count} memories.\n"
            "All your stored information has been removed.",
            ephemeral=True,
        )

    async def memory_help_command(self, interaction):
        """Show help for memory commands."""
        help_msg = (
            "🧠 **Memory System Help**\n\n"
            "**Available Commands:**\n"
            "• `/memorystats [user]` - Show memory statistics\n"
            "• `/searchmemories <query>` - Search your memories\n"
            "• `/forgetme` - Delete all your memories\n"
            "• `/memoryhelp` - Show this help message\n\n"
            "**How It Works:**\n"
            "The bot automatically stores important conversations and facts about you.\n"
            "It uses AI to determine what's worth remembering and categorizes memories.\n"
            "Your memories are private and only visible to you.\n\n"
            "**Memory Types:**\n"
            "• **Facts** - General knowledge and information\n"
            "• **Preferences** - Your likes, dislikes, and choices\n"
            "• **User Info** - Personal details about you\n"
            "• **Conversations** - Important chat exchanges\n"
            "• **Server Info** - Information about servers you're in"
        )

        await interaction.response.send_message(help_msg, ephemeral=True)
