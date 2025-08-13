# Example Integration with Your Existing Bot
# This shows the minimal changes needed to add memory to your bot

# Add these imports to your bot.py
from memory_integration import BotMemoryIntegration, MemoryCommands

# Add this after your existing client initialization (around line 1000)
# Initialize memory system
memory_integration = BotMemoryIntegration(GEMINI_CLIENT)
memory_commands = MemoryCommands(memory_integration)

# Modify your process_ask_request function (around line 250)
async def process_ask_request(request: QueuedRequest) -> None:
    try:
        print(f"🤖 Processing ask request: {request.question[:50]}...")

        # Try to get response from Gemini with model fallback
        response = await asyncio.wait_for(
            try_gemini_models(request.question, request.context_string),
            timeout=60.0,
        )

        if response:
            # Update cooldown only on successful response
            owner_id = int(os.getenv("OWNER_ID", "0"))
            if request.user_id != owner_id:  # Only apply cooldown to non-owners
                ASK_COMMAND_COOLDOWNS[request.user_id] = datetime.datetime.now()

            # STORE IN MEMORY - Add this section
            try:
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
            except Exception as e:
                print(f"⚠️ Memory storage failed: {e}")
                # Don't let memory errors break the main functionality

            # Format the response (existing code)
            filtered_question = filter_profanity(request.question)
            formatted_response = (
                f"**Question:** {filtered_question}\n\n**Answer:** {response}"
            )

            # ... rest of your existing response handling code ...

# Modify your ask_command function (around line 1000)
# Add memory context to your existing context building
async def ask_command(interaction: discord.Interaction, question: str) -> None:
    # ... existing code for gathering context ...
    
    # Add this after building your main context_string
    memory_context = memory_integration.get_memory_context(
        user_id=interaction.user.id,
        guild_id=interaction.guild.id if interaction.guild else None,
        question=processed_question
    )
    
    # Add memory context to your existing context_string
    if memory_context:
        context_string += memory_context
    
    # ... rest of your existing code ...

# Add these new slash commands (around line 1500)
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

# Add memory cleanup to your on_ready event (around line 1700)
@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Bot is ready! Starting command sync...")

    try:
        if GUILD_ID_ENV:
            print(f"GUILD_ID_ENV is set to: {GUILD_ID_ENV}")
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            print(f"Created guild object: {test_guild}")

            print("Syncing guild commands only...")
            await tree.sync(guild=test_guild)
            print(f"Slash commands synced to guild {GUILD_ID_ENV}.")
        else:
            print("No GUILD_ID_ENV set, syncing globally only...")
            await tree.sync()
            print("Slash commands synced globally (may take up to 1 hour to appear).")
    except Exception as sync_error:
        print(f"Failed to sync commands: {sync_error}")
        print(f"Error type: {type(sync_error)}")
        import traceback
        traceback.print_exc()
        print("Make sure your bot has the 'applications.commands' scope and proper permissions.")

    # ADD THIS: Start memory cleanup task
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
    
    asyncio.create_task(periodic_memory_cleanup())
    print("🧠 Memory system initialized and cleanup task started")

# Optional: Add debug command for memory system
@tree.command(name="debugmemories", description="[Owner] Debug memory system", guild=None)
async def debug_memories_command(interaction: discord.Interaction):
    if interaction.user.id != int(os.getenv("OWNER_ID", "0")):
        await interaction.response.send_message("❌ Owner only command", ephemeral=True)
        return
    
    try:
        # Get system stats
        total_memories = len(memory_integration.memory_manager.retrieve_memories(limit=10000))
        db_size = os.path.getsize("bot_memory.db") if os.path.exists("bot_memory.db") else 0
        
        debug_info = f"🔍 **Memory System Debug Info**\n\n"
        debug_info += f"**Total Memories:** {total_memories}\n"
        debug_info += f"**Database Size:** {db_size / 1024:.1f} KB\n"
        debug_info += f"**Auto Storage:** {memory_integration.auto_store_memories}\n"
        debug_info += f"**Importance Threshold:** {memory_integration.min_importance_threshold}\n"
        
        await interaction.response.send_message(debug_info, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error getting debug info: {str(e)[:200]}...", 
            ephemeral=True
        )
