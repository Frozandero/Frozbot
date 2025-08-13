# Memory System Integration Guide

This guide explains how to integrate the long-term memory system with your existing Discord bot.

## Overview

The memory system provides your bot with the ability to:
- **Automatically store** important conversations and facts
- **Intelligently categorize** memories by type and importance
- **Retrieve relevant context** for future conversations
- **Search through** stored memories
- **Manage memory lifecycle** with automatic cleanup

## Files Created

1. **`memory_system.py`** - Core memory management classes
2. **`memory_integration.py`** - Bot integration and Discord commands
3. **`memory_requirements.txt`** - Optional dependencies
4. **`MEMORY_INTEGRATION_GUIDE.md`** - This guide

## Integration Steps

### Step 1: Add Memory System to Your Bot

Add these imports to your `bot.py`:

```python
from memory_integration import BotMemoryIntegration, MemoryCommands
```

### Step 2: Initialize Memory System

Add this after your existing client initialization:

```python
# Initialize memory system
memory_integration = BotMemoryIntegration(GEMINI_CLIENT)
memory_commands = MemoryCommands(memory_integration)
```

### Step 3: Integrate Memory Storage

Modify your `process_ask_request` function to store memories after successful responses:

```python
async def process_ask_request(request: QueuedRequest) -> None:
    try:
        # ... existing code ...
        
        if response:
            # ... existing response handling ...
            
            # Store in memory if response was successful
            memory_id = await memory_integration.process_question_answer(
                user_id=request.user_id,
                channel_id=request.interaction.channel.id,
                guild_id=request.interaction.guild.id if request.interaction.guild else None,
                question=request.question,
                answer=response,
                context={
                    "server": request.interaction.guild.name if request.interaction.guild else None,
                    "channel": request.interaction.channel.name if request.interaction.channel else None,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
            
            if memory_id:
                print(f"💾 Memory stored with ID: {memory_id}")
            
            # ... rest of existing code ...
```

### Step 4: Add Memory Context to AI Prompts

Modify your context building to include relevant memories:

```python
# In your ask_command, after building the main context
memory_context = memory_integration.get_memory_context(
    user_id=interaction.user.id,
    guild_id=interaction.guild.id if interaction.guild else None,
    question=processed_question
)

# Add memory context to your existing context_string
if memory_context:
    context_string += memory_context
```

### Step 5: Add Memory Commands

Add these slash commands to your bot:

```python
@tree.command(name="memorystats", description="Show your memory statistics.", guild=None)
async def memory_stats_command(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    await memory_commands.memory_stats_command(interaction, user)

@tree.command(name="searchmemories", description="Search through your stored memories.", guild=None)
async def search_memories_command(interaction: discord.Interaction, query: str):
    await memory_commands.search_memories_command(interaction, query)

@tree.command(name="forgetme", description="Delete all your stored memories.", guild=None)
async def forget_me_command(interaction: discord.Interaction):
    await memory_commands.forget_me_command(interaction)

@tree.command(name="memoryhelp", description="Show help for memory commands.", guild=None)
async def memory_help_command(interaction: discord.Interaction):
    await memory_commands.memory_help_command(interaction)
```

### Step 6: Add Memory Cleanup

Add periodic memory cleanup to your bot:

```python
async def periodic_memory_cleanup():
    """Clean up old memories every 24 hours."""
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)  # 24 hours
            deleted_count = memory_integration.cleanup_old_memories()
            if deleted_count > 0:
                print(f"🧹 Cleaned up {deleted_count} old memories")
        except Exception as e:
            print(f"Error during memory cleanup: {e}")

# Add this to your on_ready event
@client.event
async def on_ready():
    # ... existing code ...
    
    # Start memory cleanup task
    asyncio.create_task(periodic_memory_cleanup())
```

## Configuration Options

### Memory Storage Settings

You can customize these in `memory_integration.py`:

```python
# Memory storage settings
self.auto_store_memories = True  # Enable/disable automatic storage
self.min_importance_threshold = 0.3  # Minimum importance to store (0.0-1.0)
self.max_memories_per_user = 100  # Maximum memories per user
self.max_memories_per_guild = 500  # Maximum memories per guild
```

