import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
from datetime import datetime
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

CALL_VOICE_CHANNEL_ID = 1510715789567590630

LOG_CHANNEL_ID = 1510606418888360101

VOICE_ALWAYS_ON = True
voice_client = None

# =============================
# BOT SETUP
# =============================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# =============================
# HELPERS
# =============================

def is_owner(user_id: int):
    return user_id in OWNERS

def get_color(color: str):
    if color == "white":
        return discord.Color.from_rgb(255, 255, 255)
    return discord.Color.from_rgb(0, 0, 0)

async def send_log(guild, text):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    try:
        await channel.send(text)
    except:
        pass

# =============================
# VOICE KEEP ALIVE (STABIL)
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
# /SEND (FULL FIX MIT AUSWAHL)
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
    color: str = "black"  # "black" oder "white"
):

    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)

    try:
        if embed:
            emb = discord.Embed(
                description=message,
                color=get_color(color.lower())
            )
            await channel.send(embed=emb)
        else:
            await channel.send(message)

        await interaction.response.send_message(
            f"✅ Gesendet | Embed: {embed} | Farbe: {color}",
            ephemeral=True
        )

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
