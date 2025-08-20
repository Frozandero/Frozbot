import os
from mcrcon import MCRcon

MC_HOST = None
MC_PORT = None
MC_PASSWORD = None

MC_INIT = False

HAS_MC_VARS = False


def init_mc():
    global MC_HOST, MC_PORT, MC_PASSWORD, MC_INIT, HAS_MC_VARS
    if MC_INIT:
        return

    MC_HOST = os.getenv("MC_HOST")
    MC_PORT = int(os.getenv("MC_PORT") or 25575)
    MC_PASSWORD = os.getenv("MC_PASSWORD")

    if MC_HOST and MC_PASSWORD:
        HAS_MC_VARS = True


def whitelist_player(player_name: str):
    init_mc()
    if not HAS_MC_VARS:
        return "MC_HOST, MC_PORT, MC_PASSWORD are not set"

    with MCRcon(MC_HOST, MC_PORT, MC_PASSWORD) as mcr:  # type: ignore
        resp = mcr.command(f"whitelist add {player_name}")
        return resp


def unwhitelist_player(player_name: str):
    init_mc()
    if not HAS_MC_VARS:
        return "MC_HOST, MC_PORT, MC_PASSWORD are not set"

    with MCRcon(MC_HOST, MC_PORT, MC_PASSWORD) as mcr:  # type: ignore
        resp = mcr.command(f"whitelist remove {player_name}")
        return resp


def get_whitelist():
    init_mc()
    if not HAS_MC_VARS:
        return "MC_HOST, MC_PORT, MC_PASSWORD are not set"

    with MCRcon(MC_HOST, MC_PORT, MC_PASSWORD) as mcr:  # type: ignore
        resp = mcr.command("whitelist list")
        return resp
