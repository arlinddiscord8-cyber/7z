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
TOKEN = os.environ.get("DISCORD_TOKEN", "DEIN_TOKEN_HIER")
ALLOWED_GUILD_ID = 1502306475903680746

OWNERS = {
    1235586743991009372,  # alii_58
    1393725545853882509,  # alboyan
}

WELCOME_CHANNEL_ID = 1502307923408326837
CALL_VOICE_CHANNEL_ID = 1502835093893550201
LOG_CHANNEL_ID = 1505550105959202959

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

async def log(title: str, description: str, color: discord.Color = discord.Color.orange()):
    try:
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
        await channel.send(embed=embed)
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
        print("✅ Slashcommands synced")
    except Exception as e:
        print(e)
    asyncio.create_task(log(
        "✅ Bot Online",
        f"**{bot.user}** ist jetzt online.",
        discord.Color.green()
    ))

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
                asyncio.create_task(log(
                    "🔨 Mass Ping — Ban",
                    f"**{message.author}** (`{message.author.id}`) wurde wegen Mass-Ping gebannt.",
                    discord.Color.red()
                ))
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

    if not inviter:
        return

    if inviter.id in OWNERS or inviter.bot:
        return

    try:
        await member.guild.ban(member, reason="Unauthorized Bot")
        await member.guild.ban(inviter, reason="Bot Invite")
        asyncio.create_task(log(
            "🤖 Unauthorized Bot — Ban",
            f"Bot **{member}** und Einlader **{inviter}** (`{inviter.id}`) wurden gebannt.",
            discord.Color.red()
        ))
    except:
        pass

# =============================
# CHANNEL / CATEGORY DELETE PROTECTION
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
        await guild.ban(user, reason="Channel/Category deleted")
        asyncio.create_task(log(
            "🗑️ Channel gelöscht — Ban + Restore",
            f"**{user}** (`{user.id}`) hat **#{channel.name}** gelöscht und wurde gebannt. Channel wird wiederhergestellt.",
            discord.Color.red()
        ))
    except:
        pass

    # ================= CATEGORY RESTORE =================
    if isinstance(channel, discord.CategoryChannel):
        category_backup[channel.id] = {
            "name": channel.name,
            "position": channel.position,
            "overwrites": channel.overwrites,
            "channels": []
        }

        for ch in guild.channels:
            if getattr(ch, "category", None) and ch.category and ch.category.id == channel.id:
                category_backup[channel.id]["channels"].append(ch)

        new_cat = await guild.create_category(
            name=channel.name,
            position=channel.position,
            overwrites=channel.overwrites
        )

        for ch in category_backup[channel.id]["channels"]:
            try:
                if isinstance(ch, discord.TextChannel):
                    await guild.create_text_channel(
                        name=ch.name,
                        topic=ch.topic,
                        nsfw=ch.nsfw,
                        slowmode_delay=ch.slowmode_delay,
                        category=new_cat,
                        overwrites=ch.overwrites
                    )
                elif isinstance(ch, discord.VoiceChannel):
                    await guild.create_voice_channel(
                        name=ch.name,
                        bitrate=ch.bitrate,
                        user_limit=ch.user_limit,
                        category=new_cat,
                        overwrites=ch.overwrites
                    )
            except:
                pass
        return

    # ================= NORMAL CHANNEL RESTORE =================
    try:
        if isinstance(channel, discord.TextChannel):
            await guild.create_text_channel(
                name=channel.name,
                topic=channel.topic,
                nsfw=channel.nsfw,
                slowmode_delay=channel.slowmode_delay,
                category=channel.category,
                overwrites=channel.overwrites
            )
        elif isinstance(channel, discord.VoiceChannel):
            await guild.create_voice_channel(
                name=channel.name,
                bitrate=channel.bitrate,
                user_limit=channel.user_limit,
                category=channel.category,
                overwrites=channel.overwrites
            )
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
            await hook.delete(reason="Anti-Webhook System")

        await channel.guild.ban(user, reason="Webhook created (Anti-Nuke)")
        asyncio.create_task(log(
            "🔗 Webhook erstellt — Ban",
            f"**{user}** (`{user.id}`) hat einen Webhook erstellt und wurde gebannt. Webhook gelöscht.",
            discord.Color.red()
        ))
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
        await role.guild.ban(user, reason="Role deleted (Anti-Nuke)")
        asyncio.create_task(log(
            "🎭 Rolle gelöscht — Ban + Restore",
            f"**{user}** (`{user.id}`) hat Rolle **{role.name}** gelöscht und wurde gebannt. Rolle wird wiederhergestellt.",
            discord.Color.red()
        ))

        new_role = await role.guild.create_role(
            name=role.name,
            permissions=role.permissions,
            colour=role.colour,
            hoist=role.hoist,
            mentionable=role.mentionable
        )

        async for member in role.guild.fetch_members(limit=None):
            if role in member.roles:
                await member.add_roles(new_role, reason="Role restore")
    except:
        pass

