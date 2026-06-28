"""Imagine (image generation) command for Frozbot."""

import asyncio
import datetime
import io
import logging
import re
import uuid
from typing import Optional

import discord
from discord import app_commands

from attachments import (
    ImageValidationError,
    read_validated_attachment,
    validate_image_bytes,
)
import config
from database import is_banned
from emoji import replace_guild_emojis_in_text
from llm import (
    generate_image_with_llm,
    get_llm_provider,
    provider_supports_image_generation,
)
from utils import (
    cleanup_imagine_expired_cooldowns,
    filter_profanity,
    format_duration_seconds,
)

logger = logging.getLogger(__name__)


def setup_imagine_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup imagine-related commands."""

    @tree.command(
        name="imagine",
        description="Generate an image from a prompt. Optionally include an image for reference.",
        guild=None,
    )
    async def imagine_command(
        interaction: discord.Interaction,
        prompt: str,
        image: Optional[discord.Attachment] = None,
    ) -> None:
        """Create an image from text using the configured provider if supported."""
        if is_banned(interaction.user.id):
            await interaction.response.send_message(
                "You are banned from using the imagine command.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id
        request_id = str(uuid.uuid4())

        # Log request
        try:
            image_info = " (with image input)" if image else ""
            logger.info(
                "imagine_request_received",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "has_image": bool(image),
                    "image_info": image_info,
                    "prompt_chars": len(prompt),
                },
            )
        except Exception:
            pass

        # Rate limiting
        if not config.is_owner(user_id):
            now = datetime.datetime.now()
            if user_id in config.IMAGINE_COMMAND_COOLDOWNS:
                last_used = config.IMAGINE_COMMAND_COOLDOWNS[user_id]
                seconds_passed = (now - last_used).total_seconds()
                if seconds_passed < config.IMAGINE_COMMAND_COOLDOWN_SECONDS:
                    remaining = int(
                        config.IMAGINE_COMMAND_COOLDOWN_SECONDS - seconds_passed
                    )
                    logger.info(
                        "imagine_rate_limited",
                        extra={
                            "request_id": request_id,
                            "user_id": user_id,
                            "remaining_seconds": remaining,
                        },
                    )
                    try:
                        await interaction.response.send_message(
                            f"⏰ Rate limit: You can only generate images once every "
                            f"{format_duration_seconds(config.IMAGINE_COMMAND_COOLDOWN_SECONDS)}. "
                            f"Please wait {format_duration_seconds(remaining)}.",
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
            logger.error(
                "imagine_llm_provider_missing",
                extra={"request_id": request_id, "user_id": user_id},
            )
            try:
                await interaction.response.send_message(
                    "The bot is not configured with an LLM provider. Please contact the server owner.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                return
            return

        if not provider_supports_image_generation():
            provider_name = getattr(
                provider, "provider_name", provider.__class__.__name__
            )
            logger.error(
                "imagine_provider_unsupported",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "provider": provider_name,
                },
            )
            try:
                await interaction.response.send_message(
                    f"The configured LLM provider ({provider_name}) is not configured "
                    "for image generation.",
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
            if image:
                pil_img = await read_validated_attachment(
                    image,
                    source_name="imagine_attachment",
                    request_id=request_id,
                )
                image_parts.append(pil_img)
                logger.info(
                    "imagine_image_input_attached",
                    extra={
                        "request_id": request_id,
                        "user_id": user_id,
                        "content_type": getattr(image, "content_type", None),
                    },
                )
        except ImageValidationError as e:
            await interaction.followup.send(
                f"❌ **Invalid image attachment**\n\n{e}",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.exception(
                "imagine_image_attachment_error",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                },
            )
            await interaction.followup.send(
                "❌ **Invalid image attachment**\n\nThe image could not be processed.",
                ephemeral=True,
            )
            return

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
                            avatar_bytes = await member.display_avatar.read()
                            avatar_img = validate_image_bytes(
                                avatar_bytes,
                                source_name=f"avatar_{mentioned_user_id}",
                                request_id=request_id,
                            )
                            image_parts.append(avatar_img)
                            logger.info(
                                "imagine_mention_avatar_attached",
                                extra={
                                    "request_id": request_id,
                                    "mentioned_user_id": mentioned_user_id,
                                },
                            )
            except ImageValidationError as e:
                logger.warning(
                    "imagine_mention_avatar_invalid",
                    extra={
                        "request_id": request_id,
                        "mentioned_user_id": user_id_str,
                        "error_message": str(e),
                    },
                )
            except Exception as e:
                logger.exception(
                    "imagine_mention_processing_error",
                    extra={
                        "request_id": request_id,
                        "mentioned_user_id": user_id_str,
                        "error_type": type(e).__name__,
                    },
                )

        # Prepare content
        if image_parts:
            formatted_prompt = f"Do not use user ids; use display names. Based on the provided image(s), {processed_prompt}"
            prompt_for_llm = formatted_prompt
            logger.info(
                "imagine_using_image_to_image",
                extra={"request_id": request_id, "image_count": len(image_parts)},
            )
        else:
            formatted_prompt = (
                f"Generate an image from the following prompt: {processed_prompt}"
            )
            prompt_for_llm = formatted_prompt
            logger.info("imagine_using_text_to_image", extra={"request_id": request_id})

        try:
            description_text, image_bytes = await generate_image_with_llm(
                prompt_for_llm,
                image_parts if image_parts else None,
                request_id=request_id,
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
                    logger.exception(
                        "imagine_emoji_replacement_error",
                        extra={
                            "request_id": request_id,
                            "error_type": type(e).__name__,
                        },
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
                        logger.exception(
                            "imagine_reference_attachment_failed",
                            extra={
                                "request_id": request_id,
                                "error_type": type(e).__name__,
                            },
                        )

                if len(content) > 2000:
                    content = content[:1997] + "..."
                await interaction.followup.send(content=content, files=files_to_send)

                # Record cooldown
                if not config.is_owner(user_id):
                    config.IMAGINE_COMMAND_COOLDOWNS[user_id] = datetime.datetime.now()
                    logger.info(
                        "imagine_request_completed",
                        extra={
                            "request_id": request_id,
                            "user_id": user_id,
                            "cooldown_set": True,
                        },
                    )
                else:
                    logger.info(
                        "imagine_request_completed",
                        extra={
                            "request_id": request_id,
                            "user_id": user_id,
                            "cooldown_set": False,
                        },
                    )
            else:
                msg = (
                    header
                    + "No image was returned by the model. Please try a different prompt."
                )
                if len(msg) > 2000:
                    msg = msg[:1997] + "..."
                await interaction.followup.send(content=msg)
                logger.warning(
                    "imagine_request_no_image_returned",
                    extra={"request_id": request_id, "user_id": user_id},
                )

        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏰ Image generation timed out. Please try again later.", ephemeral=True
            )
            logger.warning(
                "imagine_request_timeout",
                extra={"request_id": request_id, "user_id": user_id},
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Unexpected error during image generation: {str(e)[:180]}...",
                ephemeral=True,
            )
            logger.exception(
                "imagine_request_unexpected_error",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                },
            )
