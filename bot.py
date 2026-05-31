import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import os

TOKEN = os.getenv("TOKEN")

# =============================
# CONFIG
# =============================

ALLOWED_GUILD_ID = 1510606068311527484

OWNERS = {
    1393725545853882509,
    1235586743991009372
}

WELCOME_CHANNEL_ID = 1510606440006422589
CALL_VOICE_CHANNEL_ID = 1510715789567590630

# =============================
# LOG CONFIG
# =============================

LOG_CHANNEL_ID = 1510606418888360101
USE_EMBEDS = True
LOG_THEME = "black"  # "black" oder "white"

# =============================
# VOICE KEEP ALIVE
# =============================

VOICE_ALWAYS_ON = True
voice_client = None

# =============================
# BOT SETUP
# =============================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

ping_tracker = defaultdict(list)
action_tracker = defaultdict(list)
category_backup = {}

# =============================
# HELPERS
# =============================

def is_owner(user_id: int):
    return user_id in OWNERS

async def get_latest_audit(guild, action):
    try:
        return await guild.audit_logs(limit=1, action=action).__anext__()
    except:
        return None

# =============================
# LOG SYSTEM
# =============================

def get_log_color():
    if LOG_THEME.lower() == "white":
        return discord.Color.from_rgb(255, 255, 255)
    return discord.Color.from_rgb(0, 0, 0)


async def send_log(guild, message: str):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    try:
        if USE_EMBEDS:
            embed = discord.Embed(
                description=message,
                color=get_log_color()
            )
            embed.timestamp = datetime.utcnow()
            await channel.send(embed=embed)
        else:
            await channel.send(message)
    except:
        pass

# =============================
# VOICE KEEP ALIVE LOOP
# =============================

async def voice_keep_alive():
    await bot.wait_until_ready()

    global voice_client

    while VOICE_ALWAYS_ON:
        try:
            channel = bot.get_channel(CALL_VOICE_CHANNEL_ID)

            if channel:
                if not bot.voice_clients:
                    try:
                        voice_client = await channel.connect()
                    except:
                        pass
                else:
                    vc = bot.voice_clients[0]
                    if not vc.is_connected():
                        try:
                            await vc.disconnect()
                        except:
                            pass
                        try:
                            voice_client = await channel.connect()
                        except:
                            pass

        except:
            pass

        await asyncio.sleep(15)

# =============================
# READY
# =============================

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")

    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
        print("✅ Slashcommands synced")
    except Exception as e:
        print(e)

    bot.loop.create_task(voice_keep_alive())

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

                await send_log(message.guild, f"🚨 {message.author} wurde wegen Mass Ping gebannt")

            except:
                pass
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

    await asyncio.sleep(0.3)

    entry = await get_latest_audit(member.guild, discord.AuditLogAction.bot_add)
    if not entry:
        return

    inviter = entry.user

    if not inviter or inviter.id in OWNERS or inviter.bot:
        return

    try:
        await member.guild.ban(member, reason="Unauthorized Bot")
        await member.guild.ban(inviter, reason="Bot Invite")

        await send_log(member.guild, f"🤖 Bot {member} wurde entfernt + Inviter {inviter} gebannt")

    except:
        pass

# =============================
# CHANNEL DELETE PROTECTION
# =============================

@bot.event
async def on_guild_channel_delete(channel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    guild = channel.guild
    await asyncio.sleep(0.2)

    entry = await get_latest_audit(guild, discord.AuditLogAction.channel_delete)
    if not entry:
        return

    user = entry.user
    if not user or user.id in OWNERS or user.bot:
        return

    try:
        await guild.ban(user, reason="Channel deleted")
        await send_log(guild, f"🧨 {user} hat einen Channel gelöscht und wurde gebannt")
    except:
        pass

# =============================
# WEBHOOK PROTECTION
# =============================

@bot.event
async def on_webhooks_update(channel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.2)

    entry = await get_latest_audit(channel.guild, discord.AuditLogAction.webhook_create)
    if not entry:
        return

    user = entry.user
    if not user or user.id in OWNERS or user.bot:
        return

    try:
        webhooks = await channel.webhooks()
        for hook in webhooks:
            await hook.delete(reason="Anti-Webhook")

        await channel.guild.ban(user, reason="Webhook created")

        await send_log(channel.guild, f"🔗 Webhook von {user} gelöscht + gebannt")

    except:
        pass

# =============================
# ROLE DELETE PROTECTION
# =============================

@bot.event
async def on_guild_role_delete(role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.2)

    entry = await get_latest_audit(role.guild, discord.AuditLogAction.role_delete)
    if not entry:
        return

    user = entry.user
    if not user or user.id in OWNERS or user.bot:
        return

    try:
        await role.guild.ban(user, reason="Role deleted")

        await send_log(role.guild, f"🧷 {user} hat eine Rolle gelöscht")

    except:
        pass

# =============================
# BAN DETECTION
# =============================

@bot.event
async def on_member_ban(guild, user):
    if guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.5)

    entry = await get_latest_audit(guild, discord.AuditLogAction.ban)
    if not entry:
        return

    actor = entry.user
    if not actor or actor.id in OWNERS or actor.bot:
        return

    try:
        await guild.ban(actor, reason="Unauthorized Ban")
        await send_log(guild, f"🚫 {actor} hat einen Ban gemacht → gebannt")
    except:
        pass

# =============================
# KICK DETECTION
# =============================

@bot.event
async def on_member_remove(member):
    guild = member.guild
    if guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.2)

    entry = await get_latest_audit(guild, discord.AuditLogAction.kick)
    if not entry or entry.target.id != member.id:
        return

    actor = entry.user
    if not actor or actor.id in OWNERS or actor.bot:
        return

    try:
        await guild.ban(actor, reason="Unauthorized Kick")
        await send_log(guild, f"🪓 {actor} hat einen Kick gemacht → gebannt")
    except:
        pass

# =============================
# CALL COMMAND
# =============================

@bot.command()
async def call(ctx):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return

    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Kein Zugriff")

    channel = bot.get_channel(CALL_VOICE_CHANNEL_ID)

    try:
        vc = ctx.voice_client

        if vc and vc.is_connected():
            await vc.move_to(channel)
        else:
            await channel.connect()

        await send_log(ctx.guild, "📞 Bot im Voice Call")
        await ctx.send("✅ Connected")

    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# =============================
# START
# =============================

bot.run(TOKEN)
