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
INVITE_CHANNEL_ID        = 1512774942184177765
ROLE_CMD_ALLOWED_ROLE_ID = 1512774843047870564  # Einzige Rolle die ?role nutzen darf

VOICE_ALWAYS_ON = True
voice_client = None

# =============================
# SECURITY CONFIG
# =============================

# Anti-Spam: max messages per seconds
SPAM_MAX_MESSAGES   = 5
SPAM_INTERVAL       = 3      # seconds
SPAM_TIMEOUT_SECS   = 300    # 5 min timeout

# Mention Spam
MENTION_MAX         = 4      # max mentions per message

# Channel/Role create spam
CREATE_MAX          = 3
CREATE_INTERVAL     = 15     # seconds

# Invite filter
INVITE_PATTERN      = re.compile(r"(discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE)

# Whitelist: user IDs or role IDs that bypass security
SECURITY_WHITELIST_USERS: set[int] = set()
SECURITY_WHITELIST_ROLES: set[int] = set()

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
intents.moderation = True
bot = commands.Bot(command_prefix=["!", "?"], intents=intents)

timeout_tracker      = defaultdict(list)
kick_tracker         = defaultdict(list)
ban_tracker          = defaultdict(list)
ticket_del_tracker   = defaultdict(list)
spam_tracker         = defaultdict(list)
channel_create_tracker = defaultdict(list)
role_create_tracker  = defaultdict(list)
spam_warned          = set()

counting_state = {
    "current": 0,
    "last_user": None,
    "delete_notice": None,
}

first_react_announced = set()
ticket_counter = 0

# =============================
# INVITE DATABASE
# =============================

_db = sqlite3.connect("invites.db")
_cur = _db.cursor()
_cur.execute("""
CREATE TABLE IF NOT EXISTS invites (
    guild_id INTEGER,
    user_id  INTEGER,
    invites  INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")
_db.commit()

def _add_invite(guild_id: int, user_id: int, amount: int = 1):
    _cur.execute("""
        INSERT INTO invites (guild_id, user_id, invites)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET invites = invites + ?
    """, (guild_id, user_id, amount, amount))
    _db.commit()

def _get_invites(guild_id: int, user_id: int) -> int:
    _cur.execute("SELECT invites FROM invites WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = _cur.fetchone()
    return row[0] if row else 0

def _get_top(guild_id: int, limit: int = 10):
    _cur.execute("""
        SELECT user_id, invites FROM invites
        WHERE guild_id = ? ORDER BY invites DESC LIMIT ?
    """, (guild_id, limit))
    return _cur.fetchall()

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

def is_whitelisted(member: discord.Member) -> bool:
    """Returns True if the member is whitelisted from security actions."""
    if member.id in OWNERS:
        return True
    if member.id in SECURITY_WHITELIST_USERS:
        return True
    for role in member.roles:
        if role.id in SECURITY_WHITELIST_ROLES:
            return True
    return False

async def get_latest_audit(guild, action):
    try:
        return await guild.audit_logs(limit=1, action=action).__anext__()
    except Exception:
        return None

def get_color(color: str):
    if color == "white":
        return discord.Color.from_rgb(255, 255, 255)
    return discord.Color.from_rgb(0, 0, 0)

def is_new_account(user: discord.User, days: int = 7) -> bool:
    """Returns True if the account is younger than `days` days."""
    return (datetime.utcnow() - user.created_at.replace(tzinfo=None)) < timedelta(days=days)

async def security_log(guild, title: str, description: str, color: discord.Color = discord.Color.red(), fields: list = None):
    """Enhanced log with embed, timestamp, and optional fields."""
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title=f"🔒 {title}",
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    if fields:
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
    embed.set_footer(text="Security System")
    try:
        await channel.send(embed=embed)
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
    asyncio.create_task(cleanup_trackers())

    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

# =============================
# TRACKER CLEANUP (Memory-Leak Fix)
# =============================

async def cleanup_trackers():
    """Periodically cleans up expired tracker entries to prevent memory leaks."""
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(60)
        now = datetime.utcnow()
        for tracker, window in [
            (timeout_tracker, 15),
            (kick_tracker, 20),
            (ban_tracker, 20),
            (spam_tracker, SPAM_INTERVAL),
            (channel_create_tracker, CREATE_INTERVAL),
            (role_create_tracker, CREATE_INTERVAL),
        ]:
            dead_keys = []
            for uid, times in tracker.items():
                tracker[uid] = [t for t in times if now - t < timedelta(seconds=window)]
                if not tracker[uid]:
                    dead_keys.append(uid)
            for k in dead_keys:
                del tracker[k]

# =============================
# VOICE SYSTEM
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
                    except Exception:
                        pass
                elif not vc.is_connected():
                    try:
                        await vc.disconnect()
                    except Exception:
                        pass
                    try:
                        voice_client = await channel.connect()
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(20)

# =============================
# WELCOME NEW MEMBERS
# =============================

@bot.event
async def on_member_join(member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    # New account warning
    if is_new_account(member.user if hasattr(member, 'user') else member, days=7):
        await security_log(
            member.guild,
            "Neuer Account beigetreten",
            f"{member.mention} hat einen Account der jünger als 7 Tage ist.",
            color=discord.Color.orange(),
            fields=[
                ("User", f"{member} ({member.id})"),
                ("Account erstellt", f"<t:{int(member.created_at.timestamp())}:R>"),
            ]
        )

    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Auto-Rolle beim Beitreten")
        except Exception:
            pass

    welcome_channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        try:
            embed = discord.Embed(
                description=(
                    f"Hey {member.mention},\n\n"
                    f"Wir freuen uns dich im **7zarnova** Server begrüßen zu dürfen!\n"
                    f"Bitte beachte unser https://discord.com/channels/{ALLOWED_GUILD_ID}/{RULES_CHANNEL_ID}!\n\n"
                    f"• Sei Nett\n"
                    f"• Viel Spaß!"
                ),
                color=discord.Color.from_rgb(149, 165, 166)
            )
            await welcome_channel.send(embed=embed)
        except Exception:
            pass

    # Invite tracking
    try:
        new_invites = await member.guild.invites()
        old_cache = invite_cache.get(member.guild.id, {})
        used_invite = None

        for inv in new_invites:
            if inv.uses > old_cache.get(inv.code, 0):
                used_invite = inv
                break

        invite_cache[member.guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used_invite and used_invite.inviter:
            _add_invite(member.guild.id, used_invite.inviter.id, 1)
            total = _get_invites(member.guild.id, used_invite.inviter.id)
            invite_ch = member.guild.get_channel(INVITE_CHANNEL_ID)
            if invite_ch:
                embed = discord.Embed(
                    description=(
                        f"**{member.mention}** just joined. "
                        f"They were invited by **{used_invite.inviter.name}** "
                        f"who now has **{total} invites** !"
                    ),
                    color=discord.Color.from_rgb(149, 165, 166)
                )
                await invite_ch.send(embed=embed)
    except Exception:
        pass

# =============================
# BOOST NOTIFICATION
# =============================

@bot.event
async def on_member_update(before, after):
    if after.guild.id != ALLOWED_GUILD_ID:
        return

    if not before.premium_since and after.premium_since:
        boost_channel = after.guild.get_channel(BOOST_CHANNEL_ID)
        if boost_channel:
            try:
                await boost_channel.send("danke 🫶🏻!")
            except Exception:
                pass

    before_ids = {r.id for r in before.roles}
    after_ids  = {r.id for r in after.roles}

    if TRIGGER_ROLE_ID in after_ids and TRIGGER_ROLE_ID not in before_ids:
        for extra_id in (EXTRA_ROLE_ID_1, EXTRA_ROLE_ID_2):
            extra_role = after.guild.get_role(extra_id)
            if extra_role:
                try:
                    await after.add_roles(extra_role, reason="Trigger-Rolle vergeben")
                except Exception:
                    pass

# =============================
# AUTO-REACT & MESSAGES
# =============================

@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    guild = message.guild
    if not guild or guild.id != ALLOWED_GUILD_ID:
        await bot.process_commands(message)
        return

    # ── Anti-Spam ──────────────────────────────────────────
    if not is_whitelisted(message.author):
        now = datetime.utcnow()

        # Message spam
        spam_tracker[message.author.id].append(now)
        spam_tracker[message.author.id] = [
            t for t in spam_tracker[message.author.id]
            if now - t < timedelta(seconds=SPAM_INTERVAL)
        ]
        if len(spam_tracker[message.author.id]) >= SPAM_MAX_MESSAGES:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                await message.author.timeout(until, reason="Auto-Timeout: Nachrichten-Spam")
                await message.channel.send(
                    f"⏱️ {message.author.mention} wurde für 5 Minuten getimeoutet (Spam).",
                    delete_after=5
                )
                spam_tracker[message.author.id].clear()
                await security_log(
                    guild,
                    "Anti-Spam: Timeout",
                    f"{message.author.mention} wurde automatisch getimeoutet.",
                    color=discord.Color.orange(),
                    fields=[
                        ("User", f"{message.author} ({message.author.id})"),
                        ("Kanal", message.channel.mention),
                        ("Dauer", "5 Minuten"),
                    ]
                )
            except Exception:
                pass
            return

        # Mention spam
        total_mentions = len(message.mentions) + len(message.role_mentions)
        if total_mentions >= MENTION_MAX:
            try:
                await message.delete()
                until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                await message.author.timeout(until, reason="Auto-Timeout: Mention-Spam")
                await message.channel.send(
                    f"🚫 {message.author.mention} wurde für 5 Minuten getimeoutet (Mention-Spam).",
                    delete_after=5
                )
                await security_log(
                    guild,
                    "Anti-Spam: Mention-Spam",
                    f"{message.author.mention} hat {total_mentions} Mentions in einer Nachricht gesendet.",
                    color=discord.Color.orange(),
                    fields=[
                        ("User", f"{message.author} ({message.author.id})"),
                        ("Kanal", message.channel.mention),
                        ("Mentions", str(total_mentions)),
                    ]
                )
            except Exception:
                pass
            return

        # Discord invite filter
        if INVITE_PATTERN.search(message.content):
            try:
                await message.delete()
                await message.channel.send(
                    f"🔗 {message.author.mention} Discord-Einladungen sind nicht erlaubt!",
                    delete_after=5
                )
                await security_log(
                    guild,
                    "Invite-Link geblockt",
                    f"{message.author.mention} hat einen Invite-Link gesendet.",
                    color=discord.Color.orange(),
                    fields=[
                        ("User", f"{message.author} ({message.author.id})"),
                        ("Kanal", message.channel.mention),
                    ]
                )
            except Exception:
                pass
            return

    # ── Auto-React ─────────────────────────────────────────
    if message.channel.id in AUTO_REACT_CHANNEL_IDS:
        if message.channel.id == 1512774955413147648:
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
        else:
            try:
                await message.add_reaction("✔️")
            except Exception:
                pass

    if COUNTING_CHANNEL_ID != 0 and message.channel.id == COUNTING_CHANNEL_ID:
        await handle_counting(message)
        return

    await bot.process_commands(message)

# =============================
# MESSAGE EDIT LOG
# =============================

@bot.event
async def on_message_edit(before, after):
    if not after.guild or after.guild.id != ALLOWED_GUILD_ID:
        return
    if after.author.bot:
        return
    if before.content == after.content:
        return

    await security_log(
        after.guild,
        "Nachricht bearbeitet",
        f"{after.author.mention} hat eine Nachricht bearbeitet.",
        color=discord.Color.blurple(),
        fields=[
            ("User", f"{after.author} ({after.author.id})"),
            ("Kanal", after.channel.mention),
            ("Vorher", before.content[:300] or "*(leer)*"),
            ("Nachher", after.content[:300] or "*(leer)*"),
        ]
    )

# =============================
# MESSAGE DELETE LOG
# =============================

@bot.event
async def on_message_delete(message):
    if not message.guild or message.guild.id != ALLOWED_GUILD_ID:
        return

    if COUNTING_CHANNEL_ID != 0 and message.channel.id == COUNTING_CHANNEL_ID:
        if message.author.bot:
            return
        next_num = counting_state["current"] + 1
        try:
            notice = await message.channel.send(
                f"🗑️ Eine Nachricht wurde gelöscht. Die nächste Zahl ist **{next_num}**."
            )
            counting_state["delete_notice"] = notice
        except Exception:
            pass
        return

    if message.author.bot:
        return

    await security_log(
        message.guild,
        "Nachricht gelöscht",
        f"Eine Nachricht von {message.author.mention} wurde gelöscht.",
        color=discord.Color.dark_gray(),
        fields=[
            ("User", f"{message.author} ({message.author.id})"),
            ("Kanal", message.channel.mention),
            ("Inhalt", message.content[:400] or "*(kein Text / Anhang)*"),
        ]
    )

# =============================
# COUNTING SYSTEM
# =============================

async def handle_counting(message):
    content = message.content.strip()
    expected = counting_state["current"] + 1

    value = None
    if content.lstrip("-").isdigit():
        value = int(content)
    else:
        value = eval_math_expression(content)

    if value is None:
        try:
            await message.delete()
        except Exception:
            pass
        return

    if message.author.id == counting_state["last_user"]:
        try:
            await message.delete()
        except Exception:
            pass
        try:
            note = await message.channel.send(
                f"❌ {message.author.mention} Du kannst nicht zweimal hintereinander zählen!"
            )
            await asyncio.sleep(1.5)
            await note.delete()
        except Exception:
            pass
        return

    if value == expected:
        counting_state["current"] = expected
        counting_state["last_user"] = message.author.id
        if counting_state["delete_notice"] is not None:
            try:
                await counting_state["delete_notice"].delete()
            except Exception:
                pass
            counting_state["delete_notice"] = None
        try:
            await message.add_reaction("✔️")
        except Exception:
            pass
    else:
        try:
            note = await message.channel.send(
                f"❌ Das stimmt nicht! Die nächste Zahl ist **{expected}**."
            )
            await asyncio.sleep(1.5)
            await note.delete()
        except Exception:
            pass

# =============================
# FIRST REACTOR ANNOUNCEMENT
# =============================

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    if not reaction.message.guild or reaction.message.guild.id != ALLOWED_GUILD_ID:
        return
    if reaction.message.channel.id != 1512774955413147648:
        return
    msg_id = reaction.message.id
    if msg_id in first_react_announced:
        return
    first_react_announced.add(msg_id)
    try:
        await reaction.message.channel.send(f"{user.mention} war 🥇!")
    except Exception:
        pass

# =============================
# VOICE STATE LOG
# =============================

@bot.event
async def on_voice_state_update(member, before, after):
    if not member.guild or member.guild.id != ALLOWED_GUILD_ID:
        return
    if member.bot:
        return

    if before.channel is None and after.channel is not None:
        await security_log(
            member.guild,
            "Voice: Beigetreten",
            f"{member.mention} ist einem Voice-Kanal beigetreten.",
            color=discord.Color.green(),
            fields=[
                ("User", f"{member} ({member.id})"),
                ("Kanal", after.channel.name),
            ]
        )
    elif before.channel is not None and after.channel is None:
        await security_log(
            member.guild,
            "Voice: Verlassen",
            f"{member.mention} hat einen Voice-Kanal verlassen.",
            color=discord.Color.dark_green(),
            fields=[
                ("User", f"{member} ({member.id})"),
                ("Kanal", before.channel.name),
            ]
        )
    elif before.channel != after.channel:
        await security_log(
            member.guild,
            "Voice: Gewechselt",
            f"{member.mention} hat den Voice-Kanal gewechselt.",
            color=discord.Color.blurple(),
            fields=[
                ("User", f"{member} ({member.id})"),
                ("Von", before.channel.name),
                ("Nach", after.channel.name),
            ]
        )

# =============================
# TICKET SYSTEM
# =============================

class TicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket erstellen", emoji="📧", style=discord.ButtonStyle.blurple, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        global ticket_counter

        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        if category:
            for ch in category.text_channels:
                if ch.name.startswith("ticket-"):
                    overwrite = ch.overwrites_for(interaction.user)
                    if overwrite.read_messages:
                        return await interaction.response.send_message(
                            f"❌ Du hast bereits ein offenes Ticket: {ch.mention}",
                            ephemeral=True
                        )

        ticket_counter += 1
        current_ticket_num = ticket_counter
        support_role = guild.get_role(SUPPORT_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        for role in guild.roles:
            if role.permissions.administrator and role not in overwrites:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{current_ticket_num}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket von {interaction.user}"
            )

            embed = discord.Embed(
                title="Ticket erfolgreich erstellt! 🎟️",
                description=(
                    "Beschreibe dein Anliegen bitte schon so genau wie möglich. "
                    "Unser Team kümmert sich so schnell wie möglich um dich – "
                    "danke für deine Geduld!"
                ),
                color=discord.Color.from_rgb(149, 165, 166)
            )

            pings = interaction.user.mention
            if support_role:
                pings = f"{support_role.mention} {interaction.user.mention}"

            await ticket_channel.send(content=pings, embed=embed)

            await interaction.response.send_message(
                f"✅ Dein Ticket wurde erstellt: {ticket_channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler beim Erstellen: {e}", ephemeral=True)


@bot.tree.command(
    name="ticketpanel",
    description="Sendet das Ticket-Panel in den Ticket-Kanal",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def ticketpanel(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)

    channel = interaction.guild.get_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Ticket-Kanal nicht gefunden.", ephemeral=True)

    embed = discord.Embed(
        title="Ticket erstellen 📧",
        description=(
            "Klicke unten, um ein Ticket zu öffnen. "
            "Bitte hab ein wenig Geduld und bleib höflich, "
            "wir supporten dich so schnell es geht!"
        ),
        color=discord.Color.from_rgb(149, 165, 166)
    )

    try:
        await channel.send(embed=embed, view=TicketButton())
        await interaction.response.send_message("✅ Ticket-Panel gesendet!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)


def is_ticket_channel(channel):
    return (
        channel.category_id == TICKET_CATEGORY_ID
        and channel.name.startswith("ticket-")
    )

def can_manage_ticket(member):
    if member.id in OWNERS:
        return True
    for role in member.roles:
        if role.id == SUPPORT_ROLE_ID or role.permissions.administrator:
            return True
    return False


@bot.command()
async def close(ctx):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not is_ticket_channel(ctx.channel):
        return await ctx.send("❌ Das ist kein Ticket-Kanal.")
    if not can_manage_ticket(ctx.author):
        return await ctx.send("❌ Kein Zugriff.")
    try:
        await ctx.send("🔒 Ticket wird geschlossen...")
        await ctx.channel.set_permissions(ctx.guild.default_role, read_messages=False, send_messages=False)
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")


@bot.command(name="delete")
async def delete_ticket(ctx):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not is_ticket_channel(ctx.channel):
        return await ctx.send("❌ Das ist kein Ticket-Kanal.")
    if not can_manage_ticket(ctx.author):
        return await ctx.send("❌ Kein Zugriff.")

    if ctx.author.id not in OWNERS:
        now = datetime.utcnow()
        ticket_del_tracker[ctx.author.id] = [
            t for t in ticket_del_tracker[ctx.author.id]
            if now - t < timedelta(seconds=30)
        ]
        if len(ticket_del_tracker[ctx.author.id]) >= 3:
            return await ctx.send(
                "❌ Du kannst nicht mehr als 3 Tickets in 30 Sekunden löschen.",
                delete_after=5
            )
        ticket_del_tracker[ctx.author.id].append(now)

    try:
        await ctx.channel.delete(reason=f"Ticket gelöscht von {ctx.author}")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# =============================
# PURGE COMMAND
# =============================

@bot.command()
async def purge(ctx, amount: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await ctx.send("❌ Kein Zugriff.")

    try:
        await ctx.message.delete()
    except Exception:
        pass

    if amount is None:
        return await ctx.send("❌ Verwendung: `?purge all` oder `?purge <Anzahl>`", delete_after=3)

    if amount.lower() == "all":
        deleted = await ctx.channel.purge(limit=None)
        note = await ctx.send(f"🗑️ {len(deleted)} Nachrichten gelöscht.")
        await asyncio.sleep(3)
        try:
            await note.delete()
        except Exception:
            pass
    else:
        try:
            num = int(amount)
            if num < 1:
                return await ctx.send("❌ Zahl muss mindestens 1 sein.", delete_after=3)
            deleted = await ctx.channel.purge(limit=num)
            note = await ctx.send(f"🗑️ {len(deleted)} Nachrichten gelöscht.")
            await asyncio.sleep(3)
            try:
                await note.delete()
            except Exception:
                pass
        except ValueError:
            await ctx.send("❌ Verwendung: `?purge all` oder `?purge <Anzahl>`", delete_after=3)

# =============================
# ROLE COMMAND
# =============================

def can_use_role_cmd(member: discord.Member) -> bool:
    """Nur Owners oder Mitglieder mit ROLE_CMD_ALLOWED_ROLE_ID dürfen ?role nutzen."""
    if member.id in OWNERS:
        return True
    return any(r.id == ROLE_CMD_ALLOWED_ROLE_ID for r in member.roles)

@bot.command(name="role")
async def role_cmd(ctx, member: discord.Member = None, *, role_input: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return

    # Berechtigung prüfen
    if not can_use_role_cmd(ctx.author):
        msg = await ctx.send("❌ Du hast keine Berechtigung für diesen Command.")
        await asyncio.sleep(4)
        try:
            await ctx.message.delete()
            await msg.delete()
        except Exception:
            pass
        return

    # Verwendung prüfen
    if member is None or role_input is None:
        msg = await ctx.send(
            "❌ **Verwendung:** `?role @user Rollenname` oder `?role @user RollenID`"
        )
        await asyncio.sleep(5)
        try:
            await ctx.message.delete()
            await msg.delete()
        except Exception:
            pass
        return

    # Rolle suchen: erst nach ID, dann nach Name
    role = None
    role_input = role_input.strip()

    if role_input.isdigit():
        role = ctx.guild.get_role(int(role_input))
    if role is None:
        role = discord.utils.find(
            lambda r: r.name.lower() == role_input.lower(),
            ctx.guild.roles
        )
    # Partial match als Fallback
    if role is None:
        matches = [r for r in ctx.guild.roles if role_input.lower() in r.name.lower()]
        if len(matches) == 1:
            role = matches[0]
        elif len(matches) > 1:
            names = ", ".join(f"**{r.name}**" for r in matches[:8])
            msg = await ctx.send(f"⚠️ Mehrere Rollen gefunden: {names}\nBitte genauer angeben.")
            await asyncio.sleep(6)
            try:
                await ctx.message.delete()
                await msg.delete()
            except Exception:
                pass
            return

    if role is None:
        msg = await ctx.send(f"❌ Rolle **{role_input}** nicht gefunden.")
        await asyncio.sleep(4)
        try:
            await ctx.message.delete()
            await msg.delete()
        except Exception:
            pass
        return

    # Bot darf die Rolle nicht verwalten wenn sie höher ist
    if role >= ctx.guild.me.top_role:
        msg = await ctx.send("❌ Diese Rolle ist höher als meine eigene – ich kann sie nicht verwalten.")
        await asyncio.sleep(4)
        try:
            await ctx.message.delete()
            await msg.delete()
        except Exception:
            pass
        return

    # Verhindere dass jemand sich Admin-Rollen gibt
    if role.permissions.administrator and ctx.author.id not in OWNERS:
        msg = await ctx.send("❌ Admin-Rollen dürfen nicht mit diesem Command vergeben werden.")
        await asyncio.sleep(4)
        try:
            await ctx.message.delete()
            await msg.delete()
        except Exception:
            pass
        return

    try:
        if role in member.roles:
            await member.remove_roles(role, reason=f"Entfernt von {ctx.author} via ?role")
            embed = discord.Embed(
                description=f"➖ {member.mention} wurde die Rolle **{role.name}** entfernt.",
                color=discord.Color.red()
            )
        else:
            await member.add_roles(role, reason=f"Vergeben von {ctx.author} via ?role")
            embed = discord.Embed(
                description=f"➕ {member.mention} hat die Rolle **{role.name}** erhalten.",
                color=discord.Color.green()
            )
        embed.set_footer(text=f"Ausgeführt von {ctx.author} • {ctx.author.id}")
        await ctx.send(embed=embed)

        # Log
        await security_log(
            ctx.guild,
            "?role verwendet",
            f"{ctx.author.mention} hat die Rolle **{role.name}** bei {member.mention} geändert.",
            color=discord.Color.blurple(),
            fields=[
                ("Ausgeführt von", f"{ctx.author} ({ctx.author.id})"),
                ("Ziel", f"{member} ({member.id})"),
                ("Rolle", f"{role.name} ({role.id})"),
            ]
        )

    except discord.Forbidden:
        await ctx.send("❌ Ich habe keine Berechtigung, diese Rolle zu vergeben/entfernen.")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# =============================
# INVITES SLASH COMMANDS
# =============================

@bot.tree.command(
    name="invite",
    description="Zeigt die Invite-Anzahl eines Users",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def invite_cmd(interaction: discord.Interaction, member: discord.Member):
    count = _get_invites(interaction.guild.id, member.id)
    embed = discord.Embed(
        description=f"📨 **{member.name}** hat **{count} Invites**",
        color=discord.Color.from_rgb(149, 165, 166)
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(
    name="leaderboard",
    description="Zeigt das Invite-Leaderboard",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def leaderboard_cmd(interaction: discord.Interaction):
    top = _get_top(interaction.guild.id)
    if not top:
        return await interaction.response.send_message("Noch keine Invites gespeichert.", ephemeral=True)

    embed = discord.Embed(
        title="🏆 Invite Leaderboard",
        color=discord.Color.from_rgb(149, 165, 166)
    )
    for i, (user_id, count) in enumerate(top, start=1):
        user = bot.get_user(user_id)
        name = user.name if user else f"User {user_id}"
        embed.add_field(name=f"{i}. {name}", value=f"📨 {count} Invites", inline=False)
    await interaction.response.send_message(embed=embed)

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
    if not user or is_whitelisted(channel.guild.get_member(user.id) or user):
        return
    try:
        await channel.guild.ban(user, reason="Channel Delete")
        await security_log(
            channel.guild,
            "Channel gelöscht → Ban",
            f"{user.mention} hat einen Channel gelöscht und wurde gebannt.",
            fields=[
                ("User", f"{user} ({user.id})"),
                ("Channel", channel.name),
            ]
        )
    except Exception:
        pass


@bot.event
async def on_guild_channel_create(channel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return
    await asyncio.sleep(0.2)
    entry = await get_latest_audit(channel.guild, discord.AuditLogAction.channel_create)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(channel.guild.get_member(user.id) or user):
        return

    now = datetime.utcnow()
    channel_create_tracker[user.id].append(now)
    channel_create_tracker[user.id] = [
        t for t in channel_create_tracker[user.id]
        if now - t < timedelta(seconds=CREATE_INTERVAL)
    ]

    if len(channel_create_tracker[user.id]) >= CREATE_MAX:
        try:
            await channel.guild.ban(user, reason=f"Channel Create Spam ({CREATE_MAX}+ in {CREATE_INTERVAL}s)")
            await security_log(
                channel.guild,
                "Channel Create Spam → Ban",
                f"{user.mention} hat {CREATE_MAX}+ Channels in {CREATE_INTERVAL}s erstellt.",
                fields=[
                    ("User", f"{user} ({user.id})"),
                    ("Anzahl", str(len(channel_create_tracker[user.id]))),
                ]
            )
            channel_create_tracker[user.id].clear()
        except Exception:
            pass


@bot.event
async def on_guild_role_delete(role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return

    saved_name        = role.name
    saved_color       = role.color
    saved_permissions = role.permissions
    saved_hoist       = role.hoist
    saved_mentionable = role.mentionable

    await asyncio.sleep(0.2)
    entry = await get_latest_audit(role.guild, discord.AuditLogAction.role_delete)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(role.guild.get_member(user.id) or user):
        return

    try:
        await role.guild.ban(user, reason="Role Delete")
        await security_log(
            role.guild,
            "Rolle gelöscht → Ban",
            f"{user.mention} hat eine Rolle gelöscht und wurde gebannt.",
            fields=[
                ("User", f"{user} ({user.id})"),
                ("Rolle", saved_name),
            ]
        )
    except Exception:
        pass

    try:
        await role.guild.create_role(
            name=saved_name,
            color=saved_color,
            permissions=saved_permissions,
            hoist=saved_hoist,
            mentionable=saved_mentionable,
            reason="Automatische Wiederherstellung (Schutz)"
        )
        await security_log(
            role.guild,
            "Rolle wiederhergestellt",
            f"Rolle **{saved_name}** wurde automatisch wiederhergestellt.",
            color=discord.Color.green()
        )
    except Exception:
        pass


@bot.event
async def on_guild_role_create(role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return
    await asyncio.sleep(0.2)
    entry = await get_latest_audit(role.guild, discord.AuditLogAction.role_create)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(role.guild.get_member(user.id) or user):
        return

    now = datetime.utcnow()
    role_create_tracker[user.id].append(now)
    role_create_tracker[user.id] = [
        t for t in role_create_tracker[user.id]
        if now - t < timedelta(seconds=CREATE_INTERVAL)
    ]

    if len(role_create_tracker[user.id]) >= CREATE_MAX:
        try:
            await role.guild.ban(user, reason=f"Role Create Spam ({CREATE_MAX}+ in {CREATE_INTERVAL}s)")
            await security_log(
                role.guild,
                "Role Create Spam → Ban",
                f"{user.mention} hat {CREATE_MAX}+ Rollen in {CREATE_INTERVAL}s erstellt.",
                fields=[
                    ("User", f"{user} ({user.id})"),
                    ("Anzahl", str(len(role_create_tracker[user.id]))),
                ]
            )
            role_create_tracker[user.id].clear()
        except Exception:
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
    if not user or is_whitelisted(channel.guild.get_member(user.id) or user):
        return
    try:
        webhooks = await channel.webhooks()
        for w in webhooks:
            await w.delete()
        await channel.guild.ban(user, reason="Webhook Angriff")
        await security_log(
            channel.guild,
            "Webhook Angriff → Ban",
            f"{user.mention} hat einen Webhook erstellt und wurde gebannt.",
            fields=[
                ("User", f"{user} ({user.id})"),
                ("Kanal", channel.mention),
            ]
        )
    except Exception:
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
    if not actor or is_whitelisted(guild.get_member(actor.id) or actor):
        return

    now = datetime.utcnow()
    ban_tracker[actor.id] = [t for t in ban_tracker[actor.id] if now - t < timedelta(seconds=20)]
    ban_tracker[actor.id].append(now)

    if len(ban_tracker[actor.id]) >= 2:
        try:
            await guild.ban(actor, reason="Mass Ban (2+ Bans in 20s)")
            await security_log(
                guild,
                "Mass Ban → Ban",
                f"{actor.mention} hat 2+ Bans in 20s durchgeführt.",
                fields=[
                    ("User", f"{actor} ({actor.id})"),
                    ("Anzahl", str(len(ban_tracker[actor.id]))),
                ]
            )
        except Exception:
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
    if not actor or is_whitelisted(guild.get_member(actor.id) or actor):
        return

    now = datetime.utcnow()
    kick_tracker[actor.id] = [t for t in kick_tracker[actor.id] if now - t < timedelta(seconds=20)]
    kick_tracker[actor.id].append(now)

    if len(kick_tracker[actor.id]) >= 2:
        try:
            await guild.ban(actor, reason="Mass Kick (2+ Kicks in 20s)")
            await security_log(
                guild,
                "Mass Kick → Ban",
                f"{actor.mention} hat 2+ Kicks in 20s durchgeführt.",
                fields=[
                    ("User", f"{actor} ({actor.id})"),
                    ("Anzahl", str(len(kick_tracker[actor.id]))),
                ]
            )
        except Exception:
            pass


@bot.event
async def on_audit_log_entry_create(entry):
    if entry.guild.id != ALLOWED_GUILD_ID:
        return

    # Mass Timeout Schutz
    if entry.action == discord.AuditLogAction.member_update:
        actor = entry.user
        if not actor or is_whitelisted(entry.guild.get_member(actor.id) or actor):
            return
        changes = entry.changes
        after_changes = {c.key: c.new for c in changes.after} if hasattr(changes, 'after') else {}
        if "timed_out_until" in after_changes and after_changes["timed_out_until"] is not None:
            now = datetime.utcnow()
            timeout_tracker[actor.id] = [
                t for t in timeout_tracker[actor.id]
                if now - t < timedelta(seconds=15)
            ]
            timeout_tracker[actor.id].append(now)
            if len(timeout_tracker[actor.id]) >= 2:
                try:
                    await entry.guild.ban(actor, reason="Mass Timeout (2+ in 15s)")
                    await security_log(
                        entry.guild,
                        "Mass Timeout → Ban",
                        f"{actor.mention} hat 2+ Timeouts in 15s vergeben.",
                        fields=[
                            ("User", f"{actor} ({actor.id})"),
                            ("Anzahl", str(len(timeout_tracker[actor.id]))),
                        ]
                    )
                except Exception:
                    pass

    # Admin-Permission Schutz
    if entry.action == discord.AuditLogAction.role_update:
        actor = entry.user
        if not actor or is_whitelisted(entry.guild.get_member(actor.id) or actor):
            return
        role = entry.target
        if not role:
            return
        guild = entry.guild
        bot_member = guild.me
        if role.position >= bot_member.top_role.position:
            return
        changes = entry.changes
        after_perms = None
        if hasattr(changes, 'after'):
            for c in changes.after:
                if c.key == "permissions":
                    after_perms = c.new
                    break
        if after_perms and after_perms.administrator:
            try:
                new_perms = discord.Permissions(after_perms.value)
                new_perms.administrator = False
                await role.edit(permissions=new_perms, reason="Admin-Permission entfernt (Schutz)")
            except Exception:
                pass
            try:
                member = guild.get_member(actor.id)
                if member:
                    await member.kick(reason="Versuch Admin-Permission zu vergeben")
                    await security_log(
                        guild,
                        "Admin-Permission Versuch → Kick",
                        f"{actor.mention} hat versucht Admin-Rechte zu vergeben.",
                        fields=[
                            ("User", f"{actor} ({actor.id})"),
                            ("Rolle", role.name),
                        ]
                    )
            except Exception:
                pass

    # Server Update Log (Name / Icon)
    if entry.action == discord.AuditLogAction.guild_update:
        actor = entry.user
        if not actor or actor.bot:
            return
        await security_log(
            entry.guild,
            "Server wurde geändert",
            f"{actor.mention} hat Server-Einstellungen geändert.",
            color=discord.Color.orange(),
            fields=[
                ("User", f"{actor} ({actor.id})"),
            ]
        )

    # Bot hinzugefügt Log
    if entry.action == discord.AuditLogAction.bot_add:
        actor = entry.user
        bot_added = entry.target
        await security_log(
            entry.guild,
            "Bot hinzugefügt",
            f"{actor.mention} hat einen Bot zum Server hinzugefügt.",
            color=discord.Color.orange(),
            fields=[
                ("Hinzugefügt von", f"{actor} ({actor.id})"),
                ("Bot", f"{bot_added} ({bot_added.id})" if bot_added else "Unbekannt"),
            ]
        )

    # Role assigned log
    if entry.action == discord.AuditLogAction.member_role_update:
        actor = entry.user
        target = entry.target
        if not actor or actor.bot:
            return
        await security_log(
            entry.guild,
            "Rollen-Vergabe",
            f"{actor.mention} hat die Rollen von {target.mention if target else 'Unbekannt'} geändert.",
            color=discord.Color.blurple(),
            fields=[
                ("Verändert von", f"{actor} ({actor.id})"),
                ("Ziel", f"{target} ({target.id})" if target else "Unbekannt"),
            ]
        )

# =============================
# WHITELIST COMMANDS
# =============================

@bot.tree.command(
    name="whitelist_add",
    description="Fügt einen User zur Security-Whitelist hinzu",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def whitelist_add(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    SECURITY_WHITELIST_USERS.add(member.id)
    await interaction.response.send_message(f"✅ {member.mention} zur Whitelist hinzugefügt.", ephemeral=True)

@bot.tree.command(
    name="whitelist_remove",
    description="Entfernt einen User von der Security-Whitelist",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def whitelist_remove(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    SECURITY_WHITELIST_USERS.discard(member.id)
    await interaction.response.send_message(f"✅ {member.mention} von der Whitelist entfernt.", ephemeral=True)

@bot.tree.command(
    name="whitelist_list",
    description="Zeigt alle gewhitelisteten User",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def whitelist_list(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    if not SECURITY_WHITELIST_USERS:
        return await interaction.response.send_message("📋 Whitelist ist leer.", ephemeral=True)
    names = []
    for uid in SECURITY_WHITELIST_USERS:
        user = bot.get_user(uid)
        names.append(f"• {user} ({uid})" if user else f"• Unbekannt ({uid})")
    await interaction.response.send_message("📋 **Whitelist:**\n" + "\n".join(names), ephemeral=True)

# =============================
# LOCKDOWN COMMAND
# =============================

@bot.tree.command(
    name="lockdown",
    description="Sperrt oder entsperrt einen Kanal",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def lockdown(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)

    target = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)

    if overwrite.send_messages is False:
        # Unlock
        overwrite.send_messages = None
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔓 {target.mention} wurde entsperrt.", ephemeral=True)
        await target.send("🔓 Dieser Kanal wurde entsperrt.")
        await security_log(
            interaction.guild,
            "Lockdown aufgehoben",
            f"{interaction.user.mention} hat {target.mention} entsperrt.",
            color=discord.Color.green(),
            fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Kanal", target.mention)]
        )
    else:
        # Lock
        overwrite.send_messages = False
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔒 {target.mention} wurde gesperrt.", ephemeral=True)
        await target.send("🔒 Dieser Kanal wurde vorübergehend gesperrt.")
        await security_log(
            interaction.guild,
            "Lockdown aktiviert",
            f"{interaction.user.mention} hat {target.mention} gesperrt.",
            color=discord.Color.red(),
            fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Kanal", target.mention)]
        )

# =============================
# /SEND COMMAND
# =============================

@bot.tree.command(
    name="send",
    description="Sendet Nachricht",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def send_cmd(
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
            emb = discord.Embed(description=message, color=get_color(color))
            await channel.send(emb)
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
        await ctx.send("✅ Connected")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# =============================
# PERSISTENT VIEW SETUP
# =============================

@bot.event
async def setup_hook():
    bot.add_view(TicketButton())

# =============================
# START
# =============================

bot.run(TOKEN)
