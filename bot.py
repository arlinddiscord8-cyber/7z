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

CALL_VOICE_CHANNEL_ID   = 1512776116438306816
LOG_CHANNEL_ID           = 1512582270106468385
WELCOME_CHANNEL_ID       = 1512774925126078566
RULES_CHANNEL_ID         = 1512774929253273821
TICKET_CATEGORY_ID       = 1512774917479993515
AUTO_ROLE_ID             = 1512774841005244426

TRIGGER_ROLE_ID          = 1512774837708525658
EXTRA_ROLE_1             = 1512774836806619239
EXTRA_ROLE_2             = 1512775255070867456

INVITE_CHANNEL_ID        = 1512774942184177765

# =============================
# BOT
# =============================

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix=["!", "?"], intents=intents)

# =============================
# BACKUP STORAGE (RESTORE SYSTEM)
# =============================

channel_backup = {}
role_backup = {}

# =============================
# READY
# =============================

@bot.event
async def on_ready():
    print(f"Online als {bot.user}")

# =============================
# TRIGGER ROLE SYSTEM
# =============================

@bot.event
async def on_member_update(before, after):
    before_roles = {r.id for r in before.roles}
    after_roles = {r.id for r in after.roles}

    if TRIGGER_ROLE_ID in after_roles and TRIGGER_ROLE_ID not in before_roles:
        for rid in (EXTRA_ROLE_1, EXTRA_ROLE_2):
            role = after.guild.get_role(rid)
            if role:
                try:
                    await after.add_roles(role)
                except:
                    pass

# =============================
# /SEND COMMAND
# =============================

@bot.tree.command(
    name="send",
    description="Send message",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def send_cmd(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)

    await channel.send(message)
    await interaction.response.send_message("✅ Gesendet", ephemeral=True)

# =============================
# BACKUP BEFORE DELETE
# =============================

@bot.event
async def on_guild_channel_delete(channel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    channel_backup[channel.id] = {
        "name": channel.name,
        "type": str(channel.type),
        "category": channel.category_id
    }

    await asyncio.sleep(1)

    try:
        if channel_backup.get(channel.id):
            data = channel_backup[channel.id]
            guild = channel.guild

            if data["type"] == "text":
                await guild.create_text_channel(
                    name=data["name"],
                    category=guild.get_channel(data["category"])
                )
            elif "voice" in data["type"]:
                await guild.create_voice_channel(
                    name=data["name"],
                    category=guild.get_channel(data["category"])
                )
    except:
        pass

# =============================
# ROLE BACKUP / RESTORE
# =============================

@bot.event
async def on_guild_role_delete(role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return

    role_backup[role.id] = {
        "name": role.name,
        "permissions": role.permissions,
        "color": role.color,
        "hoist": role.hoist,
        "mentionable": role.mentionable
    }

    try:
        await role.guild.create_role(
            name=role_backup[role.id]["name"],
            permissions=role_backup[role.id]["permissions"],
            color=role_backup[role.id]["color"],
            hoist=role_backup[role.id]["hoist"],
            mentionable=role_backup[role.id]["mentionable"]
        )
    except:
        pass

# =============================
# WELCOME
# =============================

@bot.event
async def on_member_join(member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel:
        embed = discord.Embed(
            title="Willkommen 👋",
            description=(
                f"Hey {member.mention},\n\n"
                "Wir freuen uns dich im **7zarnova** Server begrüßen zu dürfen!\n"
                "Bitte beachte die Regeln!\n\n"
                "• Sei nett\n• Viel Spaß!"
            )
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

# =============================
# START
# =============================

bot.run(TOKEN)
