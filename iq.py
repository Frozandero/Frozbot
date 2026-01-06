"""IQ calculation functions for Frozbot."""

import hashlib
import random

import discord

MEAN_IQ: float = 100.0
STDDEV_IQ: float = 15.0


def build_user_seed_material(user: discord.abc.User) -> str:
    """Build a string of persistent user attributes to feed into a hash.

    Using stable identifiers ensures the generated IQ is deterministic for a given user.
    """
    user_id_str: str = str(user.id)
    created_at_iso: str = (
        user.created_at.isoformat() if getattr(user, "created_at", None) else ""  # type: ignore
    )
    username: str = getattr(user, "name", "")
    discriminator: str = getattr(
        user, "discriminator", ""
    )  # legacy, may be empty on new usernames

    seed_components = [user_id_str, created_at_iso, username, discriminator]
    return "|".join(seed_components)


def compute_seed_from_user(user: discord.abc.User) -> int:
    """Hash stable user info into a large integer seed."""
    seed_material: str = build_user_seed_material(user)
    digest_bytes: bytes = hashlib.sha256(seed_material.encode("utf-8")).digest()
    return int.from_bytes(digest_bytes, byteorder="big", signed=False)


def compute_deterministic_iq(
    user: discord.abc.User, mean: float = MEAN_IQ, stddev: float = STDDEV_IQ
) -> int:
    """Find out the IQ of a user."""
    seed_value: int = compute_seed_from_user(user)
    rng = random.Random(seed_value)
    iq_value: float = rng.normalvariate(mean, stddev)
    return max(0, int(round(iq_value)))
