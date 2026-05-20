import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import os

# =============================
# CONFIG
# =============================
TOKEN = os.environ.get("DISCORD_TOKEN")

ALLOWED_GUILD_ID = 1502306475903680746

OWNERS = {
    1235586743991009372,
    1393725545853882509,
}

WELCOME_CHANNEL_ID = 1502307923408326837
CALL_VOICE_CHANNEL_ID = 1502835093893550201
LOG_CHANNEL_ID = 1505550105959202959

# =============================
# INTENTS (RAILWAY SAFE)
# =============================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

ping_tracker = defaultdict(list)
action_tracker = defaultdict(list)
category_backup = {}

# =============================
# HELPERS
# =============================

def is_owner(user_id: int):
    return user_id in OWNERS


async def log(title: str, description: str, color: discord.Color = discord.Color.orange()):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="7Z SYSTEM")

    try:
        await channel.send(embed=embed)
    except Exception as e:
        print("LOG ERROR:", e)


def safe_log(title, description, color=discord.Color.orange()):
    asyncio.create_task(log(title, description, color))


async def get_latest_audit(guild, action):
    try:
        async for entry in guild.audit_logs(limit=1, action=action):
            return entry
    except Exception as e:
        print("AUDIT ERROR:", e)
    return None

# =============================
# READY
# =============================
@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")

    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
        print("Slashcommands synced")
    except Exception as e:
        print("SYNC ERROR:", e)

    safe_log(
        "Bot Online",
        f"{bot.user} ist gestartet.",
        discord.Color.green()
    )

# =============================
# ON MESSAGE (ANTI PING)
# =============================
@bot.event
async def on_message(message):
    if not message.guild or message.guild.id != ALLOWED_GUILD_ID:
        return

    if message.author.bot:
        return

    if is_owner(message.author.id):
        await bot.process_commands(message)
        return

    if message.mention_everyone:
        now = datetime.utcnow()
        uid = message.author.id

        ping_tracker[uid].append(now)
        ping_tracker[uid] = [t for t in ping_tracker[uid] if now - t < timedelta(seconds=10)]

        if len(ping_tracker[uid]) >= 2:
            try:
                await message.delete()
                await message.guild.ban(message.author, reason="Mass Ping")
                safe_log(
                    "Mass Ping Ban",
                    f"{message.author} wurde gebannt.",
                    discord.Color.red()
                )
            except Exception as e:
                print("PING BAN ERROR:", e)

            ping_tracker[uid].clear()

    await bot.process_commands(message)

# =============================
# BOT ADD PROTECTION
# =============================
@bot.event
async def on_member_join(member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    if not member.bot:
        return

    await asyncio.sleep(0.5)

    entry = await get_latest_audit(member.guild, discord.AuditLogAction.bot_add)
    if not entry:
        return

    inviter = entry.user

    if not inviter:
        return

    if inviter.id in OWNERS or inviter.bot:
        return

    try:
        await member.guild.ban(member, reason="Unauthorized Bot")
        await member.guild.ban(inviter, reason="Bot Invite")

        safe_log(
            "Unauthorized Bot",
            f"Bot + Inviter gebannt: {inviter}",
            discord.Color.red()
        )
    except Exception as e:
        print("BOT ADD ERROR:", e)

# =============================
# CHANNEL DELETE PROTECTION
# =============================
@bot.event
async def on_guild_channel_delete(channel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.5)

    entry = await get_latest_audit(channel.guild, discord.AuditLogAction.channel_delete)
    if not entry:
        return

    user = entry.user

    if not user or user.id in OWNERS or user.bot:
        return

    try:
        await channel.guild.ban(user, reason="Channel Delete")
        safe_log(
            "Channel Delete",
            f"{user} wurde gebannt.",
            discord.Color.red()
        )
    except Exception as e:
        print("CHANNEL DELETE ERROR:", e)

    # Restore (simple safe version)
    try:
        if isinstance(channel, discord.TextChannel):
            await channel.guild.create_text_channel(name=channel.name)
        elif isinstance(channel, discord.VoiceChannel):
            await channel.guild.create_voice_channel(name=channel.name)
    except Exception as e:
        print("RESTORE ERROR:", e)

# =============================
# ROLE DELETE PROTECTION
# =============================
@bot.event
async def on_guild_role_delete(role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.5)

    entry = await get_latest_audit(role.guild, discord.AuditLogAction.role_delete)
    if not entry:
        return

    user = entry.user

    if not user or user.id in OWNERS or user.bot:
        return

    try:
        await role.guild.ban(user, reason="Role Delete")

        new_role = await role.guild.create_role(
            name=role.name,
            permissions=role.permissions,
            colour=role.colour,
            hoist=role.hoist,
            mentionable=role.mentionable
        )

        safe_log(
            "Role Deleted",
            f"{user} gelöscht → Rolle restored",
            discord.Color.red()
        )
    except Exception as e:
        print("ROLE ERROR:", e)

# =============================
# KICK DETECTION
# =============================
@bot.event
async def on_member_remove(member):
    guild = member.guild

    if guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.5)

    entry = await get_latest_audit(guild, discord.AuditLogAction.kick)
    if not entry:
        return

    actor = entry.user

    if not actor or actor.id in OWNERS or actor.bot:
        return

    try:
        await guild.ban(actor, reason="Kick Abuse")
        safe_log(
            "Kick Ban",
            f"{actor} hat Kick benutzt",
            discord.Color.red()
        )
    except Exception as e:
        print("KICK ERROR:", e)

# =============================
# COMMANDS
# =============================
@bot.command()
async def call(ctx):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return

    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Kein Zugriff")

    channel = bot.get_channel(CALL_VOICE_CHANNEL_ID)

    if not isinstance(channel, discord.VoiceChannel):
        return await ctx.send("❌ Voice Channel fehlt")

    try:
        if ctx.voice_client:
            await ctx.voice_client.disconnect()

        await channel.connect()

        await ctx.send("✅ Connected")
    except Exception as e:
        print("CALL ERROR:", e)

# =============================
# START
# =============================
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        print("BOT CRASH:", e)
