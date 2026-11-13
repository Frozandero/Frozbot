"""Lazy-loaded Mistral SDK tools with request-local callback state."""

from contextvars import ContextVar
from typing import Awaitable, Callable, Optional

from mistralai import agents

# Set for a single SDK session, inherited by its tasks, and reset in finally.
search_callback: ContextVar[Optional[Callable[[str], Awaitable[str]]]] = ContextVar(
    "mistral_search_callback", default=None
)


@agents.tool(model_access="direct")
async def web_search(query: str) -> str:
    """Search the web for current facts. Use a focused query without private Discord context."""
    callback = search_callback.get()
    if callback is None:
        return "Search unavailable. Say you cannot verify current information."
    return await callback(query)


usage_callback: ContextVar[Optional[Callable[[object], None]]] = ContextVar(
    "mistral_usage_callback", default=None
)


class UsageHook(agents.Hook):
    async def post_llm_call(self, ctx, invocation):
        callback = usage_callback.get()
        if callback is not None:
            callback(invocation)
