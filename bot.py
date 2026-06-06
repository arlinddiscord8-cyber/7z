import sqlite3
import discord
from discord.ext import commands
from discord.ui import View, Button
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import os
import io
import math
import re

TOKEN = os.getenv("TOKEN")

# =============================
# CONFIG
# =============================

ALLOWED_GUILD_ID = 1512581389726388314

OWNERS = {
    1393725545853882509,
    1235586743991009372
}

CALL_VOICE_CHANNEL_ID   = 1512776116438306816
LOG_CHANNEL_ID           = 1512582270106468385
WELCOME_CHANNEL_ID       = 1512774925126078566
RULES_CHANNEL_ID         = 1512774929253273821
TICKET_PANEL_CHANNEL_ID  = 1512774944818462741
TICKET_CATEGORY_ID       = 1512774917479993515
SUPPORT_ROLE_ID          = 1512774845287497819
BOOST_CHANNEL_ID         = 1512774965030682665
AUTO_REACT_CHANNEL_IDS   = {1512774973607907369, 1512774955413147648}
COUNTING_CHANNEL_ID      = 1512774971712209097
AUTO_ROLE_ID             = 1512774841005244426
TRIGGER_ROLE_ID          = 1512774837708525658
EXTRA_ROLE_ID_1          = 1512774836806619239
EXTRA_ROLE_ID_2          = 1512775255070867456

VOICE_ALWAYS_ON = True
voice_client = None

# =============================
# BOT SETUP
# =============================

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
intents.reactions = True
intents.voice_states = True
intents.guild_messages = True

bot = commands.Bot(command_prefix=["!", "?"], intents=intents)

timeout_tracker      = defaultdict(list)
kick_tracker         = defaultdict(list)
ban_tracker          = defaultdict(list)
ticket_del_tracker   = defaultdict(list)

counting_state = {
    "current": 0,
    "last_user": None,
    "delete_notice": None,
}

first_react_announced = set()
ticket_counter = 0

# =============================
# INVITE CACHE (NEW SYSTEM)
# =============================

invite_cache = {}

# =============================
# HELPERS
# =============================

def is_owner(user_id: int):
    return user_id in OWNERS

def can_moderate(member):
    if member.id in OWNERS:
        return True
    for role in member.roles:
        if role.permissions.administrator or role.permissions.manage_messages:
            return True
    return False

def get_color(color: str):
    if color == "white":
        return discord.Color.from_rgb(255, 255, 255)
    return discord.Color.from_rgb(0, 0, 0)

async def security_log(guild, text):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(text)
        except Exception:
            pass

def eval_math_expression(expr: str):
    try:
        expr = expr.strip()
        allowed = set("0123456789+-*/(). ")
        if not all(c in allowed for c in expr):
            return None
        result = eval(expr, {"__builtins__": {}}, {})
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            if result == int(result):
                return int(result)
    except Exception:
        pass
    return None

# =============================
# READY
# =============================

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")

    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
    except Exception:
        pass

    asyncio.create_task(voice_keep_alive())

    # INVITE CACHE LOAD
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            invite_cache[guild.id] = {}

# =============================
# JOIN EVENT (NEW INVITE EMBED SYSTEM)
# =============================

@bot.event
async def on_member_join(member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    guild = member.guild
    inviter_name = "Unknown"
    invite_count = 0

    try:
        new_invites = await guild.invites()
        old_invites = invite_cache.get(guild.id, {})

        used_invite = None

        for inv in new_invites:
            if inv.uses > old_invites.get(inv.code, 0):
                used_invite = inv
                break

        invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used_invite and used_invite.inviter:
            inviter_name = used_invite.inviter.name
            invite_count = used_invite.uses

    except Exception:
        pass

    # Auto role
    role = guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except Exception:
            pass

    channel = guild.get_channel(WELCOME_CHANNEL_ID)

    if channel:
        embed = discord.Embed(
            title="New Member on EH / 7zarnova ᵛ²",
            description=(
                f"**{member.mention}** just joined.\n\n"
                f"They were invited by **{inviter_name}** who now has **{invite_count} invites** !"
            ),
            color=discord.Color.from_rgb(149, 165, 166)
        )

        # Avatar oben rechts
        embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed)
        except Exception:
            pass

# =============================
# REMOVED COMMANDS
# =============================

# ❌ /invite removed
# ❌ /leaderboard removed

# =============================
# REST OF YOUR BOT (UNCHANGED)
# =============================

# >>> HIER BLEIBT DEIN GANZER REST CODE (Tickets, Security, Counting usw.)

# =============================
# START
# =============================

bot.run(TOKEN)