### Database Settings

The memory system uses SQLite by default. You can change the database path:

```python
self.memory_manager = MemoryManager(db_path="custom_memory.db")
```

## Memory Types

The system automatically categorizes memories into:

- **Facts** - General knowledge and information
- **Preferences** - User likes, dislikes, and choices  
- **User Info** - Personal details about users
- **Conversations** - Important chat exchanges
- **Server Info** - Information about Discord servers

## AI-Powered Features

### Importance Scoring

The system uses your existing Gemini AI to:
- Analyze question importance (0.0-1.0 scale)
- Extract relevant tags for categorization
- Determine memory types

### Smart Filtering

Memories are automatically filtered to avoid storing:
- Greetings and casual conversation
- Very short or very long exchanges
- Bot commands and responses
- Low-importance content

## Privacy and Security

- **User Isolation**: Each user can only see their own memories
- **Guild Context**: Memories can be scoped to specific Discord servers
- **Data Control**: Users can delete their memories with `/forgetme`
- **Automatic Cleanup**: Old, low-importance memories are automatically removed

## Performance Considerations

### Database Optimization

The system includes database indexes for:
- User ID lookups
- Guild ID filtering
- Memory type categorization
- Importance score sorting
- Last accessed timestamps

### Memory Limits

- **Per User**: 100 memories (configurable)
- **Per Guild**: 500 memories (configurable)
- **Global**: 1000 memories before cleanup

### Cleanup Schedule

- **Automatic**: Every 24 hours
- **Criteria**: Memories older than 30 days with importance < 0.3
- **Manual**: Available through bot owner commands

## Advanced Features

### Vector Embeddings (Optional)

For enhanced semantic search, you can add:

```bash
pip install sentence-transformers numpy torch
```

Then modify the search function to use semantic similarity instead of keyword matching.

### Memory Analytics

The system provides statistics on:
- Total memories per user
- Memory type distribution
- Average importance scores
- Memory age ranges

## Troubleshooting

### Common Issues

1. **Database Permissions**: Ensure the bot has write access to create `bot_memory.db`
2. **Memory Not Storing**: Check importance threshold and filtering rules
3. **Performance Issues**: Monitor database size and cleanup frequency

### Debug Commands

Add these owner-only commands for debugging:

```python
@tree.command(name="debugmemories", description="[Owner] Debug memory system", guild=None)
async def debug_memories_command(interaction: discord.Interaction):
    if interaction.user.id != int(os.getenv("OWNER_ID", "0")):
        await interaction.response.send_message("❌ Owner only command", ephemeral=True)
        return
    
    # Get system stats
    total_memories = len(memory_integration.memory_manager.retrieve_memories(limit=10000))
    db_size = os.path.getsize("bot_memory.db") if os.path.exists("bot_memory.db") else 0
    
    debug_info = f"🔍 **Memory System Debug Info**\n\n"
    debug_info += f"**Total Memories:** {total_memories}\n"
    debug_info += f"**Database Size:** {db_size / 1024:.1f} KB\n"
    debug_info += f"**Auto Storage:** {memory_integration.auto_store_memories}\n"
    debug_info += f"**Importance Threshold:** {memory_integration.min_importance_threshold}\n"
    
    await interaction.response.send_message(debug_info, ephemeral=True)
```

## Future Enhancements

### Planned Features

1. **Memory Sharing**: Allow users to share memories with others
2. **Memory Export**: Export memories to JSON/CSV
3. **Advanced Search**: Full-text search with filters
4. **Memory Clustering**: Group related memories together
5. **Cross-Server Memory**: Share memories across Discord servers

### Integration Ideas

1. **User Profiles**: Build user profiles from stored memories
2. **Conversation History**: Track conversation patterns over time
3. **Server Analytics**: Understand server activity and preferences
4. **Personalized Responses**: Use memory context for more personalized AI responses

## Support

If you encounter issues:

1. Check the console logs for error messages
2. Verify database permissions and disk space
3. Test with a simple memory command
4. Check that all imports are working correctly

The memory system is designed to be robust and handle errors gracefully, so your bot will continue working even if memory operations fail.
