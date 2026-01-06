"""Imagine (image generation) command for Frozbot."""

import asyncio
import datetime
import io
import re
from typing import Optional

import discord
from discord import app_commands
from PIL import Image

import config
from database import is_banned
from emoji import replace_guild_emojis_in_text
from llm import generate_image_with_llm, get_llm_provider
from utils import filter_profanity, cleanup_imagine_expired_cooldowns


def setup_imagine_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup imagine-related commands."""

    @tree.command(
        name="imagine",
        description="Generate an image from a prompt using Gemini. Optionally include an image for reference.",
        guild=None,
    )
    async def imagine_command(
        interaction: discord.Interaction,
        prompt: str,
        image: Optional[discord.Attachment] = None,
    ) -> None:
        """Create an image from text using Gemini image generation."""
        if is_banned(interaction.user.id):
            await interaction.response.send_message(
                "You are banned from using the imagine command.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id

        # Log request
        try:
            image_info = " (with image input)" if image else ""
            print(
                f"[IMAGINE] /imagine request from user {user_id}{image_info}: {prompt[:60]}..."
            )
        except Exception:
            pass

        # Rate limiting
        if not config.is_owner(user_id):
            now = datetime.datetime.now()
            if user_id in config.IMAGINE_COMMAND_COOLDOWNS:
                last_used = config.IMAGINE_COMMAND_COOLDOWNS[user_id]
                minutes_passed = (now - last_used).total_seconds() / 60
                if minutes_passed < config.IMAGINE_COMMAND_COOLDOWN_MINUTES:
                    remaining = int(
                        config.IMAGINE_COMMAND_COOLDOWN_MINUTES - minutes_passed
                    )
                    print(
                        f"[RATELIMIT] /imagine rate-limited for user {user_id}. Remaining: {remaining} min"
                    )
                    try:
                        await interaction.response.send_message(
                            f"⏰ Rate limit: You can only generate images once every {config.IMAGINE_COMMAND_COOLDOWN_MINUTES} minutes. Please wait {remaining} more minutes.",
                            ephemeral=True,
                        )
                    except discord.errors.NotFound:
                        pass
                    return

            if len(config.IMAGINE_COMMAND_COOLDOWNS) > 100:
                cleanup_imagine_expired_cooldowns()

        # Global toggle
        if not config.IMAGINE_ENABLE and not config.is_owner(user_id):
            try:
                await interaction.response.send_message(
                    "🛑 Image generation is currently disabled.", ephemeral=True
                )
            except discord.errors.NotFound:
                pass
            return

        # Check LLM provider (image generation requires provider support)
        provider = get_llm_provider()
        if not provider:
            print("[ERROR] /imagine attempted but LLM provider is not configured")
            try:
                await interaction.response.send_message(
                    "The bot is not configured with an LLM provider. Please contact the server owner.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                return
            return

        # Defer
        try:
            await interaction.response.defer(thinking=True)
        except discord.errors.NotFound:
            return

        # Process image input
        image_parts = []
        try:
            if image and getattr(image, "content_type", "").startswith("image/"):
                image_bytes = await image.read()
                pil_img = Image.open(io.BytesIO(image_bytes))
                if pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")
                image_parts.append(pil_img)
                print(
                    f"[IMAGE] Image input detected: {image.content_type}, size: {len(image_bytes)} bytes"
                )
        except Exception as e:
            print(f"Failed to process image attachment: {e}")

        # Extract mentioned users
        mention_pattern = r"<@!?(\d+)>"
        matches = re.findall(mention_pattern, prompt)
        processed_prompt = prompt

        for user_id_str in matches:
            try:
                mentioned_user_id = int(user_id_str)
                if interaction.guild:
                    member = interaction.guild.get_member(mentioned_user_id)
                    if member:
                        processed_prompt = processed_prompt.replace(
                            f"<@{mentioned_user_id}>", f"@{member.display_name}"
                        )
                        processed_prompt = processed_prompt.replace(
                            f"<@!{mentioned_user_id}>", f"@{member.display_name}"
                        )

                        # Add profile picture
                        if member.display_avatar:
                            print(
                                f"Adding profile picture for user {mentioned_user_id}"
                            )
                            avatar_bytes = await member.display_avatar.read()
                            avatar_img = Image.open(io.BytesIO(avatar_bytes))
                            if avatar_img.mode != "RGB":
                                avatar_img = avatar_img.convert("RGB")
                            image_parts.append(avatar_img)
            except Exception as e:
                print(f"Error processing user mention {user_id_str}: {e}")

        # Prepare content
        if image_parts:
            formatted_prompt = f"Do not use user ids; use display names. Based on the provided image(s), {processed_prompt}"
            prompt_for_llm = formatted_prompt
            print(f"[IMAGE] Using image-to-image generation")
        else:
            formatted_prompt = (
                f"Generate an image from the following prompt: {processed_prompt}"
            )
            prompt_for_llm = formatted_prompt
            print(f"[IMAGE] Using text-to-image generation")

        try:
            description_text, image_bytes = await generate_image_with_llm(
                prompt_for_llm, image_parts if image_parts else None
            )

            filtered_prompt = filter_profanity(prompt)

            # Replace guild emojis in description
            display_text = (description_text or "").strip()
            if display_text:
                try:
                    guild = interaction.guild
                    if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                        display_text = await replace_guild_emojis_in_text(
                            display_text, guild
                        )
                except Exception as e:
                    print(
                        f"[WARN] Error during emoji replacement in imagine command: {e}"
                    )

            # Build message
            image_source_info = " (with image input)" if image_parts else ""
            header = f"**Prompt:** {filtered_prompt}{image_source_info}\n\n"
            if display_text:
                content = header + f"**Notes:** {display_text}"
            else:
                content = header + "Generating image..."

            if image_bytes is not None:
                image_buffer = io.BytesIO(image_bytes)
                files_to_send = [discord.File(image_buffer, filename="imagine.png")]

                # Include input image as reference
                if image_parts:
                    try:
                        input_img_buf = io.BytesIO()
                        image_parts[0].convert("RGB").save(input_img_buf, format="PNG")
                        input_img_buf.seek(0)
                        files_to_send.insert(
                            0,
                            discord.File(input_img_buf, filename="input_reference.png"),
                        )
                    except Exception as e:
                        print(f"[WARN] Failed to include input image as reference: {e}")

                if len(content) > 2000:
                    content = content[:1997] + "..."
                await interaction.followup.send(content=content, files=files_to_send)

                # Record cooldown
                if not config.is_owner(user_id):
                    config.IMAGINE_COMMAND_COOLDOWNS[user_id] = datetime.datetime.now()
                    print(f"[OK] /imagine success for user {user_id}; cooldown set")
                else:
                    print(
                        f"[OK] /imagine success for owner {user_id}; cooldown bypassed"
                    )
            else:
                msg = (
                    header
                    + "No image was returned by the model. Please try a different prompt."
                )
                if len(msg) > 2000:
                    msg = msg[:1997] + "..."
                await interaction.followup.send(content=msg)
                print(f"[WARN] /imagine returned no image for user {user_id}")

        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏰ Image generation timed out. Please try again later.", ephemeral=True
            )
            print(f"[TIMEOUT] /imagine timeout for user {user_id}: {prompt[:60]}...")
        except Exception as e:
            await interaction.followup.send(
                f"❌ Unexpected error during image generation: {str(e)[:180]}...",
                ephemeral=True,
            )
            print(
                f"[ERROR] /imagine unexpected error for user {user_id}: {str(e)[:200]}..."
            )
