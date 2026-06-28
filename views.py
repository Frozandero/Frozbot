"""Discord UI views for Frozbot."""

import logging

import discord

from database import count_memories_by_user, get_memories_by_user

logger = logging.getLogger(__name__)


class MemoryPaginationView(discord.ui.View):
    """Paginated view for displaying memories."""

    def __init__(
        self,
        username: str,
        channel_id: int,
        page: int = 0,
        page_size: int = 10,
        user_id: int | None = None,
        display_name: str | None = None,
    ):
        super().__init__(timeout=300)  # 5 minute timeout
        self.username = username
        self.user_id = user_id
        self.display_name = display_name
        self.page = page
        self.page_size = page_size
        self.channel_id = channel_id
        self.total_memories = count_memories_by_user(
            username, channel_id, user_id=user_id
        )
        self.total_pages = max(1, (self.total_memories + page_size - 1) // page_size)

        # Update button states
        self.update_buttons()

    def update_buttons(self):
        """Update button states based on current page."""
        # Clear existing buttons
        self.clear_items()

        # Add Previous button
        prev_button = discord.ui.Button(
            label="◀ Previous",
            style=discord.ButtonStyle.secondary,
            custom_id=f"memory_prev_{self.username}_{self.page}",
            disabled=(self.page <= 0),
        )
        prev_button.callback = self.previous_page
        self.add_item(prev_button)

        # Add page info button (non-functional, just shows page info)
        page_info = discord.ui.Button(
            label=f"Page {self.page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True,
        )
        self.add_item(page_info)

        # Add Next button
        next_button = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.secondary,
            custom_id=f"memory_next_{self.username}_{self.page}",
            disabled=(self.page >= self.total_pages - 1),
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

    def get_current_memories(self) -> list[tuple[int, str, str]]:
        """Get memories for the current page."""
        offset = self.page * self.page_size
        return get_memories_by_user(
            self.username,
            self.channel_id,
            self.page_size,
            offset,
            user_id=self.user_id,
        )

    def format_memories_message(self) -> str:
        """Format memories into a displayable message."""
        memories = self.get_current_memories()
        label = self.display_name or self.username
        if not memories:
            return f"No memories found for {label}."

        # Limit memory length for display to prevent overly long messages
        formatted_memories = []
        for memory in memories:
            memory_num = memory[0]
            # Truncate very long memories for readability
            display_memory = (
                memory[2] if len(memory[2]) <= 200 else memory[2][:197] + "..."
            )
            formatted_memories.append(f"{memory_num}. {memory[1]}: {display_memory}")

        memory_text = "\n".join(formatted_memories)

        return f"**Memories for {label}** ({self.total_memories} total):\n\n{memory_text}"

    async def previous_page(self, interaction: discord.Interaction):
        """Handle previous page button click."""
        try:
            if self.page > 0:
                self.page -= 1
                self.update_buttons()
                await interaction.response.edit_message(
                    content=self.format_memories_message(), view=self
                )
            else:
                await interaction.response.defer()
        except Exception as e:
            logger.exception(
                "memory_previous_page_error",
                extra={"error_type": type(e).__name__},
            )
            await interaction.response.defer()

    async def next_page(self, interaction: discord.Interaction):
        """Handle next page button click."""
        try:
            if self.page < self.total_pages - 1:
                self.page += 1
                self.update_buttons()
                await interaction.response.edit_message(
                    content=self.format_memories_message(), view=self
                )
            else:
                await interaction.response.defer()
        except Exception as e:
            logger.exception(
                "memory_next_page_error",
                extra={"error_type": type(e).__name__},
            )
            await interaction.response.defer()

    async def on_timeout(self):
        """Handle view timeout - disable all buttons."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
