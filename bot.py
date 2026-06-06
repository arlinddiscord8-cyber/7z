import discord
from discord.ext import commands
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import os

TOKEN = os.getenv("TOKEN")

# =============================
# CONFIG
# =============================

ALLOWED_GUILD_ID = 1512581389726388314

OWNERS = {
    1393725545853882509,
    1235586743991009372
}

CALL_VOICE_CHANNEL_ID = 1512776116438306816
LOG_CHANNEL_ID = 1512582270106468385

VOICE_ALWAYS_ON = True
voice_client = None

# =============================
# BOT SETUP
# =============================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

ping_tracker = defaultdict(list)
action_tracker = defaultdict(list)

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

def get_color(color: str):
    if color == "white":
        return discord.Color.from_rgb(255, 255, 255)
    return discord.Color.from_rgb(0, 0, 0)

async def send_log(guild, text):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(text)
        except:
            pass

# =============================
# READY
# =============================

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")
    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
    except:
        pass
    asyncio.create_task(voice_keep_alive())

# =============================
# VOICE SYSTEM (STABIL)
# =============================

async def voice_keep_alive():
    await bot.wait_until_ready()

    global voice_client

    while VOICE_ALWAYS_ON:
        try:
            channel = bot.get_channel(CALL_VOICE_CHANNEL_ID)

            if channel:
                vc = discord.utils.get(bot.voice_clients, guild=channel.guild)

                if vc is None:
                    try:
                        voice_client = await channel.connect()
                    except:
                        pass

                elif not vc.is_connected():
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

        await asyncio.sleep(20)

# =============================
# SECURITY SYSTEM
# =============================

@bot.event
async def on_guild_channel_delete(channel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.2)
    entry = await get_latest_audit(channel.guild, discord.AuditLogAction.channel_delete)
    if not entry:
        return

    user = entry.user
    if not user or user.id in OWNERS or user.bot:
        return

    try:
        await channel.guild.ban(user, reason="Channel Delete")
        await send_log(channel.guild, f"🧨 {user} hat Channel gelöscht → gebannt")
    except:
        pass


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
        await role.guild.ban(user, reason="Role Delete")
        await send_log(role.guild, f"🧷 {user} hat Role gelöscht → gebannt")
    except:
        pass


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
        for w in webhooks:
            await w.delete()

        await channel.guild.ban(user, reason="Webhook")
        await send_log(channel.guild, f"🔗 Webhook Angriff von {user}")
    except:
        pass


@bot.event
async def on_member_ban(guild, user):
    if guild.id != ALLOWED_GUILD_ID:
        return

    await asyncio.sleep(0.3)
    entry = await get_latest_audit(guild, discord.AuditLogAction.ban)
    if not entry:
        return

    actor = entry.user
    if not actor or actor.id in OWNERS or actor.bot:
        return

    try:
        await guild.ban(actor, reason="Unauthorized Ban")
        await send_log(guild, f"🚫 {actor} hat Ban gemacht → gebannt")
    except:
        pass


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
        await guild.ban(actor, reason="Kick Abuse")
        await send_log(guild, f"🪓 {actor} hat Kick gemacht → gebannt")
    except:
        pass

# =============================
# /SEND COMMAND
# =============================

@bot.tree.command(
    name="send",
    description="Sendet Nachricht",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def send(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    embed: bool = True,
    color: str = "black"
):

    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)

    try:
        if embed:
            emb = discord.Embed(
                description=message,
                color=get_color(color)
            )
            await channel.send(embed=emb)
        else:
            await channel.send(message)

        await interaction.response.send_message("✅ Gesendet", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# =============================
# !CALL
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