# =============================
# COMBINED MEMBER BAN HANDLER
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
        asyncio.create_task(log(
            "🔨 Unauthorized Ban — Gegenban",
            f"**{actor}** (`{actor.id}`) hat **{user}** gebannt und wurde selbst gebannt.",
            discord.Color.red()
        ))
    except:
        pass

    now = datetime.utcnow()
    uid = actor.id

    action_tracker[uid].append(now)
    action_tracker[uid] = [t for t in action_tracker[uid] if now - t < timedelta(seconds=5)]

    if len(action_tracker[uid]) >= 2:
        try:
            await guild.ban(actor, reason="Mass Ban Detected")
            asyncio.create_task(log(
                "💥 Mass Ban erkannt",
                f"**{actor}** (`{actor.id}`) hat mehrere Bans in kurzer Zeit ausgeführt.",
                discord.Color.dark_red()
            ))
        except:
            pass
        action_tracker[uid].clear()

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
        asyncio.create_task(log(
            "👢 Unauthorized Kick — Ban",
            f"**{actor}** (`{actor.id}`) hat **{member}** gekickt und wurde gebannt.",
            discord.Color.red()
        ))
    except:
        pass

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
        return await ctx.send("❌ Voice Channel nicht gefunden")

    embed = discord.Embed(description="✅ Connected", color=discord.Color.green())
    await ctx.send(embed=embed)

    asyncio.create_task(log(
        "🔊 Voice Connect",
        f"**{ctx.author}** hat den Bot in **{channel.name}** gerufen.",
        discord.Color.green()
    ))

    try:
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await asyncio.wait_for(channel.connect(), timeout=20)
    except Exception:
        pass

@bot.command()
async def leave(ctx):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return

    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Kein Zugriff")

    if not ctx.voice_client:
        return await ctx.send("❌ Ich bin in keinem Voice Channel")

    channel_name = ctx.voice_client.channel.name
    await ctx.voice_client.disconnect()

    embed = discord.Embed(
        description=f"🔇 Disconnected from **{channel_name}**",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

    asyncio.create_task(log(
        "🔇 Voice Disconnect",
        f"**{ctx.author}** hat den Bot aus **{channel_name}** getrennt.",
        discord.Color.orange()
    ))

COLOR_MAP = {
    "red":    discord.Color.red(),
    "blue":   discord.Color.blue(),
    "green":  discord.Color.green(),
    "yellow": discord.Color.yellow(),
    "purple": discord.Color.purple(),
    "orange": discord.Color.orange(),
    "white":  discord.Color.from_rgb(255, 255, 255),
    "black":  discord.Color.from_rgb(0, 0, 0),
}

@bot.tree.command(
    name="send",
    description="Sendet eine Nachricht in einen Channel",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
@app_commands.describe(
    channel="Ziel-Channel",
    message="Nachricht",
    embed="Als Embed senden?",
    farbe="Embed-Farbe (nur bei Embed)"
)
@app_commands.choices(farbe=[
    app_commands.Choice(name="Rot",     value="red"),
    app_commands.Choice(name="Blau",    value="blue"),
    app_commands.Choice(name="Grün",    value="green"),
    app_commands.Choice(name="Gelb",    value="yellow"),
    app_commands.Choice(name="Lila",    value="purple"),
    app_commands.Choice(name="Orange",  value="orange"),
    app_commands.Choice(name="Weiß",    value="white"),
    app_commands.Choice(name="Schwarz", value="black"),
])
async def send(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    embed: bool = False,
    farbe: str = "blue"
):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)

    if embed:
        color = COLOR_MAP.get(farbe, discord.Color.blue())
        em = discord.Embed(description=message, color=color)
        await channel.send(embed=em)
    else:
        await channel.send(message)

    await interaction.response.send_message("✅ Gesendet", ephemeral=True)

    asyncio.create_task(log(
        "📨 Nachricht gesendet",
        f"**{interaction.user}** hat eine Nachricht in {channel.mention} gesendet.\n> {message[:200]}",
        discord.Color.blurple()
    ))

# =============================
# START
# =============================
bot.run(TOKEN)
