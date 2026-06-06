import sqlite3
import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import os
import re

TOKEN = os.getenv("TOKEN")

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════

ALLOWED_GUILD_ID = 1512581389726388314

OWNERS = {
    1393725545853882509,
    1235586743991009372,
}

CALL_VOICE_CHANNEL_ID    = 1512776116438306816
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
ROLE_CMD_ALLOWED_ROLE_ID = 1512774843047870564

VOICE_ALWAYS_ON = True

# ═══════════════════════════════════════════════════════════
#  SECURITY CONFIG
# ═══════════════════════════════════════════════════════════

SPAM_MAX_MESSAGES = 5
SPAM_INTERVAL     = 3      # seconds
SPAM_TIMEOUT_SECS = 300    # 5 min timeout
MENTION_MAX       = 4
CREATE_MAX        = 3
CREATE_INTERVAL   = 15     # seconds

INVITE_PATTERN = re.compile(r"(discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE)

SECURITY_WHITELIST_USERS: set[int] = set()
SECURITY_WHITELIST_ROLES: set[int] = set()

# ═══════════════════════════════════════════════════════════
#  BOT SETUP
# ═══════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.members        = True
intents.guilds         = True
intents.message_content = True
intents.reactions      = True
intents.voice_states   = True
intents.guild_messages = True
intents.moderation     = True

bot = commands.Bot(command_prefix=["!", "?"], intents=intents)

# trackers
timeout_tracker        = defaultdict(list)
kick_tracker           = defaultdict(list)
ban_tracker            = defaultdict(list)
ticket_del_tracker     = defaultdict(list)
spam_tracker           = defaultdict(list)
channel_create_tracker = defaultdict(list)
role_create_tracker    = defaultdict(list)

counting_state = {"current": 0, "last_user": None, "delete_notice": None}
first_react_announced: set[int] = set()
ticket_counter = 0

# ═══════════════════════════════════════════════════════════
#  DATABASE  (invites + warns + counting persistence)
# ═══════════════════════════════════════════════════════════

_db  = sqlite3.connect("bot.db")
_cur = _db.cursor()

_cur.executescript("""
CREATE TABLE IF NOT EXISTS invites (
    guild_id INTEGER,
    user_id  INTEGER,
    invites  INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS warns (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    mod_id    INTEGER NOT NULL,
    reason    TEXT    NOT NULL,
    timestamp TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS counting (
    guild_id  INTEGER PRIMARY KEY,
    current   INTEGER DEFAULT 0,
    last_user INTEGER DEFAULT 0
);
""")
_db.commit()

# ── invite helpers ───────────────────────────────────────

def _add_invite(guild_id: int, user_id: int, amount: int = 1):
    _cur.execute("""
        INSERT INTO invites (guild_id, user_id, invites) VALUES (?,?,?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET invites = invites + ?
    """, (guild_id, user_id, amount, amount))
    _db.commit()

def _get_invites(guild_id: int, user_id: int) -> int:
    _cur.execute("SELECT invites FROM invites WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    row = _cur.fetchone()
    return row[0] if row else 0

def _set_invites(guild_id: int, user_id: int, amount: int):
    _cur.execute("""
        INSERT INTO invites (guild_id, user_id, invites) VALUES (?,?,?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET invites = ?
    """, (guild_id, user_id, amount, amount))
    _db.commit()

def _get_top(guild_id: int, limit: int = 10):
    _cur.execute("SELECT user_id, invites FROM invites WHERE guild_id=? ORDER BY invites DESC LIMIT ?", (guild_id, limit))
    return _cur.fetchall()

# ── warn helpers ─────────────────────────────────────────

def _add_warn(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    _cur.execute(
        "INSERT INTO warns (guild_id,user_id,mod_id,reason,timestamp) VALUES (?,?,?,?,?)",
        (guild_id, user_id, mod_id, reason, datetime.utcnow().isoformat())
    )
    _db.commit()
    return _cur.lastrowid

def _get_warns(guild_id: int, user_id: int):
    _cur.execute("SELECT id,mod_id,reason,timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id", (guild_id, user_id))
    return _cur.fetchall()

def _del_warn(warn_id: int, guild_id: int) -> bool:
    _cur.execute("DELETE FROM warns WHERE id=? AND guild_id=?", (warn_id, guild_id))
    _db.commit()
    return _cur.rowcount > 0

def _clear_warns(guild_id: int, user_id: int) -> int:
    _cur.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    _db.commit()
    return _cur.rowcount

# ── counting persistence ─────────────────────────────────

def _save_count(guild_id: int, current: int, last_user: int):
    _cur.execute("""
        INSERT INTO counting (guild_id, current, last_user) VALUES (?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET current=?, last_user=?
    """, (guild_id, current, last_user, current, last_user))
    _db.commit()

def _load_count(guild_id: int):
    _cur.execute("SELECT current, last_user FROM counting WHERE guild_id=?", (guild_id,))
    row = _cur.fetchone()
    return (row[0], row[1]) if row else (0, 0)

invite_cache: dict[int, dict[str, int]] = {}

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def is_owner(user_id: int) -> bool:
    return user_id in OWNERS

def can_moderate(member: discord.Member) -> bool:
    if member.id in OWNERS:
        return True
    return any(r.permissions.administrator or r.permissions.manage_messages for r in member.roles)

def can_use_role_cmd(member: discord.Member) -> bool:
    if member.id in OWNERS:
        return True
    return any(r.id == ROLE_CMD_ALLOWED_ROLE_ID for r in member.roles)

def is_whitelisted(member) -> bool:
    if not member:
        return False
    if getattr(member, "id", None) in OWNERS:
        return True
    if getattr(member, "id", None) in SECURITY_WHITELIST_USERS:
        return True
    if hasattr(member, "roles"):
        return any(r.id in SECURITY_WHITELIST_ROLES for r in member.roles)
    return False

def is_new_account(user: discord.User, days: int = 7) -> bool:
    return (datetime.utcnow() - user.created_at.replace(tzinfo=None)) < timedelta(days=days)

def get_color(color: str) -> discord.Color:
    return discord.Color.from_rgb(255, 255, 255) if color == "white" else discord.Color.from_rgb(0, 0, 0)

def eval_math_expression(expr: str):
    try:
        expr = expr.strip()
        if not all(c in "0123456789+-*/(). " for c in expr):
            return None
        result = eval(expr, {"__builtins__": {}}, {})
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            return int(result) if result == int(result) else None
    except Exception:
        pass
    return None

async def get_latest_audit(guild: discord.Guild, action):
    try:
        return await guild.audit_logs(limit=1, action=action).__anext__()
    except Exception:
        return None

async def security_log(
    guild: discord.Guild,
    title: str,
    description: str,
    color: discord.Color = discord.Color.red(),
    fields: list | None = None,
):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title=f"🔒 {title}",
        description=description,
        color=color,
        timestamp=datetime.utcnow(),
    )
    for name, value in (fields or []):
        embed.add_field(name=name, value=str(value)[:1024], inline=True)
    embed.set_footer(text="Security System")
    try:
        await channel.send(embed=embed)
    except Exception:
        pass

async def _reply_and_clean(ctx, text: str, delay: float = 4.0):
    """Sends a temporary reply that deletes itself and the command."""
    msg = await ctx.send(text)
    await asyncio.sleep(delay)
    for m in (ctx.message, msg):
        try:
            await m.delete()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
#  READY
# ═══════════════════════════════════════════════════════════

async def setup_hook():
    bot.add_view(TicketButton())

bot.setup_hook = setup_hook

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")
    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
    except Exception:
        pass

    asyncio.create_task(voice_keep_alive())
    asyncio.create_task(cleanup_trackers())

    # load counting state from db
    for guild in bot.guilds:
        current, last_user = _load_count(guild.id)
        counting_state["current"]   = current
        counting_state["last_user"] = last_user if last_user else None

    # cache invites
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
#  TRACKER CLEANUP
# ═══════════════════════════════════════════════════════════

async def cleanup_trackers():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(60)
        now = datetime.utcnow()
        for tracker, window in [
            (timeout_tracker,        15),
            (kick_tracker,           20),
            (ban_tracker,            20),
            (spam_tracker,           SPAM_INTERVAL),
            (channel_create_tracker, CREATE_INTERVAL),
            (role_create_tracker,    CREATE_INTERVAL),
        ]:
            dead = [uid for uid, times in tracker.items()
                    if not [t for t in times if now - t < timedelta(seconds=window)]]
            for uid in dead:
                del tracker[uid]

# ═══════════════════════════════════════════════════════════
#  VOICE KEEP-ALIVE
# ═══════════════════════════════════════════════════════════

async def voice_keep_alive():
    await bot.wait_until_ready()
    while VOICE_ALWAYS_ON:
        try:
            channel = bot.get_channel(CALL_VOICE_CHANNEL_ID)
            if channel:
                vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
                if vc is None:
                    try:
                        await channel.connect()
                    except Exception:
                        pass
                elif not vc.is_connected():
                    try:
                        await vc.disconnect()
                    except Exception:
                        pass
                    try:
                        await channel.connect()
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(20)

# ═══════════════════════════════════════════════════════════
#  WELCOME / AUTO-ROLE
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    # new account warning
    if is_new_account(member, days=7):
        await security_log(
            member.guild,
            "⚠️ Neuer Account beigetreten",
            f"{member.mention} hat einen Account der jünger als 7 Tage ist.",
            color=discord.Color.orange(),
            fields=[
                ("User",             f"{member} ({member.id})"),
                ("Account erstellt", f"<t:{int(member.created_at.timestamp())}:R>"),
            ],
        )

    # auto role
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Auto-Rolle")
        except Exception:
            pass

    # welcome embed
    welcome_channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        try:
            embed = discord.Embed(
                description=(
                    f"Hey {member.mention},\n\n"
                    f"Wir freuen uns dich im **7zarnova** Server begrüßen zu dürfen!\n"
                    f"Bitte beachte unser <#{RULES_CHANNEL_ID}>!\n\n"
                    f"• Sei nett\n"
                    f"• Viel Spaß!"
                ),
                color=discord.Color.from_rgb(149, 165, 166),
            )
            await welcome_channel.send(embed=embed)
        except Exception:
            pass

    # invite tracking
    try:
        new_invites = await member.guild.invites()
        old_cache   = invite_cache.get(member.guild.id, {})
        used_invite = next(
            (inv for inv in new_invites if inv.uses > old_cache.get(inv.code, 0)),
            None,
        )
        invite_cache[member.guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used_invite and used_invite.inviter:
            _add_invite(member.guild.id, used_invite.inviter.id, 1)
            total      = _get_invites(member.guild.id, used_invite.inviter.id)
            invite_ch  = member.guild.get_channel(INVITE_CHANNEL_ID)
            if invite_ch:
                embed = discord.Embed(
                    description=(
                        f"**{member.mention}** ist beigetreten. "
                        f"Eingeladen von **{used_invite.inviter.name}** – "
                        f"jetzt **{total} Invites**!"
                    ),
                    color=discord.Color.from_rgb(149, 165, 166),
                )
                await invite_ch.send(embed=embed)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════
#  BOOST / ROLE-TRIGGER
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild.id != ALLOWED_GUILD_ID:
        return

    if not before.premium_since and after.premium_since:
        ch = after.guild.get_channel(BOOST_CHANNEL_ID)
        if ch:
            try:
                await ch.send("danke 🫶🏻!")
            except Exception:
                pass

    before_ids = {r.id for r in before.roles}
    after_ids  = {r.id for r in after.roles}
    if TRIGGER_ROLE_ID in after_ids and TRIGGER_ROLE_ID not in before_ids:
        for extra_id in (EXTRA_ROLE_ID_1, EXTRA_ROLE_ID_2):
            extra = after.guild.get_role(extra_id)
            if extra:
                try:
                    await after.add_roles(extra, reason="Trigger-Rolle")
                except Exception:
                    pass

# ═══════════════════════════════════════════════════════════
#  MESSAGES  (anti-spam + auto-react + counting)
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    guild = message.guild
    if not guild or guild.id != ALLOWED_GUILD_ID:
        await bot.process_commands(message)
        return

    # ── anti-spam ────────────────────────────────────────
    if not is_whitelisted(message.author):
        now = datetime.utcnow()

        # message spam
        spam_tracker[message.author.id].append(now)
        spam_tracker[message.author.id] = [
            t for t in spam_tracker[message.author.id]
            if now - t < timedelta(seconds=SPAM_INTERVAL)
        ]
        if len(spam_tracker[message.author.id]) >= SPAM_MAX_MESSAGES:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                await message.author.timeout(until, reason="Auto-Timeout: Spam")
                await message.channel.send(
                    f"⏱️ {message.author.mention} wurde für 5 Minuten getimeoutet (Spam).",
                    delete_after=5,
                )
                spam_tracker[message.author.id].clear()
                await security_log(guild, "Anti-Spam: Timeout",
                    f"{message.author.mention} wurde automatisch getimeoutet.",
                    color=discord.Color.orange(),
                    fields=[("User", f"{message.author} ({message.author.id})"),
                            ("Kanal", message.channel.mention), ("Dauer", "5 Minuten")])
            except Exception:
                pass
            return

        # mention spam
        total_mentions = len(message.mentions) + len(message.role_mentions)
        if total_mentions >= MENTION_MAX:
            try:
                await message.delete()
                until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                await message.author.timeout(until, reason="Auto-Timeout: Mention-Spam")
                await message.channel.send(
                    f"🚫 {message.author.mention} wurde für 5 Minuten getimeoutet (Mention-Spam).",
                    delete_after=5,
                )
                await security_log(guild, "Anti-Spam: Mention-Spam",
                    f"{message.author.mention} hat {total_mentions} Mentions gesendet.",
                    color=discord.Color.orange(),
                    fields=[("User", f"{message.author} ({message.author.id})"),
                            ("Kanal", message.channel.mention), ("Mentions", total_mentions)])
            except Exception:
                pass
            return

        # invite filter
        if INVITE_PATTERN.search(message.content):
            try:
                await message.delete()
                await message.channel.send(
                    f"🔗 {message.author.mention} Discord-Einladungen sind hier nicht erlaubt!",
                    delete_after=5,
                )
                await security_log(guild, "Invite-Link geblockt",
                    f"{message.author.mention} hat einen Invite-Link gesendet.",
                    color=discord.Color.orange(),
                    fields=[("User", f"{message.author} ({message.author.id})"),
                            ("Kanal", message.channel.mention)])
            except Exception:
                pass
            return

    # ── auto-react ────────────────────────────────────────
    if message.channel.id in AUTO_REACT_CHANNEL_IDS:
        emoji = "✅" if message.channel.id == 1512774955413147648 else "✔️"
        try:
            await message.add_reaction(emoji)
        except Exception:
            pass

    # ── counting ──────────────────────────────────────────
    if COUNTING_CHANNEL_ID and message.channel.id == COUNTING_CHANNEL_ID:
        await handle_counting(message)
        return

    await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════
#  MESSAGE EDIT / DELETE LOGS
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not after.guild or after.guild.id != ALLOWED_GUILD_ID:
        return
    if after.author.bot or before.content == after.content:
        return
    await security_log(after.guild, "Nachricht bearbeitet",
        f"{after.author.mention} hat eine Nachricht bearbeitet.",
        color=discord.Color.blurple(),
        fields=[
            ("User",    f"{after.author} ({after.author.id})"),
            ("Kanal",   after.channel.mention),
            ("Vorher",  before.content[:300] or "*(leer)*"),
            ("Nachher", after.content[:300] or "*(leer)*"),
        ])

@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild or message.guild.id != ALLOWED_GUILD_ID:
        return

    # counting notice
    if COUNTING_CHANNEL_ID and message.channel.id == COUNTING_CHANNEL_ID:
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

    await security_log(message.guild, "Nachricht gelöscht",
        f"Eine Nachricht von {message.author.mention} wurde gelöscht.",
        color=discord.Color.dark_gray(),
        fields=[
            ("User",   f"{message.author} ({message.author.id})"),
            ("Kanal",  message.channel.mention),
            ("Inhalt", message.content[:400] or "*(kein Text / Anhang)*"),
        ])

# ═══════════════════════════════════════════════════════════
#  COUNTING SYSTEM  (persistent)
# ═══════════════════════════════════════════════════════════

async def handle_counting(message: discord.Message):
    content  = message.content.strip()
    expected = counting_state["current"] + 1

    value = int(content) if content.lstrip("-").isdigit() else eval_math_expression(content)
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
            n = await message.channel.send(
                f"❌ {message.author.mention} Du kannst nicht zweimal hintereinander zählen!"
            )
            await asyncio.sleep(1.5)
            await n.delete()
        except Exception:
            pass
        return

    if value == expected:
        counting_state["current"]   = expected
        counting_state["last_user"] = message.author.id
        _save_count(message.guild.id, expected, message.author.id)
        if counting_state["delete_notice"]:
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
            n = await message.channel.send(f"❌ Das stimmt nicht! Die nächste Zahl ist **{expected}**.")
            await asyncio.sleep(1.5)
            await n.delete()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
#  FIRST REACTOR
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
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

# ═══════════════════════════════════════════════════════════
#  VOICE STATE LOG
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if not member.guild or member.guild.id != ALLOWED_GUILD_ID or member.bot:
        return
    if before.channel is None and after.channel is not None:
        await security_log(member.guild, "Voice: Beigetreten",
            f"{member.mention} ist einem Voice-Kanal beigetreten.",
            color=discord.Color.green(),
            fields=[("User", f"{member} ({member.id})"), ("Kanal", after.channel.name)])
    elif before.channel is not None and after.channel is None:
        await security_log(member.guild, "Voice: Verlassen",
            f"{member.mention} hat einen Voice-Kanal verlassen.",
            color=discord.Color.dark_green(),
            fields=[("User", f"{member} ({member.id})"), ("Kanal", before.channel.name)])
    elif before.channel != after.channel:
        await security_log(member.guild, "Voice: Gewechselt",
            f"{member.mention} hat den Voice-Kanal gewechselt.",
            color=discord.Color.blurple(),
            fields=[("User", f"{member} ({member.id})"), ("Von", before.channel.name), ("Nach", after.channel.name)])

# ═══════════════════════════════════════════════════════════
#  TICKET SYSTEM  (with close button + transcript)
# ═══════════════════════════════════════════════════════════

def is_ticket_channel(channel: discord.TextChannel) -> bool:
    return channel.category_id == TICKET_CATEGORY_ID and channel.name.startswith("ticket-")

def can_manage_ticket(member: discord.Member) -> bool:
    if member.id in OWNERS:
        return True
    return any(r.id == SUPPORT_ROLE_ID or r.permissions.administrator for r in member.roles)

async def _generate_transcript(channel: discord.TextChannel) -> discord.File:
    lines = []
    async for msg in channel.history(limit=500, oldest_first=True):
        ts = msg.created_at.strftime("%d.%m.%Y %H:%M")
        lines.append(f"[{ts}] {msg.author} ({msg.author.id}): {msg.content}")
        for att in msg.attachments:
            lines.append(f"[{ts}] {msg.author}: [Anhang: {att.url}]")
    content = "\n".join(lines).encode("utf-8")
    import io
    return discord.File(io.BytesIO(content), filename=f"transcript-{channel.name}.txt")

class TicketCloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket schließen", emoji="🔒", style=discord.ButtonStyle.red, custom_id="ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: Button):
        if not can_manage_ticket(interaction.user):
            return await interaction.response.send_message("❌ Kein Zugriff.", ephemeral=True)
        await interaction.response.send_message("🔒 Ticket wird geschlossen...")
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role, read_messages=False, send_messages=False)
        except Exception as e:
            await interaction.channel.send(f"❌ Fehler: {e}")

    @discord.ui.button(label="Transcript & Löschen", emoji="🗑️", style=discord.ButtonStyle.gray, custom_id="ticket_delete_btn")
    async def delete_btn(self, interaction: discord.Interaction, button: Button):
        if not can_manage_ticket(interaction.user):
            return await interaction.response.send_message("❌ Kein Zugriff.", ephemeral=True)
        await interaction.response.send_message("📄 Erstelle Transcript und lösche Ticket...")
        try:
            transcript = await _generate_transcript(interaction.channel)
            log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_ch:
                await log_ch.send(
                    content=f"📄 Transcript von **{interaction.channel.name}** (gelöscht von {interaction.user.mention})",
                    file=transcript,
                )
        except Exception:
            pass
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete(reason=f"Ticket gelöscht von {interaction.user}")
        except Exception:
            pass

class TicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket erstellen", emoji="📧", style=discord.ButtonStyle.blurple, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        global ticket_counter
        guild    = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        # check existing ticket
        if category:
            for ch in category.text_channels:
                if ch.name.startswith("ticket-"):
                    ow = ch.overwrites_for(interaction.user)
                    if ow.read_messages:
                        return await interaction.response.send_message(
                            f"❌ Du hast bereits ein offenes Ticket: {ch.mention}", ephemeral=True
                        )

        ticket_counter += 1
        support_role = guild.get_role(SUPPORT_ROLE_ID)
        overwrites   = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        for r in guild.roles:
            if r.permissions.administrator and r not in overwrites:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{ticket_counter}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket von {interaction.user}",
            )
            embed = discord.Embed(
                title="Ticket erstellt 🎟️",
                description=(
                    "Beschreibe dein Anliegen so genau wie möglich.\n"
                    "Unser Team kümmert sich so schnell wie möglich – danke für deine Geduld!"
                ),
                color=discord.Color.from_rgb(149, 165, 166),
            )
            pings = f"{support_role.mention} {interaction.user.mention}" if support_role else interaction.user.mention
            await ticket_channel.send(content=pings, embed=embed, view=TicketCloseView())
            await interaction.response.send_message(f"✅ Dein Ticket: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)


@bot.tree.command(name="ticketpanel", description="Sendet das Ticket-Panel", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def ticketpanel(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    channel = interaction.guild.get_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Kanal nicht gefunden.", ephemeral=True)
    embed = discord.Embed(
        title="Ticket erstellen 📧",
        description="Klicke unten, um ein Ticket zu öffnen.\nBleib höflich – wir supporten dich so schnell es geht!",
        color=discord.Color.from_rgb(149, 165, 166),
    )
    try:
        await channel.send(embed=embed, view=TicketButton())
        await interaction.response.send_message("✅ Panel gesendet!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)


@bot.command()
async def close(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID or not is_ticket_channel(ctx.channel):
        return
    if not can_manage_ticket(ctx.author):
        return await ctx.send("❌ Kein Zugriff.")
    await ctx.send("🔒 Ticket wird geschlossen...")
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, read_messages=False, send_messages=False)
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")


@bot.command(name="delete")
async def delete_ticket(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID or not is_ticket_channel(ctx.channel):
        return
    if not can_manage_ticket(ctx.author):
        return await ctx.send("❌ Kein Zugriff.")

    if ctx.author.id not in OWNERS:
        now = datetime.utcnow()
        ticket_del_tracker[ctx.author.id] = [
            t for t in ticket_del_tracker[ctx.author.id]
            if now - t < timedelta(seconds=30)
        ]
        if len(ticket_del_tracker[ctx.author.id]) >= 3:
            return await ctx.send("❌ Maximal 3 Tickets in 30 Sekunden löschen.", delete_after=5)
        ticket_del_tracker[ctx.author.id].append(now)

    try:
        transcript = await _generate_transcript(ctx.channel)
        log_ch = ctx.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            await log_ch.send(
                content=f"📄 Transcript von **{ctx.channel.name}** (gelöscht von {ctx.author.mention})",
                file=transcript,
            )
    except Exception:
        pass
    await asyncio.sleep(1)
    try:
        await ctx.channel.delete(reason=f"Ticket gelöscht von {ctx.author}")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# ═══════════════════════════════════════════════════════════
#  MODERATION COMMANDS
# ═══════════════════════════════════════════════════════════

@bot.command()
async def kick(ctx: commands.Context, member: discord.Member = None, *, reason: str = "Kein Grund angegeben"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if member is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?kick @user [Grund]`")
    if member.id in OWNERS:
        return await _reply_and_clean(ctx, "❌ Owner können nicht gekickt werden.")
    if member.top_role >= ctx.guild.me.top_role:
        return await _reply_and_clean(ctx, "❌ Diese Person hat eine höhere Rolle als ich.")
    try:
        await member.kick(reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(
            title="👢 Kick",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User",   value=f"{member} ({member.id})")
        embed.add_field(name="Mod",    value=f"{ctx.author}")
        embed.add_field(name="Grund",  value=reason)
        await ctx.send(embed=embed)
        await security_log(ctx.guild, "Kick", f"{member.mention} wurde von {ctx.author.mention} gekickt.",
            color=discord.Color.orange(),
            fields=[("User", f"{member} ({member.id})"), ("Mod", str(ctx.author)), ("Grund", reason)])
    except discord.Forbidden:
        await ctx.send("❌ Keine Berechtigung.")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")


@bot.command()
async def ban(ctx: commands.Context, member: discord.Member = None, *, reason: str = "Kein Grund angegeben"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if member is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?ban @user [Grund]`")
    if member.id in OWNERS:
        return await _reply_and_clean(ctx, "❌ Owner können nicht gebannt werden.")
    if member.top_role >= ctx.guild.me.top_role:
        return await _reply_and_clean(ctx, "❌ Diese Person hat eine höhere Rolle als ich.")
    try:
        await member.ban(reason=f"{ctx.author}: {reason}", delete_message_days=1)
        embed = discord.Embed(title="🔨 Ban", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User",  value=f"{member} ({member.id})")
        embed.add_field(name="Mod",   value=f"{ctx.author}")
        embed.add_field(name="Grund", value=reason)
        await ctx.send(embed=embed)
        await security_log(ctx.guild, "Ban", f"{member.mention} wurde von {ctx.author.mention} gebannt.",
            fields=[("User", f"{member} ({member.id})"), ("Mod", str(ctx.author)), ("Grund", reason)])
    except discord.Forbidden:
        await ctx.send("❌ Keine Berechtigung.")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")


@bot.command()
async def unban(ctx: commands.Context, user_id: str = None, *, reason: str = "Kein Grund angegeben"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if user_id is None or not user_id.isdigit():
        return await _reply_and_clean(ctx, "❌ Verwendung: `?unban <UserID> [Grund]`")
    try:
        user = await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(title="✅ Unban", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="User",  value=f"{user} ({user.id})")
        embed.add_field(name="Mod",   value=f"{ctx.author}")
        embed.add_field(name="Grund", value=reason)
        await ctx.send(embed=embed)
        await security_log(ctx.guild, "Unban", f"{user.mention} wurde von {ctx.author.mention} entbannt.",
            color=discord.Color.green(),
            fields=[("User", f"{user} ({user.id})"), ("Mod", str(ctx.author)), ("Grund", reason)])
    except discord.NotFound:
        await ctx.send("❌ User nicht gefunden oder nicht gebannt.")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")


@bot.command()
async def timeout(ctx: commands.Context, member: discord.Member = None, duration: str = None, *, reason: str = "Kein Grund angegeben"):
    """Beispiel: ?timeout @user 10m Spam  |  Einheiten: s m h d"""
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if member is None or duration is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?timeout @user <Zeit> [Grund]`\nEinheiten: `s` `m` `h` `d`")

    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit  = duration[-1].lower()
    if unit not in units or not duration[:-1].isdigit():
        return await _reply_and_clean(ctx, "❌ Ungültige Zeit. Beispiel: `10m`, `2h`, `1d`")

    seconds = int(duration[:-1]) * units[unit]
    if seconds > 2419200:
        return await _reply_and_clean(ctx, "❌ Maximale Timeout-Dauer ist 28 Tage.")

    try:
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(title="⏱️ Timeout", color=discord.Color.orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",  value=f"{member} ({member.id})")
        embed.add_field(name="Dauer", value=duration)
        embed.add_field(name="Grund", value=reason)
        embed.add_field(name="Mod",   value=str(ctx.author))
        await ctx.send(embed=embed)
        await security_log(ctx.guild, "Timeout",
            f"{member.mention} wurde von {ctx.author.mention} getimeoutet.",
            color=discord.Color.orange(),
            fields=[("User", f"{member} ({member.id})"), ("Dauer", duration), ("Grund", reason)])
    except discord.Forbidden:
        await ctx.send("❌ Keine Berechtigung.")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# ═══════════════════════════════════════════════════════════
#  WARN SYSTEM
# ═══════════════════════════════════════════════════════════

@bot.command()
async def warn(ctx: commands.Context, member: discord.Member = None, *, reason: str = "Kein Grund angegeben"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if member is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?warn @user [Grund]`")

    warn_id = _add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    warns   = _get_warns(ctx.guild.id, member.id)

    embed = discord.Embed(title="⚠️ Verwarnung", color=discord.Color.yellow(), timestamp=datetime.utcnow())
    embed.add_field(name="User",          value=f"{member} ({member.id})")
    embed.add_field(name="Mod",           value=str(ctx.author))
    embed.add_field(name="Grund",         value=reason)
    embed.add_field(name="Warn ID",       value=f"#{warn_id}")
    embed.add_field(name="Total Warns",   value=str(len(warns)))
    await ctx.send(embed=embed)

    # try to DM
    try:
        dm_embed = discord.Embed(
            title=f"⚠️ Du wurdest auf **{ctx.guild.name}** verwarnt",
            description=f"**Grund:** {reason}\n**Warn #{warn_id}** | Gesamt: {len(warns)}",
            color=discord.Color.yellow(),
            timestamp=datetime.utcnow(),
        )
        await member.send(embed=dm_embed)
    except Exception:
        pass

    await security_log(ctx.guild, "Verwarnung",
        f"{member.mention} wurde von {ctx.author.mention} verwarnt.",
        color=discord.Color.yellow(),
        fields=[("User", f"{member} ({member.id})"), ("Grund", reason),
                ("Warn ID", f"#{warn_id}"), ("Total", len(warns))])


@bot.command()
async def warns(ctx: commands.Context, member: discord.Member = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if member is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?warns @user`")

    warn_list = _get_warns(ctx.guild.id, member.id)
    embed = discord.Embed(
        title=f"⚠️ Verwarnungen von {member}",
        color=discord.Color.yellow(),
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if not warn_list:
        embed.description = "Keine Verwarnungen."
    else:
        for w_id, mod_id, reason, ts in warn_list:
            mod = ctx.guild.get_member(mod_id)
            mod_str = str(mod) if mod else f"ID:{mod_id}"
            date_str = ts[:10]
            embed.add_field(
                name=f"Warn #{w_id} – {date_str}",
                value=f"**Grund:** {reason}\n**Mod:** {mod_str}",
                inline=False,
            )
    await ctx.send(embed=embed)


@bot.command()
async def clearwarn(ctx: commands.Context, warn_id: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if warn_id is None or not warn_id.isdigit():
        return await _reply_and_clean(ctx, "❌ Verwendung: `?clearwarn <WarnID>`")
    if _del_warn(int(warn_id), ctx.guild.id):
        await ctx.send(f"✅ Verwarnung **#{warn_id}** wurde gelöscht.", delete_after=5)
    else:
        await ctx.send(f"❌ Verwarnung **#{warn_id}** nicht gefunden.", delete_after=5)


@bot.command()
async def clearwarns(ctx: commands.Context, member: discord.Member = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if member is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?clearwarns @user`")
    count = _clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"✅ **{count}** Verwarnungen von {member.mention} gelöscht.", delete_after=5)

# ═══════════════════════════════════════════════════════════
#  USERINFO / SERVERINFO / AVATAR
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="userinfo", description="Zeigt Infos über einen User", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles  = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]

    embed = discord.Embed(
        title=f"👤 {member}",
        color=member.color if member.color.value else discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID",              value=member.id,                                              inline=True)
    embed.add_field(name="Nickname",        value=member.nick or "–",                                    inline=True)
    embed.add_field(name="Bot",             value="✅" if member.bot else "❌",                           inline=True)
    embed.add_field(name="Account erstellt", value=f"<t:{int(member.created_at.timestamp())}:R>",        inline=True)
    embed.add_field(name="Beigetreten",     value=f"<t:{int(member.joined_at.timestamp())}:R>",          inline=True)
    embed.add_field(name="Boosting",        value=f"<t:{int(member.premium_since.timestamp())}:R>" if member.premium_since else "❌", inline=True)
    embed.add_field(name=f"Rollen ({len(roles)})", value=" ".join(roles[:20]) or "–", inline=False)
    embed.set_footer(text=f"Angefragt von {interaction.user}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="Zeigt Infos über den Server", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(
        title=f"🏠 {g.name}",
        color=discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="ID",          value=g.id,                                              inline=True)
    embed.add_field(name="Owner",       value=f"<@{g.owner_id}>",                               inline=True)
    embed.add_field(name="Erstellt",    value=f"<t:{int(g.created_at.timestamp())}:R>",         inline=True)
    embed.add_field(name="Mitglieder",  value=g.member_count,                                   inline=True)
    embed.add_field(name="Rollen",      value=len(g.roles),                                     inline=True)
    embed.add_field(name="Kanäle",      value=len(g.channels),                                  inline=True)
    embed.add_field(name="Boosts",      value=g.premium_subscription_count,                     inline=True)
    embed.add_field(name="Boost Level", value=g.premium_tier,                                   inline=True)
    embed.add_field(name="Verifizierung", value=str(g.verification_level),                      inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="Zeigt den Avatar eines Users", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed  = discord.Embed(title=f"🖼️ Avatar von {member}", color=discord.Color.from_rgb(149, 165, 166))
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════
#  PURGE
# ═══════════════════════════════════════════════════════════

@bot.command()
async def purge(ctx: commands.Context, amount: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    try:
        await ctx.message.delete()
    except Exception:
        pass
    if amount is None:
        return await ctx.send("❌ Verwendung: `?purge all` oder `?purge <Anzahl>`", delete_after=3)

    if amount.lower() == "all":
        deleted = await ctx.channel.purge(limit=None)
    else:
        if not amount.isdigit() or int(amount) < 1:
            return await ctx.send("❌ Ungültige Anzahl.", delete_after=3)
        deleted = await ctx.channel.purge(limit=int(amount))

    note = await ctx.send(f"🗑️ {len(deleted)} Nachrichten gelöscht.")
    await asyncio.sleep(3)
    try:
        await note.delete()
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════
#  ROLE COMMAND  (Carl-bot style)
# ═══════════════════════════════════════════════════════════

def _find_role(guild: discord.Guild, query: str) -> list[discord.Role]:
    """Returns list of matching roles (ID → exact name → partial name)."""
    query = query.strip()
    if query.isdigit():
        r = guild.get_role(int(query))
        return [r] if r else []
    exact = [r for r in guild.roles if r.name.lower() == query.lower()]
    if exact:
        return exact
    return [r for r in guild.roles if query.lower() in r.name.lower()]

@bot.command(name="role")
async def role_cmd(ctx: commands.Context, member: discord.Member = None, *, role_input: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_use_role_cmd(ctx.author):
        return await _reply_and_clean(ctx, "❌ Du hast keine Berechtigung für diesen Command.")
    if member is None or role_input is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?role @user <Rollenname oder ID>`")

    matches = _find_role(ctx.guild, role_input)

    if not matches:
        return await _reply_and_clean(ctx, f"❌ Keine Rolle mit **{role_input}** gefunden.")
    if len(matches) > 1:
        names = ", ".join(f"`{r.name}`" for r in matches[:8])
        return await _reply_and_clean(ctx, f"⚠️ Mehrere Rollen gefunden: {names} – bitte genauer angeben.", delay=6)

    role = matches[0]

    if role >= ctx.guild.me.top_role:
        return await _reply_and_clean(ctx, "❌ Diese Rolle ist gleich hoch oder höher als meine eigene.")
    if role.permissions.administrator and ctx.author.id not in OWNERS:
        return await _reply_and_clean(ctx, "❌ Admin-Rollen können nur von Owners vergeben werden.")

    try:
        if role in member.roles:
            await member.remove_roles(role, reason=f"?role von {ctx.author}")
            action = "entfernt"
            color  = discord.Color.red()
            emoji  = "➖"
        else:
            await member.add_roles(role, reason=f"?role von {ctx.author}")
            action = "hinzugefügt"
            color  = discord.Color.green()
            emoji  = "➕"

        embed = discord.Embed(color=color, timestamp=datetime.utcnow())
        embed.description = f"{emoji} Rolle **{role.name}** wurde {member.mention} **{action}**."
        embed.add_field(name="Rolle", value=f"{role.mention} ({role.id})")
        embed.add_field(name="User",  value=f"{member} ({member.id})")
        embed.set_footer(text=f"Ausgeführt von {ctx.author} • {ctx.author.id}")
        await ctx.send(embed=embed)

        await security_log(ctx.guild, "?role verwendet",
            f"{ctx.author.mention} hat die Rolle **{role.name}** bei {member.mention} {action}.",
            color=discord.Color.blurple(),
            fields=[("Mod",   f"{ctx.author} ({ctx.author.id})"),
                    ("User",  f"{member} ({member.id})"),
                    ("Rolle", f"{role.name} ({role.id})")])

    except discord.Forbidden:
        await ctx.send("❌ Keine Berechtigung für diese Rolle.")
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# ═══════════════════════════════════════════════════════════
#  COUNTING SETCOUNT
# ═══════════════════════════════════════════════════════════

@bot.command()
async def setcount(ctx: commands.Context, number: int = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not is_owner(ctx.author.id):
        return await _reply_and_clean(ctx, "❌ Kein Zugriff.")
    if number is None:
        return await _reply_and_clean(ctx, "❌ Verwendung: `?setcount <Zahl>`")
    counting_state["current"]   = number
    counting_state["last_user"] = None
    _save_count(ctx.guild.id, number, 0)
    await ctx.send(f"✅ Zähler wurde auf **{number}** gesetzt.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════
#  INVITES SLASH COMMANDS
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="invite", description="Zeigt die Invite-Anzahl eines Users", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def invite_cmd(interaction: discord.Interaction, member: discord.Member):
    count = _get_invites(interaction.guild.id, member.id)
    embed = discord.Embed(
        description=f"📨 **{member.name}** hat **{count} Invites**",
        color=discord.Color.from_rgb(149, 165, 166),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="invites_set", description="Setzt die Invite-Anzahl eines Users manuell", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def invites_set_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    _set_invites(interaction.guild.id, member.id, amount)
    await interaction.response.send_message(f"✅ Invites von {member.mention} auf **{amount}** gesetzt.", ephemeral=True)


@bot.tree.command(name="leaderboard", description="Zeigt das Invite-Leaderboard", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def leaderboard_cmd(interaction: discord.Interaction):
    top = _get_top(interaction.guild.id)
    if not top:
        return await interaction.response.send_message("Noch keine Invites gespeichert.", ephemeral=True)
    embed = discord.Embed(title="🏆 Invite Leaderboard", color=discord.Color.from_rgb(149, 165, 166))
    for i, (user_id, count) in enumerate(top, start=1):
        user = bot.get_user(user_id)
        name = user.name if user else f"User {user_id}"
        embed.add_field(name=f"{i}. {name}", value=f"📨 {count} Invites", inline=False)
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════
#  SECURITY SYSTEM
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    # save channel data BEFORE audit log lookup
    saved = {
        "name":      channel.name,
        "type":      channel.type,
        "category":  channel.category,
        "position":  channel.position,
        "overwrites": channel.overwrites,
        "topic":     getattr(channel, "topic", None),
        "nsfw":      getattr(channel, "nsfw", False),
        "slowmode":  getattr(channel, "slowmode_delay", 0),
    }

    await asyncio.sleep(0.3)
    entry = await get_latest_audit(channel.guild, discord.AuditLogAction.channel_delete)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(channel.guild.get_member(user.id) or user):
        return

    # ban
    try:
        await channel.guild.ban(user, reason="Channel Delete – Auto-Schutz")
        await security_log(channel.guild, "Channel gelöscht → Ban",
            f"{user.mention} hat **#{saved['name']}** gelöscht und wurde gebannt.",
            fields=[("User", f"{user} ({user.id})"), ("Channel", saved["name"])])
    except Exception:
        pass

    # restore channel
    try:
        kwargs = dict(
            name=saved["name"],
            overwrites=saved["overwrites"],
            category=saved["category"],
            position=saved["position"],
            reason="Auto-Wiederherstellung (Schutz)",
        )
        if saved["type"] == discord.ChannelType.text:
            if saved["topic"]:
                kwargs["topic"] = saved["topic"]
            kwargs["nsfw"]       = saved["nsfw"]
            kwargs["slowmode_delay"] = saved["slowmode"]
            restored = await channel.guild.create_text_channel(**kwargs)
        elif saved["type"] == discord.ChannelType.voice:
            restored = await channel.guild.create_voice_channel(**kwargs)
        else:
            restored = await channel.guild.create_text_channel(**kwargs)

        await security_log(channel.guild, "Channel wiederhergestellt",
            f"Channel **#{saved['name']}** wurde automatisch wiederhergestellt.",
            color=discord.Color.green(),
            fields=[("Channel", restored.mention)])
    except Exception:
        pass


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return
    await asyncio.sleep(0.3)
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
            await channel.guild.ban(user, reason=f"Channel-Create-Spam ({CREATE_MAX}+ in {CREATE_INTERVAL}s)")
            await security_log(channel.guild, "Channel Create Spam → Ban",
                f"{user.mention} hat {len(channel_create_tracker[user.id])} Channels in {CREATE_INTERVAL}s erstellt.",
                fields=[("User", f"{user} ({user.id})")])
            channel_create_tracker[user.id].clear()
        except Exception:
            pass


@bot.event
async def on_guild_role_delete(role: discord.Role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return

    saved = {
        "name":        role.name,
        "color":       role.color,
        "permissions": role.permissions,
        "hoist":       role.hoist,
        "mentionable": role.mentionable,
        "position":    role.position,
    }

    await asyncio.sleep(0.3)
    entry = await get_latest_audit(role.guild, discord.AuditLogAction.role_delete)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(role.guild.get_member(user.id) or user):
        return

    try:
        await role.guild.ban(user, reason="Role Delete – Auto-Schutz")
        await security_log(role.guild, "Rolle gelöscht → Ban",
            f"{user.mention} hat die Rolle **{saved['name']}** gelöscht und wurde gebannt.",
            fields=[("User", f"{user} ({user.id})"), ("Rolle", saved["name"])])
    except Exception:
        pass

    try:
        restored = await role.guild.create_role(
            name=saved["name"], color=saved["color"],
            permissions=saved["permissions"], hoist=saved["hoist"],
            mentionable=saved["mentionable"],
            reason="Auto-Wiederherstellung (Schutz)",
        )
        await security_log(role.guild, "Rolle wiederhergestellt",
            f"Rolle **{saved['name']}** wurde automatisch wiederhergestellt.",
            color=discord.Color.green(),
            fields=[("Rolle", restored.mention)])
    except Exception:
        pass


@bot.event
async def on_guild_role_create(role: discord.Role):
    if role.guild.id != ALLOWED_GUILD_ID:
        return
    await asyncio.sleep(0.3)
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
            await role.guild.ban(user, reason=f"Role-Create-Spam ({CREATE_MAX}+ in {CREATE_INTERVAL}s)")
            await security_log(role.guild, "Role Create Spam → Ban",
                f"{user.mention} hat {len(role_create_tracker[user.id])} Rollen in {CREATE_INTERVAL}s erstellt.",
                fields=[("User", f"{user} ({user.id})")])
            role_create_tracker[user.id].clear()
        except Exception:
            pass


@bot.event
async def on_webhooks_update(channel: discord.TextChannel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return
    await asyncio.sleep(0.3)
    entry = await get_latest_audit(channel.guild, discord.AuditLogAction.webhook_create)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(channel.guild.get_member(user.id) or user):
        return
    try:
        for w in await channel.webhooks():
            await w.delete()
        await channel.guild.ban(user, reason="Webhook-Angriff – Auto-Schutz")
        await security_log(channel.guild, "Webhook Angriff → Ban",
            f"{user.mention} hat einen Webhook erstellt und wurde gebannt.",
            fields=[("User", f"{user} ({user.id})"), ("Kanal", channel.mention)])
    except Exception:
        pass


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
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
            await guild.ban(actor, reason="Mass Ban (2+ in 20s)")
            await security_log(guild, "Mass Ban → Ban",
                f"{actor.mention} hat 2+ Bans in 20s durchgeführt.",
                fields=[("User", f"{actor} ({actor.id})"), ("Anzahl", len(ban_tracker[actor.id]))])
        except Exception:
            pass


@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    if guild.id != ALLOWED_GUILD_ID:
        return
    await asyncio.sleep(0.3)
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
            await guild.ban(actor, reason="Mass Kick (2+ in 20s)")
            await security_log(guild, "Mass Kick → Ban",
                f"{actor.mention} hat 2+ Kicks in 20s durchgeführt.",
                fields=[("User", f"{actor} ({actor.id})"), ("Anzahl", len(kick_tracker[actor.id]))])
        except Exception:
            pass


@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    if entry.guild.id != ALLOWED_GUILD_ID:
        return

    # ── mass timeout ────────────────────────────────────
    if entry.action == discord.AuditLogAction.member_update:
        actor = entry.user
        if not actor or is_whitelisted(entry.guild.get_member(actor.id) or actor):
            return
        changes      = entry.changes
        after_changes = {c.key: c.new for c in changes.after} if hasattr(changes, "after") else {}
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
                    await security_log(entry.guild, "Mass Timeout → Ban",
                        f"{actor.mention} hat 2+ Timeouts in 15s vergeben.",
                        fields=[("User", f"{actor} ({actor.id})"), ("Anzahl", len(timeout_tracker[actor.id]))])
                except Exception:
                    pass

    # ── admin perm grant ────────────────────────────────
    if entry.action == discord.AuditLogAction.role_update:
        actor = entry.user
        if not actor or is_whitelisted(entry.guild.get_member(actor.id) or actor):
            return
        role = entry.target
        if not role or role.position >= entry.guild.me.top_role.position:
            return
        after_perms = None
        if hasattr(entry.changes, "after"):
            for c in entry.changes.after:
                if c.key == "permissions":
                    after_perms = c.new
                    break
        if after_perms and after_perms.administrator:
            try:
                p = discord.Permissions(after_perms.value)
                p.administrator = False
                await role.edit(permissions=p, reason="Admin-Perm entfernt (Schutz)")
            except Exception:
                pass
            m = entry.guild.get_member(actor.id)
            if m:
                try:
                    await m.kick(reason="Versuch Admin-Rechte zu vergeben")
                    await security_log(entry.guild, "Admin-Perm Versuch → Kick",
                        f"{actor.mention} hat versucht Admin-Rechte zu vergeben.",
                        fields=[("User", f"{actor} ({actor.id})"), ("Rolle", role.name)])
                except Exception:
                    pass

    # ── server update log ───────────────────────────────
    if entry.action == discord.AuditLogAction.guild_update:
        actor = entry.user
        if actor and not actor.bot:
            await security_log(entry.guild, "Server-Einstellungen geändert",
                f"{actor.mention} hat Server-Einstellungen geändert.",
                color=discord.Color.orange(),
                fields=[("User", f"{actor} ({actor.id})")])

    # ── bot added log ───────────────────────────────────
    if entry.action == discord.AuditLogAction.bot_add:
        actor     = entry.user
        bot_added = entry.target
        await security_log(entry.guild, "Bot hinzugefügt",
            f"{actor.mention} hat einen Bot hinzugefügt.",
            color=discord.Color.orange(),
            fields=[("Hinzugefügt von", f"{actor} ({actor.id})"),
                    ("Bot", f"{bot_added} ({bot_added.id})" if bot_added else "?")])

    # ── role assigned log ───────────────────────────────
    if entry.action == discord.AuditLogAction.member_role_update:
        actor  = entry.user
        target = entry.target
        if actor and not actor.bot:
            await security_log(entry.guild, "Rollen-Vergabe",
                f"{actor.mention} hat die Rollen von {target.mention if target else '?'} geändert.",
                color=discord.Color.blurple(),
                fields=[("Mod",  f"{actor} ({actor.id})"),
                        ("Ziel", f"{target} ({target.id})" if target else "?")])

# ═══════════════════════════════════════════════════════════
#  WHITELIST COMMANDS
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="whitelist_add", description="Fügt einen User zur Security-Whitelist hinzu", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def whitelist_add(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    SECURITY_WHITELIST_USERS.add(member.id)
    await interaction.response.send_message(f"✅ {member.mention} zur Whitelist hinzugefügt.", ephemeral=True)


@bot.tree.command(name="whitelist_remove", description="Entfernt einen User von der Security-Whitelist", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def whitelist_remove(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    SECURITY_WHITELIST_USERS.discard(member.id)
    await interaction.response.send_message(f"✅ {member.mention} von der Whitelist entfernt.", ephemeral=True)


@bot.tree.command(name="whitelist_list", description="Zeigt alle gewhitelisteten User", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def whitelist_list(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    if not SECURITY_WHITELIST_USERS:
        return await interaction.response.send_message("📋 Whitelist ist leer.", ephemeral=True)
    names = []
    for uid in SECURITY_WHITELIST_USERS:
        u = bot.get_user(uid)
        names.append(f"• {u} (`{uid}`)" if u else f"• Unbekannt (`{uid}`)")
    await interaction.response.send_message("📋 **Whitelist:**\n" + "\n".join(names), ephemeral=True)

# ═══════════════════════════════════════════════════════════
#  LOCKDOWN
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="lockdown", description="Sperrt oder entsperrt einen Kanal", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def lockdown(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    target    = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)

    if overwrite.send_messages is False:
        overwrite.send_messages = None
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔓 {target.mention} entsperrt.", ephemeral=True)
        await target.send("🔓 Dieser Kanal wurde entsperrt.")
        await security_log(interaction.guild, "Lockdown aufgehoben",
            f"{interaction.user.mention} hat {target.mention} entsperrt.",
            color=discord.Color.green(),
            fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Kanal", target.mention)])
    else:
        overwrite.send_messages = False
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"🔒 {target.mention} gesperrt.", ephemeral=True)
        await target.send("🔒 Dieser Kanal wurde vorübergehend gesperrt.")
        await security_log(interaction.guild, "Lockdown aktiviert",
            f"{interaction.user.mention} hat {target.mention} gesperrt.",
            color=discord.Color.red(),
            fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Kanal", target.mention)])

# ═══════════════════════════════════════════════════════════
#  /SEND
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="send", description="Sendet eine Nachricht in einen Kanal", guild=discord.Object(id=ALLOWED_GUILD_ID))
async def send_cmd(interaction: discord.Interaction, channel: discord.TextChannel, message: str, embed: bool = True, color: str = "black"):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("❌ Kein Zugriff", ephemeral=True)
    try:
        if embed:
            emb = discord.Embed(description=message, color=get_color(color))
            await channel.send(embed=emb)
        else:
            await channel.send(message)
        await interaction.response.send_message("✅ Gesendet", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# ═══════════════════════════════════════════════════════════
#  HELP COMMAND
# ═══════════════════════════════════════════════════════════

@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    embed = discord.Embed(
        title="📖 Bot Hilfe",
        color=discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="🛡️ Moderation", value=(
        "`?kick @user [Grund]`\n"
        "`?ban @user [Grund]`\n"
        "`?unban <ID> [Grund]`\n"
        "`?timeout @user <Zeit> [Grund]` – Einheiten: s m h d\n"
        "`?purge <Anzahl|all>`"
    ), inline=False)
    embed.add_field(name="⚠️ Warns", value=(
        "`?warn @user [Grund]`\n"
        "`?warns @user`\n"
        "`?clearwarn <ID>`\n"
        "`?clearwarns @user`"
    ), inline=False)
    embed.add_field(name="🎭 Rollen", value=(
        "`?role @user <Name oder ID>`"
    ), inline=False)
    embed.add_field(name="🎟️ Tickets", value=(
        "`?close` – Ticket schließen\n"
        "`?delete` – Transcript + Ticket löschen"
    ), inline=False)
    embed.add_field(name="ℹ️ Info", value=(
        "`/userinfo [@user]`\n"
        "`/serverinfo`\n"
        "`/avatar [@user]`"
    ), inline=False)
    embed.add_field(name="📨 Invites", value=(
        "`/invite @user`\n"
        "`/leaderboard`\n"
        "`/invites_set @user <Anzahl>`"
    ), inline=False)
    embed.add_field(name="🔧 Owner Only", value=(
        "`?setcount <Zahl>`\n"
        "`?call`\n"
        "`/send`\n"
        "`/lockdown [#kanal]`\n"
        "`/ticketpanel`\n"
        "`/whitelist_add/remove/list`"
    ), inline=False)
    embed.set_footer(text=f"Angefragt von {ctx.author}")
    await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════
#  !CALL
# ═══════════════════════════════════════════════════════════

@bot.command()
async def call(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID or not is_owner(ctx.author.id):
        return
    channel = bot.get_channel(CALL_VOICE_CHANNEL_ID)
    try:
        vc = ctx.voice_client
        if vc and vc.is_connected():
            await vc.move_to(channel)
        else:
            await channel.connect()
        await ctx.send("✅ Connected", delete_after=3)
    except Exception as e:
        await ctx.send(f"❌ Fehler: {e}")

# ═══════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════

bot.run(TOKEN)
