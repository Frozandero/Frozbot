"""Admin commands for Frozbot (owner-only)."""

import asyncio
import os
from typing import Optional

import discord
from discord import app_commands

import config
from emoji import debug_guild_emoji_state, replace_guild_emojis_in_text
from database import is_banned, add_banned_user, remove_banned_user


def setup_admin_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup admin-related commands."""

    @tree.command(
        name="clearqueue",
        description="[Owner Only] Clear the request queue.",
        guild=None,
    )
    async def clear_queue_command(interaction: discord.Interaction) -> None:
        """Clear the request queue (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can clear the queue.",
                    ephemeral=True,
                )
                return

            queue_size = config.REQUEST_QUEUE.qsize()

            while not config.REQUEST_QUEUE.empty():
                try:
                    config.REQUEST_QUEUE.get_nowait()
                    config.REQUEST_QUEUE.task_done()
                except asyncio.QueueEmpty:
                    break

            await interaction.response.send_message(
                f"🗑️ **Queue Cleared**\n\n"
                f"✅ Successfully cleared {queue_size} requests from the queue.\n"
                f"The queue is now empty.",
                ephemeral=True,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error clearing queue**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="clearcache",
        description="[Owner Only] Clear the channel summary cache to reset LLM context.",
        guild=None,
    )
    async def clear_cache_command(interaction: discord.Interaction) -> None:
        """Clear the channel summary cache (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can clear the cache.",
                    ephemeral=True,
                )
                return

            cache_size = len(config.CHANNEL_SUMMARY_CACHE)
            config.CHANNEL_SUMMARY_CACHE.clear()

            await interaction.response.send_message(
                f"🗑️ **Cache Cleared**\n\n"
                f"✅ Successfully cleared channel summary cache.\n"
                f"Cleared {cache_size} cached channel summaries.\n"
                f"New summaries will be generated on next request.",
                ephemeral=True,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error clearing cache**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="sethistorylimit",
        description="[Owner Only] Set the number of recent messages to fetch per user.",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def set_history_limit_command(
        interaction: discord.Interaction, limit: Optional[int] = None
    ) -> None:
        """Set the message history limit (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can set the history limit.",
                    ephemeral=True,
                )
                return

            if limit is None:
                await interaction.response.send_message(
                    f"📊 **Current Message History Limit**\n\n"
                    f"**Value:** {config.MESSAGE_HISTORY_LIMIT} messages\n\n"
                    f"Use `/sethistorylimit <number>` to change this value.",
                    ephemeral=True,
                )
            else:
                if limit < 1 or limit > 50:
                    await interaction.response.send_message(
                        "❌ **Invalid Value**\n\n"
                        f"Please provide a value between 1 and 50.\n"
                        f"Current value: {config.MESSAGE_HISTORY_LIMIT}",
                        ephemeral=True,
                    )
                    return

                old_limit = config.MESSAGE_HISTORY_LIMIT
                config.MESSAGE_HISTORY_LIMIT = limit

                await interaction.response.send_message(
                    f"✅ **Message History Limit Updated**\n\n"
                    f"**Old Value:** {old_limit} messages\n"
                    f"**New Value:** {config.MESSAGE_HISTORY_LIMIT} messages\n\n"
                    f"This change will take effect immediately for new requests.",
                    ephemeral=True,
                )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error setting history limit**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="setsearchdepth",
        description="[Owner Only] Set how far back to search in channel history.",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def set_search_depth_command(
        interaction: discord.Interaction, depth: Optional[int] = None
    ) -> None:
        """Set the message history search depth (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can set the search depth.",
                    ephemeral=True,
                )
                return

            if depth is None:
                await interaction.response.send_message(
                    f"🔍 **Current Message History Search Depth**\n\n"
                    f"**Value:** {config.MESSAGE_HISTORY_SEARCH_DEPTH} messages\n\n"
                    f"Use `/setsearchdepth <number>` to change this value.",
                    ephemeral=True,
                )
            else:
                if depth < 100 or depth > 10000:
                    await interaction.response.send_message(
                        "❌ **Invalid Value**\n\n"
                        f"Please provide a value between 100 and 10,000.\n"
                        f"Current value: {config.MESSAGE_HISTORY_SEARCH_DEPTH}",
                        ephemeral=True,
                    )
                    return

                old_depth = config.MESSAGE_HISTORY_SEARCH_DEPTH
                config.MESSAGE_HISTORY_SEARCH_DEPTH = depth

                await interaction.response.send_message(
                    f"✅ **Message History Search Depth Updated**\n\n"
                    f"**Old Value:** {old_depth} messages\n"
                    f"**New Value:** {config.MESSAGE_HISTORY_SEARCH_DEPTH} messages\n\n"
                    f"This change will take effect immediately for new requests.",
                    ephemeral=True,
                )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error setting search depth**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="config",
        description="[Owner Only] View current bot configuration.",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def config_command(interaction: discord.Interaction) -> None:
        """View current bot configuration (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can view the configuration.",
                    ephemeral=True,
                )
                return

            config_info = f"⚙️ **Bot Configuration**\n\n"
            config_info += (
                f"**Message History Limit:** {config.MESSAGE_HISTORY_LIMIT} messages\n"
            )
            config_info += f"**Message History Search Depth:** {config.MESSAGE_HISTORY_SEARCH_DEPTH} messages\n"
            config_info += f"**Ask Command Cooldown:** {config.ASK_COMMAND_COOLDOWN_MINUTES} minutes\n"
            config_info += f"**Imagine Command Cooldown:** {config.IMAGINE_COMMAND_COOLDOWN_MINUTES} minutes\n"
            config_info += (
                f"**Max Stored Questions:** {config.MAX_STORED_QUESTIONS} questions\n\n"
            )
            config_info += "**LLM Provider:**\n"
            config_info += f"• Selected: {config.LLM_PROVIDER}\n\n"
            config_info += "**Image Generation:**\n"
            config_info += f"• Enabled: {config.IMAGINE_ENABLE}\n\n"
            config_info += "**TTS:**\n"
            config_info += f"• Configured: {config.is_tts_configured()}\n\n"
            config_info += "**Command Visibility:**\n"
            config_info += "• Ask/imagine visibility is decided when slash commands are synced.\n"
            config_info += "• TTS command options are hidden when ElevenLabs is not configured.\n\n"
            config_info += "**Channel Context Settings:**\n"
            config_info += f"• Last raw messages: {config.CHANNEL_CONTEXT_LAST}\n"
            config_info += f"• Include bot messages (raw context): {config.CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES}\n"
            config_info += f"• Summary enabled: {config.CHANNEL_SUMMARY_ENABLE}\n"
            config_info += f"• Summary depth: {config.CHANNEL_SUMMARY_DEPTH}\n"
            config_info += f"• Summary TTL: {config.CHANNEL_SUMMARY_TTL_MIN} min\n\n"
            config_info += "**Commands to modify:**\n"
            config_info += (
                "• `/sethistorylimit <number>` - Set message history limit (1-50)\n"
            )
            config_info += (
                "• `/setsearchdepth <number>` - Set search depth (100-10000)\n"
            )
            config_info += (
                "• `/setimagineenabled <true|false>` - Toggle image generation\n"
            )
            config_info += "• `/setcontextincludebots <true|false>` - Include bot messages in raw context\n"
            config_info += "• `/debugemojis` - Debug emoji replacement issues\n"
            config_info += "• `/config` - View current configuration"

            await interaction.response.send_message(config_info, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error viewing configuration**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="debugemojis",
        description="[Owner Only] Debug emoji replacement issues in the current guild.",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def debug_emojis_command(interaction: discord.Interaction) -> None:
        """Debug emoji replacement issues (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can debug emoji issues.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            if not guild:
                await interaction.followup.send(
                    "❌ **No Guild Context**\n\nThis command must be used in a server.",
                    ephemeral=True,
                )
                return

            debug_info = await debug_guild_emoji_state(guild)

            test_text = "Testing emoji replacement: :test: :smile: :cool:"
            print(f"[TEST] Testing emoji replacement with: {test_text}")

            replaced_text = await replace_guild_emojis_in_text(test_text, guild)

            test_result = f"🧪 **Emoji Replacement Test**\n\n"
            test_result += f"**Test Text:** {test_text}\n"
            test_result += f"**Result:** {replaced_text}\n\n"

            full_debug = debug_info + "\n\n" + test_result

            if len(full_debug) > 2000:
                await interaction.followup.send(
                    content=debug_info[:1997] + "...", ephemeral=True
                )
                await interaction.followup.send(content=test_result, ephemeral=True)
            else:
                await interaction.followup.send(content=full_debug, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"❌ **Error debugging emojis**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="togglellmban",
        description="[Owner Only] Ban a user from using the LLM",
        guild=None,
    )
    async def ban_llm_command(
        interaction: discord.Interaction, user: discord.Member
    ) -> None:
        """Ban a user from using the LLM (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can ban users from the LLM.",
                    ephemeral=True,
                )
                return

            if is_banned(user.id):
                remove_banned_user(user.id)
                await interaction.response.send_message(
                    f"✅ **User Unbanned**\n\n{user.mention} has been unbanned from using the LLM.",
                    ephemeral=True,
                )
                return

            add_banned_user(user.id)
            await interaction.response.send_message(
                f"✅ **User Banned**\n\n{user.mention} has been banned from using the LLM.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error banning user**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="setask",
        description="[Owner Only] Enable/disable ask command (true/false or omit to view)",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def set_ask_command_command(
        interaction: discord.Interaction, enabled: Optional[bool] = None
    ) -> None:
        """View or update the ask command (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can change this setting.",
                    ephemeral=True,
                )
                return

            if enabled is None:
                await interaction.response.send_message(
                    f"💬 **Ask Command**\n\nCurrent: {config.ASK_ENABLE}",
                    ephemeral=True,
                )
                return

            old_value = config.ASK_ENABLE
            config.ASK_ENABLE = bool(enabled)
            await interaction.response.send_message(
                f"✅ **Ask Command Updated**\n\nOld: {old_value}\nNew: {config.ASK_ENABLE}\n\nRun `/refresh` to resync command visibility.",
                ephemeral=True,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error updating setting**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="setimagineenabled",
        description="[Owner Only] Enable or disable image generation (true/false or omit to view)",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def set_imagine_enabled_command(
        interaction: discord.Interaction, enabled: Optional[bool] = None
    ) -> None:
        """View or update the global image generation toggle (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can change this setting.",
                    ephemeral=True,
                )
                return

            if enabled is None:
                await interaction.response.send_message(
                    f"🖼️ **Image Generation Toggle**\n\nCurrent: {config.IMAGINE_ENABLE}",
                    ephemeral=True,
                )
                return

            old_value = config.IMAGINE_ENABLE
            config.IMAGINE_ENABLE = bool(enabled)
            await interaction.response.send_message(
                f"✅ **Image Generation Updated**\n\nOld: {old_value}\nNew: {config.IMAGINE_ENABLE}\n\nRun `/refresh` to resync command visibility.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error updating setting**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="setcontextincludebots",
        description="[Owner Only] Include or exclude bot messages in raw channel context (true/false or omit to view)",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def set_context_include_bots_command(
        interaction: discord.Interaction, include: Optional[bool] = None
    ) -> None:
        """View or update inclusion of bot messages in the raw channel context (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can change this setting.",
                    ephemeral=True,
                )
                return

            if include is None:
                await interaction.response.send_message(
                    f"💬 **Include Bot Messages in Raw Context**\n\nCurrent: {config.CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES}",
                    ephemeral=True,
                )
                return

            old_value = config.CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES
            config.CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES = bool(include)
            await interaction.response.send_message(
                f"✅ **Raw Context Inclusion Updated**\n\nOld: {old_value}\nNew: {config.CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error updating setting**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

    @tree.command(
        name="refresh",
        description="[Dev Only] Refresh slash commands on the server.",
        guild=config.IS_DEV_SERVER_COMMAND,
    )
    async def refresh_commands(interaction: discord.Interaction) -> None:
        """Refresh slash commands (owner only)."""
        if not config.is_owner(interaction.user.id):
            try:
                await interaction.response.send_message(
                    "You don't have permission to use this command.", ephemeral=True
                )
            except discord.errors.NotFound:
                print(
                    "Interaction not found when sending permission error for refresh command"
                )
                return
            return

        try:
            await interaction.response.defer(ephemeral=True)
            from commands import rebuild_all_commands

            rebuild_all_commands(tree, client)

            if config.GUILD_ID_ENV:
                test_guild = discord.Object(id=int(config.GUILD_ID_ENV))
                await tree.sync(guild=test_guild)
                try:
                    await interaction.followup.send(
                        f"Commands cleared and refreshed on guild {config.GUILD_ID_ENV}!",
                        ephemeral=True,
                    )
                except discord.errors.NotFound:
                    print(
                        "Interaction not found when sending guild refresh success message"
                    )
                    return
            else:
                tree.clear_commands(guild=None)
                await tree.sync()
                try:
                    await interaction.followup.send(
                        "Commands cleared and refreshed globally! (May take up to 1 hour)",
                        ephemeral=True,
                    )
                except discord.errors.NotFound:
                    print(
                        "Interaction not found when sending global refresh success message"
                    )
                    return
        except discord.errors.NotFound:
            print("Interaction not found when deferring refresh command")
            return

        except Exception as e:
            try:
                await interaction.followup.send(
                    f"Failed to refresh commands: {e}", ephemeral=True
                )
            except discord.errors.NotFound:
                print("Interaction not found when sending refresh error message")
                return
