import sqlite3
import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import os
import re
import io

TOKEN = os.getenv("TOKEN")

# ================================================================
#  CONFIG
# ================================================================

ALLOWED_GUILD_ID = 1512581389726388314

OWNERS = {
    1393725545853882509,
    1235586743991009372,
}

CALL_VOICE_CHANNEL_ID   = 1512776116438306816
LOG_CHANNEL_ID          = 1512582270106468385
WELCOME_CHANNEL_ID      = 1512774925126078566
RULES_CHANNEL_ID        = 1512774929253273821
TICKET_PANEL_CHANNEL_ID = 1512774944818462741
TICKET_CATEGORY_ID      = 1512774917479993515
SUPPORT_ROLE_ID         = 1512774845287497819
BOOST_CHANNEL_ID        = 1512774965030682665
AUTO_REACT_CHANNEL_IDS  = {1512774973607907369, 1512774955413147648}
COUNTING_CHANNEL_ID     = 1512774971712209097
AUTO_ROLE_ID            = 1512774841005244426
TRIGGER_ROLE_ID         = 1512774837708525658
EXTRA_ROLE_ID_1         = 1512774836806619239
EXTRA_ROLE_ID_2         = 1512775255070867456
INVITE_CHANNEL_ID       = 1512774942184177765
ROLE_CMD_ALLOWED_ROLE_ID = 1512774843047870564

VOICE_ALWAYS_ON = True

# ================================================================
#  SECURITY CONFIG
# ================================================================

SPAM_MAX_MESSAGES = 5
SPAM_INTERVAL     = 3
SPAM_TIMEOUT_SECS = 300
MENTION_MAX       = 3        # lowered from 4
CREATE_MAX        = 3
CREATE_INTERVAL   = 15

INVITE_PATTERN = re.compile(r"(discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE)

SECURITY_WHITELIST_USERS: set[int] = set()
SECURITY_WHITELIST_ROLES: set[int] = set()

# ================================================================
#  BOT SETUP
# ================================================================

intents = discord.Intents.default()
intents.members         = True
intents.guilds          = True
intents.message_content = True
intents.reactions       = True
intents.voice_states    = True
intents.guild_messages  = True
intents.moderation      = True

bot = commands.Bot(
    command_prefix=["!", "?"],
    intents=intents,
    help_command=None
)

timeout_tracker        = defaultdict(list)
kick_tracker           = defaultdict(list)
ban_tracker            = defaultdict(list)
ticket_del_tracker     = defaultdict(list)
spam_tracker           = defaultdict(list)
mention_tracker        = defaultdict(list)
channel_create_tracker = defaultdict(list)
role_create_tracker    = defaultdict(list)

counting_state = {"current": 0, "last_user": None, "delete_notice": None}
first_react_announced: set[int] = set()

# ================================================================
#  DATABASE
# ================================================================

_db  = sqlite3.connect("bot.db", check_same_thread=False)
_cur = _db.cursor()

_cur.executescript("""
CREATE TABLE IF NOT EXISTS invites (
    guild_id INTEGER,
    user_id  INTEGER,
    invites  INTEGER DEFAULT 0,
    left_invites INTEGER DEFAULT 0,
    fake_invites INTEGER DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS ticket_counter (
    guild_id INTEGER PRIMARY KEY,
    counter  INTEGER DEFAULT 0
);
""")
_db.commit()

# ── invite helpers ──────────────────────────────────────────────

def _add_invite(guild_id: int, user_id: int, amount: int = 1):
    _cur.execute("""
        INSERT INTO invites (guild_id, user_id, invites) VALUES (?,?,?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET invites = invites + ?
    """, (guild_id, user_id, amount, amount))
    _db.commit()

def _get_invites(guild_id: int, user_id: int) -> tuple:
    _cur.execute(
        "SELECT invites, left_invites, fake_invites FROM invites WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )
    row = _cur.fetchone()
    return row if row else (0, 0, 0)

def _set_invites(guild_id: int, user_id: int, amount: int):
    _cur.execute("""
        INSERT INTO invites (guild_id, user_id, invites) VALUES (?,?,?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET invites = ?
    """, (guild_id, user_id, amount, amount))
    _db.commit()

def _get_top(guild_id: int, limit: int = 10):
    _cur.execute(
        "SELECT user_id, invites, left_invites, fake_invites FROM invites WHERE guild_id=? ORDER BY invites DESC LIMIT ?",
        (guild_id, limit)
    )
    return _cur.fetchall()

# ── warn helpers ────────────────────────────────────────────────

def _add_warn(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    _cur.execute(
        "INSERT INTO warns (guild_id,user_id,mod_id,reason,timestamp) VALUES (?,?,?,?,?)",
        (guild_id, user_id, mod_id, reason, datetime.utcnow().isoformat())
    )
    _db.commit()
    return _cur.lastrowid

def _get_warns(guild_id: int, user_id: int):
    _cur.execute(
        "SELECT id,mod_id,reason,timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id",
        (guild_id, user_id)
    )
    return _cur.fetchall()

def _del_warn(warn_id: int, guild_id: int) -> bool:
    _cur.execute("DELETE FROM warns WHERE id=? AND guild_id=?", (warn_id, guild_id))
    _db.commit()
    return _cur.rowcount > 0

def _clear_warns(guild_id: int, user_id: int) -> int:
    _cur.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    _db.commit()
    return _cur.rowcount

# ── counting persistence ────────────────────────────────────────

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

# ── ticket counter persistence ──────────────────────────────────

def _get_ticket_counter(guild_id: int) -> int:
    _cur.execute("SELECT counter FROM ticket_counter WHERE guild_id=?", (guild_id,))
    row = _cur.fetchone()
    return row[0] if row else 0

def _increment_ticket_counter(guild_id: int) -> int:
    _cur.execute("""
        INSERT INTO ticket_counter (guild_id, counter) VALUES (?,1)
        ON CONFLICT(guild_id) DO UPDATE SET counter = counter + 1
    """, (guild_id,))
    _db.commit()
    return _get_ticket_counter(guild_id)

invite_cache: dict[int, dict[str, int]] = {}

# ================================================================
#  HELPERS
# ================================================================

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
    """Safe math evaluation without eval()."""
    import operator, re as _re
    expr = expr.strip()
    # Only allow digits, operators, parentheses, spaces, decimals
    if not _re.fullmatch(r"[\d\s\+\-\*\/\(\)\.]+", expr):
        return None
    # Tokenise and evaluate safely using a recursive parser
    try:
        import ast
        tree = ast.parse(expr, mode="eval")
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num,
                   ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                   ast.Mod, ast.Pow, ast.UAdd, ast.USub, ast.Constant)
        for node in ast.walk(tree):
            if not isinstance(node, allowed):
                return None
        result = eval(compile(tree, "<math>", "eval"), {"__builtins__": {}}, {})
        if isinstance(result, (int, float)) and not isinstance(result, bool):
            return int(result) if result == int(result) else None
    except Exception:
        return None
    return None

async def get_latest_audit(guild: discord.Guild, action, target_id: int = None):
    try:
        async for entry in guild.audit_logs(limit=5, action=action):
            if target_id is None or (entry.target and entry.target.id == target_id):
                return entry
    except Exception:
        pass
    return None

# ── Log helpers ─────────────────────────────────────────────────

async def mod_log(
    guild: discord.Guild,
    action: str,
    description: str,
    color: discord.Color = discord.Color.from_rgb(30, 30, 30),
    fields: list | None = None,
):
    """Only sends logs that are relevant for moderation."""
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title=action,
        description=description,
        color=color,
        timestamp=datetime.utcnow(),
    )
    for name, value in (fields or []):
        embed.add_field(name=name, value=str(value)[:1024], inline=True)
    embed.set_footer(text="7z Security")
    try:
        await channel.send(embed=embed)
    except Exception:
        pass

async def _reply_and_clean(ctx, text: str, delay: float = 4.0):
    msg = await ctx.send(text)
    await asyncio.sleep(delay)
    for m in (ctx.message, msg):
        try:
            await m.delete()
        except Exception:
            pass

# ================================================================
#  READY
# ================================================================

async def setup_hook():
    bot.add_view(TicketButton())
    bot.add_view(TicketCloseView())

bot.setup_hook = setup_hook

@bot.event
async def on_ready():
    print(f"Online: {bot.user}")
    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
    except Exception:
        pass

    asyncio.create_task(voice_keep_alive())
    asyncio.create_task(cleanup_trackers())

    for guild in bot.guilds:
        current, last_user = _load_count(guild.id)
        counting_state["current"]   = current
        counting_state["last_user"] = last_user if last_user else None

    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

# ================================================================
#  TRACKER CLEANUP
# ================================================================

async def cleanup_trackers():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(10)
        now = datetime.utcnow()
        for tracker, window in [
            (timeout_tracker,        15),
            (kick_tracker,           20),
            (ban_tracker,            20),
            (spam_tracker,           SPAM_INTERVAL),
            (mention_tracker,        10),
            (channel_create_tracker, CREATE_INTERVAL),
            (role_create_tracker,    CREATE_INTERVAL),
        ]:
            dead = [uid for uid, times in tracker.items()
                    if not [t for t in times if now - t < timedelta(seconds=window)]]
            for uid in dead:
                del tracker[uid]

# ================================================================
#  VOICE KEEP-ALIVE
# ================================================================

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

# ================================================================
#  WELCOME / AUTO-ROLE
# ================================================================

@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != ALLOWED_GUILD_ID:
        return

    if is_new_account(member, days=7):
        await mod_log(
            member.guild,
            "New Account Warning",
            f"{member.mention} joined with an account younger than 7 days.",
            color=discord.Color.orange(),
            fields=[
                ("User",    f"{member} ({member.id})"),
                ("Created", f"<t:{int(member.created_at.timestamp())}:R>"),
            ],
        )

    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Auto Role")
        except Exception:
            pass

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

        invite_ch = member.guild.get_channel(INVITE_CHANNEL_ID)
        if not invite_ch:
            return

        # Vanity URL join — no normal invite matched
        if used_invite is None:
            vanity_code = None
            try:
                vanity = await member.guild.vanity_invite()
                if vanity:
                    vanity_code = vanity.code
            except Exception:
                pass

            embed = discord.Embed(
                title=member.guild.name,
                description=(
                    f"{member.mention} ist beigetreten.\n"
                    f"Eingeladen über **Vanity URL**"
                    + (f" (`/{vanity_code}`)" if vanity_code else "")
                ),
                color=discord.Color.from_rgb(149, 165, 166),
                timestamp=datetime.utcnow(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Vanity Invite")
            await invite_ch.send(embed=embed)

        elif used_invite.inviter:
            inviter = used_invite.inviter
            _add_invite(member.guild.id, inviter.id, 1)
            total, left, fake = _get_invites(member.guild.id, inviter.id)
            real = total - left - fake

            embed = discord.Embed(
                title=member.guild.name,
                description=(
                    f"{member.mention} ist beigetreten.\n"
                    f"Eingeladen von **{inviter.name}** ({inviter.mention}) \u2013 "
                    f"jetzt **{real} Invites**\n"
                    f"({total} gesamt \u00b7 {left} left \u00b7 {fake} fake)"
                ),
                color=discord.Color.from_rgb(149, 165, 166),
                timestamp=datetime.utcnow(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Invite code: {used_invite.code}")
            await invite_ch.send(embed=embed)

        else:
            embed = discord.Embed(
                title=member.guild.name,
                description=(
                    f"{member.mention} ist beigetreten.\n"
                    f"Einladender konnte nicht ermittelt werden."
                ),
                color=discord.Color.from_rgb(149, 165, 166),
                timestamp=datetime.utcnow(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Invite code: {used_invite.code}")
            await invite_ch.send(embed=embed)

    except Exception:
        pass

@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    if guild.id != ALLOWED_GUILD_ID:
        return

    # Update left-invites tracking
    try:
        new_invites = await guild.invites()
        old_cache   = invite_cache.get(guild.id, {})
        # Find which invite was used when they joined — not always possible,
        # so we just mark the inviter's count as -1 if detectable
        invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
    except Exception:
        pass

    # Mass kick detection
    await asyncio.sleep(0.3)
    entry = await get_latest_audit(guild, discord.AuditLogAction.kick, member.id)
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
            await guild.ban(actor, reason="Mass Kick detected (2+ in 20s)")
            await mod_log(guild, "Mass Kick — Auto Ban",
                f"{actor.mention} kicked 2+ members in 20 seconds.",
                fields=[("User", f"{actor} ({actor.id})"), ("Count", len(kick_tracker[actor.id]))])
        except Exception:
            pass

# ================================================================
#  BOOST / ROLE-TRIGGER
# ================================================================

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild.id != ALLOWED_GUILD_ID:
        return

    if not before.premium_since and after.premium_since:
        ch = after.guild.get_channel(BOOST_CHANNEL_ID)
        if ch:
            try:
                await ch.send("thank you 🖤")
            except Exception:
                pass

    before_ids = {r.id for r in before.roles}
    after_ids  = {r.id for r in after.roles}
    if TRIGGER_ROLE_ID in after_ids and TRIGGER_ROLE_ID not in before_ids:
        for extra_id in (EXTRA_ROLE_ID_1, EXTRA_ROLE_ID_2):
            extra = after.guild.get_role(extra_id)
            if extra:
                try:
                    await after.add_roles(extra, reason="Trigger Role")
                except Exception:
                    pass

# ================================================================
#  MESSAGES — Anti-Spam + Anti-MassMention + Auto-React + Counting
# ================================================================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    guild = message.guild
    if not guild or guild.id != ALLOWED_GUILD_ID:
        await bot.process_commands(message)
        return

    if not is_whitelisted(message.author):
        now = datetime.utcnow()

        # ── message spam ────────────────────────────────────
        spam_tracker[message.author.id].append(now)
        spam_tracker[message.author.id] = [
            t for t in spam_tracker[message.author.id]
            if now - t < timedelta(seconds=SPAM_INTERVAL)
        ]
        if len(spam_tracker[message.author.id]) >= SPAM_MAX_MESSAGES:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                await message.author.timeout(until, reason="Auto-Timeout: Message Spam")
                # Delete recent spam messages
                def is_spam(m):
                    return m.author.id == message.author.id
                try:
                    await message.channel.purge(limit=20, check=is_spam, bulk=True)
                except Exception:
                    pass
                await message.channel.send(
                    f"{message.author.mention} has been timed out for 5 minutes (spam).",
                    delete_after=5,
                )
                spam_tracker[message.author.id].clear()
                await mod_log(guild, "Anti-Spam — Timeout",
                    f"{message.author.mention} was automatically timed out for spam.",
                    color=discord.Color.orange(),
                    fields=[
                        ("User",     f"{message.author} ({message.author.id})"),
                        ("Channel",  message.channel.mention),
                        ("Duration", "5 minutes"),
                    ])
            except Exception:
                pass
            return

        # ── everyone / here ping spam ────────────────────────
        # Allow normal use — only block rapid repeated attempts
        if "@everyone" in message.content or "@here" in message.content:
            mention_tracker[message.author.id].append(now)
            mention_tracker[message.author.id] = [
                t for t in mention_tracker[message.author.id]
                if now - t < timedelta(seconds=10)
            ]
            if len(mention_tracker[message.author.id]) >= 2:
                try:
                    await message.delete()
                    until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                    await message.author.timeout(until, reason="Mass ping spam")
                    await message.channel.send(
                        f"{message.author.mention} has been timed out for mass ping spam.",
                        delete_after=5,
                    )
                    mention_tracker[message.author.id].clear()
                    await mod_log(guild, "Mass Ping Spam — Timeout",
                        f"{message.author.mention} spammed mass pings.",
                        color=discord.Color.red(),
                        fields=[("User", f"{message.author} ({message.author.id})")])
                except Exception:
                    pass
                return

        # ── user mention spam ────────────────────────────────
        total_mentions = len(set(u.id for u in message.mentions)) + len(message.role_mentions)
        if total_mentions >= MENTION_MAX:
            try:
                await message.delete()
                until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECS)
                await message.author.timeout(until, reason="Auto-Timeout: Mention Spam")
                await message.channel.send(
                    f"{message.author.mention} has been timed out for mass mentions.",
                    delete_after=5,
                )
                await mod_log(guild, "Mention Spam — Timeout",
                    f"{message.author.mention} sent {total_mentions} mentions in one message.",
                    color=discord.Color.orange(),
                    fields=[
                        ("User",     f"{message.author} ({message.author.id})"),
                        ("Channel",  message.channel.mention),
                        ("Mentions", total_mentions),
                    ])
            except Exception:
                pass
            return

        # ── invite filter ────────────────────────────────────
        if INVITE_PATTERN.search(message.content):
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} Discord invites are not allowed here.",
                    delete_after=5,
                )
                await mod_log(guild, "Invite Link Blocked",
                    f"{message.author.mention} posted an invite link.",
                    color=discord.Color.orange(),
                    fields=[
                        ("User",    f"{message.author} ({message.author.id})"),
                        ("Channel", message.channel.mention),
                    ])
            except Exception:
                pass
            return

    # ── auto-react ───────────────────────────────────────────
    if message.channel.id in AUTO_REACT_CHANNEL_IDS:
        emoji = "✅" if message.channel.id == 1512774955413147648 else "✔️"
        try:
            await message.add_reaction(emoji)
        except Exception:
            pass

    # ── counting ─────────────────────────────────────────────
    if COUNTING_CHANNEL_ID and message.channel.id == COUNTING_CHANNEL_ID:
        await handle_counting(message)
        return

    await bot.process_commands(message)

# ================================================================
#  MESSAGE EDIT / DELETE LOGS  (only relevant, no noise)
# ================================================================

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not after.guild or after.guild.id != ALLOWED_GUILD_ID:
        return
    if after.author.bot or before.content == after.content:
        return
    # Only log if content actually changed and is not empty
    if not before.content and not after.content:
        return
    pass  # message edit not logged

@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild or message.guild.id != ALLOWED_GUILD_ID:
        return

    # counting delete notice
    if COUNTING_CHANNEL_ID and message.channel.id == COUNTING_CHANNEL_ID:
        if message.author.bot:
            return
        next_num = counting_state["current"] + 1
        try:
            notice = await message.channel.send(
                f"A message was deleted. Next number is **{next_num}**."
            )
            counting_state["delete_notice"] = notice
        except Exception:
            pass
        return

    # Don't log bot message deletions
    if message.author.bot:
        return

    # Don't log empty messages (embeds only etc)
    if not message.content:
        return

    pass  # message delete not logged

# ================================================================
#  COUNTING SYSTEM
# ================================================================

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
                f"{message.author.mention} You can't count twice in a row."
            )
            await asyncio.sleep(2)
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
            n = await message.channel.send(
                f"Wrong number. Next is **{expected}**."
            )
            await asyncio.sleep(2)
            await n.delete()
        except Exception:
            pass

# ================================================================
#  FIRST REACTOR
# ================================================================

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
        await reaction.message.channel.send(f"{user.mention} was first 🥇")
    except Exception:
        pass

# ================================================================
#  VOICE STATE LOG
# ================================================================

@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    if not member.guild or member.guild.id != ALLOWED_GUILD_ID or member.bot:
        return
    pass  # voice state not logged

# ================================================================
#  TICKET SYSTEM
# ================================================================

def is_ticket_channel(channel: discord.TextChannel) -> bool:
    return channel.category_id == TICKET_CATEGORY_ID and channel.name.startswith("ticket-")

def can_manage_ticket(member: discord.Member) -> bool:
    if member.id in OWNERS:
        return True
    return any(r.id == SUPPORT_ROLE_ID or r.permissions.administrator for r in member.roles)

async def _generate_transcript(channel: discord.TextChannel) -> discord.File:
    lines = [f"Transcript — #{channel.name}", f"Exported: {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC", ""]
    async for msg in channel.history(limit=500, oldest_first=True):
        ts = msg.created_at.strftime("%d.%m.%Y %H:%M")
        lines.append(f"[{ts}] {msg.author} ({msg.author.id}): {msg.content}")
        for att in msg.attachments:
            lines.append(f"[{ts}] {msg.author}: [Attachment: {att.url}]")
    content = "\n".join(lines).encode("utf-8")
    return discord.File(io.BytesIO(content), filename=f"transcript-{channel.name}.txt")


class TicketCloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: Button):
        if not can_manage_ticket(interaction.user):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_message("Ticket is being closed...")
        try:
            await interaction.channel.set_permissions(
                interaction.guild.default_role,
                read_messages=False,
                send_messages=False,
            )
        except Exception as e:
            await interaction.channel.send(f"Error: {e}")

    @discord.ui.button(label="Save & Delete", style=discord.ButtonStyle.gray, custom_id="ticket_delete_btn")
    async def delete_btn(self, interaction: discord.Interaction, button: Button):
        if not can_manage_ticket(interaction.user):
            return await interaction.response.send_message("No permission.", ephemeral=True)
        await interaction.response.send_message("Generating transcript and deleting ticket...")
        try:
            transcript = await _generate_transcript(interaction.channel)
            log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_ch:
                embed = discord.Embed(
                    title="Ticket Closed",
                    description=f"**Channel:** {interaction.channel.name}\n**Closed by:** {interaction.user.mention}",
                    color=discord.Color.from_rgb(149, 165, 166),
                    timestamp=datetime.utcnow(),
                )
                await log_ch.send(embed=embed, file=transcript)
        except Exception:
            pass
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user}")
        except Exception:
            pass


class TicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.blurple, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        guild    = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        if category:
            for ch in category.text_channels:
                if ch.name.startswith("ticket-"):
                    ow = ch.overwrites_for(interaction.user)
                    if ow.read_messages:
                        return await interaction.response.send_message(
                            f"You already have an open ticket: {ch.mention}", ephemeral=True
                        )

        ticket_num   = _increment_ticket_counter(guild.id)
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
                name=f"ticket-{ticket_num}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket by {interaction.user}",
            )
            embed = discord.Embed(
                title="Support Ticket",
                description=(
                    "Describe your issue as clearly as possible.\n"
                    "Our team will assist you shortly."
                ),
                color=discord.Color.from_rgb(149, 165, 166),
                timestamp=datetime.utcnow(),
            )
            embed.set_footer(text=f"Ticket #{ticket_num}")
            pings = f"{support_role.mention} {interaction.user.mention}" if support_role else interaction.user.mention
            await ticket_channel.send(content=pings, embed=embed, view=TicketCloseView())
            await interaction.response.send_message(
                f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(
    name="ticketpanel",
    description="Send the ticket panel",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def ticketpanel(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    channel = interaction.guild.get_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("Channel not found.", ephemeral=True)
    embed = discord.Embed(
        title="Support",
        description="Click the button below to open a ticket.\nBe respectful — we'll help you as fast as possible.",
        color=discord.Color.from_rgb(149, 165, 166),
    )
    try:
        await channel.send(embed=embed, view=TicketButton())
        await interaction.response.send_message("Panel sent.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.command()
async def close(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID or not is_ticket_channel(ctx.channel):
        return
    if not can_manage_ticket(ctx.author):
        return await ctx.send("No permission.")
    await ctx.send("Closing ticket...")
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, read_messages=False, send_messages=False)
    except Exception as e:
        await ctx.send(f"Error: {e}")


@bot.command(name="delete")
async def delete_ticket(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID or not is_ticket_channel(ctx.channel):
        return
    if not can_manage_ticket(ctx.author):
        return await ctx.send("No permission.")

    if ctx.author.id not in OWNERS:
        now = datetime.utcnow()
        ticket_del_tracker[ctx.author.id] = [
            t for t in ticket_del_tracker[ctx.author.id]
            if now - t < timedelta(seconds=30)
        ]
        if len(ticket_del_tracker[ctx.author.id]) >= 3:
            return await ctx.send("Maximum 3 ticket deletions per 30 seconds.", delete_after=5)
        ticket_del_tracker[ctx.author.id].append(now)

    try:
        transcript = await _generate_transcript(ctx.channel)
        log_ch = ctx.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            embed = discord.Embed(
                title="Ticket Closed",
                description=f"**Channel:** {ctx.channel.name}\n**Closed by:** {ctx.author.mention}",
                color=discord.Color.from_rgb(149, 165, 166),
                timestamp=datetime.utcnow(),
            )
            await log_ch.send(embed=embed, file=transcript)
    except Exception:
        pass
    await asyncio.sleep(1)
    try:
        await ctx.channel.delete(reason=f"Ticket deleted by {ctx.author}")
    except Exception as e:
        await ctx.send(f"Error: {e}")

# ================================================================
#  MODERATION COMMANDS
# ================================================================

@bot.command()
async def kick(ctx: commands.Context, member: discord.Member = None, *, reason: str = "No reason provided"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None:
        return await _reply_and_clean(ctx, "Usage: `?kick @user [reason]`")
    if member.id in OWNERS:
        return await _reply_and_clean(ctx, "Cannot kick an owner.")
    if member.top_role >= ctx.guild.me.top_role:
        return await _reply_and_clean(ctx, "That member has a higher role than me.")
    try:
        await member.kick(reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(title="Kick", color=discord.Color.orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",   value=f"{member} ({member.id})")
        embed.add_field(name="Mod",    value=str(ctx.author))
        embed.add_field(name="Reason", value=reason)
        await ctx.send(embed=embed)

    except discord.Forbidden:
        await ctx.send("Missing permissions.")
    except Exception as e:
        await ctx.send(f"Error: {e}")


@bot.command()
async def ban(ctx: commands.Context, member: discord.Member = None, *, reason: str = "No reason provided"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None:
        return await _reply_and_clean(ctx, "Usage: `?ban @user [reason]`")
    if member.id in OWNERS:
        return await _reply_and_clean(ctx, "Cannot ban an owner.")
    if member.top_role >= ctx.guild.me.top_role:
        return await _reply_and_clean(ctx, "That member has a higher role than me.")
    try:
        await member.ban(reason=f"{ctx.author}: {reason}", delete_message_days=1)
        embed = discord.Embed(title="Ban", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User",   value=f"{member} ({member.id})")
        embed.add_field(name="Mod",    value=str(ctx.author))
        embed.add_field(name="Reason", value=reason)
        await ctx.send(embed=embed)

    except discord.Forbidden:
        await ctx.send("Missing permissions.")
    except Exception as e:
        await ctx.send(f"Error: {e}")


@bot.command()
async def unban(ctx: commands.Context, user_id: str = None, *, reason: str = "No reason provided"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if user_id is None or not user_id.isdigit():
        return await _reply_and_clean(ctx, "Usage: `?unban <UserID> [reason]`")
    try:
        user = await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(title="Unban", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="User",   value=f"{user} ({user.id})")
        embed.add_field(name="Mod",    value=str(ctx.author))
        embed.add_field(name="Reason", value=reason)
        await ctx.send(embed=embed)

    except discord.NotFound:
        await ctx.send("User not found or not banned.")
    except Exception as e:
        await ctx.send(f"Error: {e}")


@bot.command()
async def timeout(
    ctx: commands.Context,
    member: discord.Member = None,
    duration: str = None,
    *,
    reason: str = "No reason provided",
):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None or duration is None:
        return await _reply_and_clean(ctx, "Usage: `?timeout @user <time> [reason]` — Units: `s` `m` `h` `d`")

    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit  = duration[-1].lower()
    if unit not in units or not duration[:-1].isdigit():
        return await _reply_and_clean(ctx, "Invalid time. Example: `10m`, `2h`, `1d`")

    seconds = int(duration[:-1]) * units[unit]
    if seconds > 2419200:
        return await _reply_and_clean(ctx, "Maximum timeout duration is 28 days.")

    try:
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
        embed = discord.Embed(title="Timeout", color=discord.Color.orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",     value=f"{member} ({member.id})")
        embed.add_field(name="Duration", value=duration)
        embed.add_field(name="Until",    value=f"<t:{int(until.timestamp())}:F>")
        embed.add_field(name="Reason",   value=reason)
        embed.add_field(name="Mod",      value=str(ctx.author))
        await ctx.send(embed=embed)

    except discord.Forbidden:
        await ctx.send("Missing permissions.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

# ================================================================
#  WARN SYSTEM
# ================================================================

@bot.command()
async def warn(ctx: commands.Context, member: discord.Member = None, *, reason: str = "No reason provided"):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None:
        return await _reply_and_clean(ctx, "Usage: `?warn @user [reason]`")

    warn_id = _add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
    warns   = _get_warns(ctx.guild.id, member.id)

    embed = discord.Embed(title="Warning", color=discord.Color.yellow(), timestamp=datetime.utcnow())
    embed.add_field(name="User",        value=f"{member} ({member.id})")
    embed.add_field(name="Mod",         value=str(ctx.author))
    embed.add_field(name="Reason",      value=reason)
    embed.add_field(name="Warn ID",     value=f"#{warn_id}")
    embed.add_field(name="Total Warns", value=str(len(warns)))
    await ctx.send(embed=embed)

    # DM
    dm_status = "DM sent"
    try:
        dm_embed = discord.Embed(
            title=f"You received a warning on {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Warn #{warn_id}** — Total: {len(warns)}",
            color=discord.Color.yellow(),
            timestamp=datetime.utcnow(),
        )
        await member.send(embed=dm_embed)
    except Exception:
        dm_status = "DM failed (blocked)"




@bot.command()
async def warns(ctx: commands.Context, member: discord.Member = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None:
        return await _reply_and_clean(ctx, "Usage: `?warns @user`")

    warn_list = _get_warns(ctx.guild.id, member.id)
    embed = discord.Embed(
        title=f"Warnings — {member}",
        color=discord.Color.yellow(),
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if not warn_list:
        embed.description = "No warnings on record."
    else:
        for w_id, mod_id, reason, ts in warn_list:
            mod     = ctx.guild.get_member(mod_id)
            mod_str = str(mod) if mod else f"ID:{mod_id}"
            embed.add_field(
                name=f"#{w_id} — {ts[:10]}",
                value=f"**Reason:** {reason}\n**Mod:** {mod_str}",
                inline=False,
            )
    await ctx.send(embed=embed)


@bot.command()
async def clearwarn(ctx: commands.Context, warn_id: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if warn_id is None or not warn_id.isdigit():
        return await _reply_and_clean(ctx, "Usage: `?clearwarn <WarnID>`")
    if _del_warn(int(warn_id), ctx.guild.id):
        await ctx.send(f"Warning **#{warn_id}** deleted.", delete_after=5)
    else:
        await ctx.send(f"Warning **#{warn_id}** not found.", delete_after=5)


@bot.command()
async def clearwarns(ctx: commands.Context, member: discord.Member = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None:
        return await _reply_and_clean(ctx, "Usage: `?clearwarns @user`")
    count = _clear_warns(ctx.guild.id, member.id)
    await ctx.send(f"**{count}** warnings cleared for {member.mention}.", delete_after=5)

# ================================================================
#  USERINFO / SERVERINFO / AVATAR
# ================================================================

@bot.tree.command(
    name="userinfo",
    description="Show info about a user",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles  = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]

    embed = discord.Embed(
        title=str(member),
        color=member.color if member.color.value else discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID",       value=member.id,                                     inline=True)
    embed.add_field(name="Nickname", value=member.nick or "—",                            inline=True)
    embed.add_field(name="Bot",      value="Yes" if member.bot else "No",                 inline=True)
    embed.add_field(name="Created",  value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
    embed.add_field(name="Joined",   value=f"<t:{int(member.joined_at.timestamp())}:R>",  inline=True)
    embed.add_field(
        name="Boosting",
        value=f"<t:{int(member.premium_since.timestamp())}:R>" if member.premium_since else "No",
        inline=True,
    )
    embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:20]) or "—", inline=False)
    embed.set_footer(text=f"Requested by {interaction.user}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="serverinfo",
    description="Show server info",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(
        title=g.name,
        color=discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="ID",           value=g.id,                                        inline=True)
    embed.add_field(name="Owner",        value=f"<@{g.owner_id}>",                          inline=True)
    embed.add_field(name="Created",      value=f"<t:{int(g.created_at.timestamp())}:R>",    inline=True)
    embed.add_field(name="Members",      value=g.member_count,                              inline=True)
    embed.add_field(name="Roles",        value=len(g.roles),                                inline=True)
    embed.add_field(name="Channels",     value=len(g.channels),                             inline=True)
    embed.add_field(name="Boosts",       value=g.premium_subscription_count,                inline=True)
    embed.add_field(name="Boost Level",  value=g.premium_tier,                              inline=True)
    embed.add_field(name="Verification", value=str(g.verification_level),                   inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="avatar",
    description="Show a user's avatar",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed  = discord.Embed(
        title=f"Avatar — {member}",
        color=discord.Color.from_rgb(149, 165, 166),
    )
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)

# ================================================================
#  PURGE
# ================================================================

@bot.command()
async def purge(ctx: commands.Context, amount: str = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not can_moderate(ctx.author):
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    try:
        await ctx.message.delete()
    except Exception:
        pass
    if amount is None:
        return await ctx.send("Usage: `?purge all` or `?purge <amount>`", delete_after=3)

    if amount.lower() == "all":
        deleted = await ctx.channel.purge(limit=None)
    else:
        if not amount.isdigit() or int(amount) < 1:
            return await ctx.send("Invalid amount.", delete_after=3)
        if int(amount) > 1000:
            return await ctx.send("Maximum 1000 messages per purge.", delete_after=3)
        deleted = await ctx.channel.purge(limit=int(amount))

    note = await ctx.send(f"{len(deleted)} messages deleted.")
    await asyncio.sleep(3)
    try:
        await note.delete()
    except Exception:
        pass

# ================================================================
#  ROLE COMMAND
# ================================================================

def _find_role(guild: discord.Guild, query: str) -> list[discord.Role]:
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
        return await _reply_and_clean(ctx, "Insufficient permissions.")
    if member is None or role_input is None:
        return await _reply_and_clean(ctx, "Usage: `?role @user <role name or ID>`")

    matches = _find_role(ctx.guild, role_input)
    if not matches:
        return await _reply_and_clean(ctx, f"No role found matching **{role_input}**.")
    if len(matches) > 1:
        names = ", ".join(f"`{r.name}`" for r in matches[:8])
        return await _reply_and_clean(ctx, f"Multiple roles found: {names} — be more specific.", delay=6)

    role = matches[0]
    if role >= ctx.guild.me.top_role:
        return await _reply_and_clean(ctx, "That role is equal to or higher than my highest role.")
    if role.permissions.administrator and ctx.author.id not in OWNERS:
        return await _reply_and_clean(ctx, "Only owners can assign admin roles.")

    try:
        if role in member.roles:
            await member.remove_roles(role, reason=f"?role by {ctx.author}")
            action, color = "removed", discord.Color.red()
        else:
            await member.add_roles(role, reason=f"?role by {ctx.author}")
            action, color = "added", discord.Color.green()

        embed = discord.Embed(color=color, timestamp=datetime.utcnow())
        embed.description = f"Role **{role.name}** {action} for {member.mention}."
        embed.add_field(name="Role", value=f"{role.mention} ({role.id})")
        embed.add_field(name="User", value=f"{member} ({member.id})")
        embed.set_footer(text=f"By {ctx.author} · {ctx.author.id}")
        await ctx.send(embed=embed)


    except discord.Forbidden:
        await ctx.send("Missing permissions for that role.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

# ================================================================
#  SETCOUNT
# ================================================================

@bot.command()
async def setcount(ctx: commands.Context, number: int = None):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    if not is_owner(ctx.author.id):
        return await _reply_and_clean(ctx, "No permission.")
    if number is None:
        return await _reply_and_clean(ctx, "Usage: `?setcount <number>`")
    counting_state["current"]   = number
    counting_state["last_user"] = None
    _save_count(ctx.guild.id, number, 0)
    await ctx.send(f"Counter set to **{number}**.", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception:
        pass

# ================================================================
#  INVITE SLASH COMMANDS
# ================================================================

@bot.tree.command(
    name="invite",
    description="Show invite count for a user",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def invite_cmd(interaction: discord.Interaction, member: discord.Member):
    total, left, fake = _get_invites(interaction.guild.id, member.id)
    real = total - left - fake

    embed = discord.Embed(color=discord.Color.from_rgb(149, 165, 166), timestamp=datetime.utcnow())
    embed.set_author(name=f"{member.name}'s Invites", icon_url=member.display_avatar.url)
    embed.description = f"**{member.mention}** has **{real}** invites"
    embed.add_field(name="Total",  value=total, inline=True)
    embed.add_field(name="Left",   value=left,  inline=True)
    embed.add_field(name="Fake",   value=fake,  inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="invites_set",
    description="Manually set invite count for a user",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def invites_set_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    _set_invites(interaction.guild.id, member.id, amount)
    await interaction.response.send_message(
        f"Invites for {member.mention} set to **{amount}**.", ephemeral=True
    )


@bot.tree.command(
    name="leaderboard",
    description="Show invite leaderboard",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def leaderboard_cmd(interaction: discord.Interaction):
    top = _get_top(interaction.guild.id)
    if not top:
        return await interaction.response.send_message("No invite data yet.", ephemeral=True)

    embed = discord.Embed(
        title="Invite Leaderboard",
        color=discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (user_id, total, left, fake) in enumerate(top, start=1):
        user = bot.get_user(user_id)
        name = user.name if user else f"Unknown ({user_id})"
        real = total - left - fake
        prefix = medals.get(i, f"{i}.")
        embed.add_field(
            name=f"{prefix} {name}",
            value=f"**{real}** invites ({total} total · {left} left · {fake} fake)",
            inline=False,
        )
    await interaction.response.send_message(embed=embed)

# ================================================================
#  SECURITY SYSTEM
# ================================================================

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    if channel.guild.id != ALLOWED_GUILD_ID:
        return

    # Don't restore ticket channels — they should stay deleted
    if (
        getattr(channel, "category_id", None) == TICKET_CATEGORY_ID
        and channel.name.startswith("ticket-")
    ):
        return

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

    try:
        await channel.guild.ban(user, reason="Channel Delete — Auto Protection")
        await mod_log(channel.guild, "Channel Deleted — Auto Ban",
            f"{user.mention} deleted **#{saved['name']}** and was banned.",
            fields=[("User", f"{user} ({user.id})"), ("Channel", saved["name"])])
    except Exception:
        pass

    # Restore channel
    try:
        kwargs = dict(
            name=saved["name"],
            overwrites=saved["overwrites"],
            category=saved["category"],
            position=saved["position"],
            reason="Auto-Restore (Protection)",
        )
        if saved["type"] == discord.ChannelType.text:
            if saved["topic"]:
                kwargs["topic"] = saved["topic"]
            kwargs["nsfw"]            = saved["nsfw"]
            kwargs["slowmode_delay"]  = saved["slowmode"]
            restored = await channel.guild.create_text_channel(**kwargs)
        elif saved["type"] == discord.ChannelType.voice:
            restored = await channel.guild.create_voice_channel(**kwargs)
        else:
            restored = await channel.guild.create_text_channel(**kwargs)

        await mod_log(channel.guild, "Channel Restored",
            f"Channel **#{saved['name']}** was automatically restored.",
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
            await channel.guild.ban(user, reason=f"Channel Spam ({CREATE_MAX}+ in {CREATE_INTERVAL}s)")
            await mod_log(channel.guild, "Channel Spam — Auto Ban",
                f"{user.mention} created {len(channel_create_tracker[user.id])} channels in {CREATE_INTERVAL}s.",
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
    }

    await asyncio.sleep(0.3)
    entry = await get_latest_audit(role.guild, discord.AuditLogAction.role_delete)
    if not entry:
        return
    user = entry.user
    if not user or is_whitelisted(role.guild.get_member(user.id) or user):
        return

    try:
        await role.guild.ban(user, reason="Role Delete — Auto Protection")
        await mod_log(role.guild, "Role Deleted — Auto Ban",
            f"{user.mention} deleted role **{saved['name']}** and was banned.",
            fields=[("User", f"{user} ({user.id})"), ("Role", saved["name"])])
    except Exception:
        pass

    try:
        restored = await role.guild.create_role(
            name=saved["name"],
            color=saved["color"],
            permissions=saved["permissions"],
            hoist=saved["hoist"],
            mentionable=saved["mentionable"],
            reason="Auto-Restore (Protection)",
        )
        await mod_log(role.guild, "Role Restored",
            f"Role **{saved['name']}** was automatically restored.",
            color=discord.Color.green(),
            fields=[("Role", restored.mention)])
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
            await role.guild.ban(user, reason=f"Role Spam ({CREATE_MAX}+ in {CREATE_INTERVAL}s)")
            await mod_log(role.guild, "Role Spam — Auto Ban",
                f"{user.mention} created {len(role_create_tracker[user.id])} roles in {CREATE_INTERVAL}s.",
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
        await channel.guild.ban(user, reason="Webhook Attack — Auto Protection")
        await mod_log(channel.guild, "Webhook Attack — Auto Ban",
            f"{user.mention} created a webhook and was banned.",
            fields=[("User", f"{user} ({user.id})"), ("Channel", channel.mention)])
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
            await mod_log(guild, "Mass Ban — Auto Ban",
                f"{actor.mention} banned 2+ members in 20 seconds.",
                fields=[("User", f"{actor} ({actor.id})"), ("Count", len(ban_tracker[actor.id]))])
        except Exception:
            pass


@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    if entry.guild.id != ALLOWED_GUILD_ID:
        return

    # ── mass timeout ────────────────────────────────────────
    if entry.action == discord.AuditLogAction.member_update:
        actor = entry.user
        if not actor or is_whitelisted(entry.guild.get_member(actor.id) or actor):
            return
        changes       = entry.changes
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
                    await mod_log(entry.guild, "Mass Timeout — Auto Ban",
                        f"{actor.mention} timed out 2+ members in 15 seconds.",
                        fields=[("User", f"{actor} ({actor.id})"), ("Count", len(timeout_tracker[actor.id]))])
                except Exception:
                    pass

    # ── admin perm grant ────────────────────────────────────
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
                await role.edit(permissions=p, reason="Admin perm removed (Protection)")
            except Exception:
                pass
            m = entry.guild.get_member(actor.id)
            if m:
                try:
                    await m.kick(reason="Attempted to grant admin permissions")
                    await mod_log(entry.guild, "Admin Perm Attempt — Kick",
                        f"{actor.mention} tried to grant admin permissions.",
                        fields=[("User", f"{actor} ({actor.id})"), ("Role", role.name)])
                except Exception:
                    pass

    # ── server update log ───────────────────────────────────
    if entry.action == discord.AuditLogAction.guild_update:
        actor = entry.user
        if actor and not actor.bot:
            await mod_log(entry.guild, "Server Settings Changed",
                f"{actor.mention} modified server settings.",
                color=discord.Color.orange(),
                fields=[("User", f"{actor} ({actor.id})")])

    # ── bot added log ───────────────────────────────────────
    if entry.action == discord.AuditLogAction.bot_add:
        actor     = entry.user
        bot_added = entry.target
        await mod_log(entry.guild, "Bot Added",
            f"{actor.mention} added a bot to the server.",
            color=discord.Color.orange(),
            fields=[
                ("Added by", f"{actor} ({actor.id})"),
                ("Bot",      f"{bot_added} ({bot_added.id})" if bot_added else "Unknown"),
            ])

# ================================================================
#  WHITELIST COMMANDS
# ================================================================

@bot.tree.command(
    name="whitelist_add",
    description="Add a user to the security whitelist",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def whitelist_add(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    SECURITY_WHITELIST_USERS.add(member.id)
    await interaction.response.send_message(f"{member.mention} added to whitelist.", ephemeral=True)


@bot.tree.command(
    name="whitelist_remove",
    description="Remove a user from the security whitelist",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def whitelist_remove(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    SECURITY_WHITELIST_USERS.discard(member.id)
    await interaction.response.send_message(f"{member.mention} removed from whitelist.", ephemeral=True)


@bot.tree.command(
    name="whitelist_list",
    description="Show all whitelisted users",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def whitelist_list(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    if not SECURITY_WHITELIST_USERS:
        return await interaction.response.send_message("Whitelist is empty.", ephemeral=True)
    names = []
    for uid in SECURITY_WHITELIST_USERS:
        u = bot.get_user(uid)
        names.append(f"{u} (`{uid}`)" if u else f"Unknown (`{uid}`)")
    await interaction.response.send_message("**Whitelist:**\n" + "\n".join(names), ephemeral=True)

# ================================================================
#  /SEND
# ================================================================

@bot.tree.command(
    name="send",
    description="Send a message to a channel",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def send_cmd(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
    embed: bool = True,
    color: str = "black",
):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    try:
        if embed:
            emb = discord.Embed(description=message, color=get_color(color))
            await channel.send(embed=emb)
        else:
            await channel.send(message)
        await interaction.response.send_message("Sent.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)

# ================================================================
#  HELP COMMAND
# ================================================================

@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    if ctx.guild.id != ALLOWED_GUILD_ID:
        return
    embed = discord.Embed(
        title="Command Overview",
        color=discord.Color.from_rgb(149, 165, 166),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Moderation", value=(
        "`?kick @user [reason]`\n"
        "`?ban @user [reason]`\n"
        "`?unban <ID> [reason]`\n"
        "`?timeout @user <time> [reason]` — s m h d\n"
        "`?purge <amount|all>`"
    ), inline=False)
    embed.add_field(name="Warnings", value=(
        "`?warn @user [reason]`\n"
        "`?warns @user`\n"
        "`?clearwarn <ID>`\n"
        "`?clearwarns @user`"
    ), inline=False)
    embed.add_field(name="Roles", value="`?role @user <name or ID>`", inline=False)

    embed.add_field(name="Info", value=(
        "`/userinfo [@user]`\n"
        "`/serverinfo`\n"
        "`/avatar [@user]`"
    ), inline=False)
    embed.add_field(name="Invites", value=(
        "`/invite @user`\n"
        "`/leaderboard`\n"
        "`/invites_set @user <amount>`"
    ), inline=False)
    embed.add_field(name="Utility", value=(
        "`/say #channel <text>`\n"
        "`/alts [days]` — Show new accounts"
    ), inline=False)
    embed.add_field(name="Tickets", value=(
        "`?close` — Close ticket\n"
        "`?delete` — Save transcript & delete\n"
        "`/adduser @user` — Add user to ticket\n"
        "`/removeuser @user` — Remove user from ticket\n"
        "`/renameticket <name>` — Rename ticket"
    ), inline=False)
    embed.add_field(name="Owner Only", value=(
        "`?setcount <number>`\n"
        "`?call`\n"
        "`/send`\n"
        "`/ticketpanel`\n"
        "`/whitelist_add|remove|list`"
    ), inline=False)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

# ================================================================
#  !CALL
# ================================================================

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
        await ctx.send("Connected.", delete_after=3)
    except Exception as e:
        await ctx.send(f"Error: {e}")


# ================================================================
#  SLASH COMMANDS — SAY / ALTS / TICKET TOOLS
# ================================================================

@bot.tree.command(
    name="say",
    description="Send a message as the bot",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def say_cmd(interaction: discord.Interaction, channel: discord.TextChannel, text: str):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("No permission.", ephemeral=True)
    try:
        await channel.send(text)
        await interaction.response.send_message("Sent.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("Missing permissions for that channel.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(
    name="alts",
    description="Show accounts younger than X days",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def alts_cmd(interaction: discord.Interaction, days: int = 7):
    if not can_moderate(interaction.user):
        return await interaction.response.send_message("Insufficient permissions.", ephemeral=True)
    if days < 1 or days > 365:
        return await interaction.response.send_message("Days must be between 1 and 365.", ephemeral=True)

    now  = datetime.utcnow()
    alts = [
        m for m in interaction.guild.members
        if not m.bot and (now - m.created_at.replace(tzinfo=None)) < timedelta(days=days)
    ]

    if not alts:
        return await interaction.response.send_message(
            f"No accounts younger than {days} days found.", ephemeral=True
        )

    embed = discord.Embed(
        title=f"Accounts younger than {days} days",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text=f"Found {len(alts)} account(s)")

    lines = []
    for m in sorted(alts, key=lambda x: x.created_at, reverse=True)[:20]:
        age_days = (now - m.created_at.replace(tzinfo=None)).days
        lines.append(f"{m.mention} — {age_days}d old (<t:{int(m.created_at.timestamp())}:R>)")

    embed.description = "\n".join(lines)
    if len(alts) > 20:
        embed.description += f"\n*...and {len(alts) - 20} more*"
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="adduser",
    description="Add a user to the current ticket",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def adduser_cmd(interaction: discord.Interaction, member: discord.Member):
    if not is_ticket_channel(interaction.channel):
        return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
    if not can_manage_ticket(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    try:
        await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
        await interaction.response.send_message(f"{member.mention} has been added to the ticket.", ephemeral=False)
    except discord.Forbidden:
        await interaction.response.send_message("Missing permissions.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(
    name="removeuser",
    description="Remove a user from the current ticket",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def removeuser_cmd(interaction: discord.Interaction, member: discord.Member):
    if not is_ticket_channel(interaction.channel):
        return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
    if not can_manage_ticket(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    try:
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(f"{member.mention} has been removed from the ticket.", ephemeral=False)
    except discord.Forbidden:
        await interaction.response.send_message("Missing permissions.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(
    name="renameticket",
    description="Rename the current ticket",
    guild=discord.Object(id=ALLOWED_GUILD_ID)
)
async def renameticket_cmd(interaction: discord.Interaction, name: str):
    if not is_ticket_channel(interaction.channel):
        return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
    if not can_manage_ticket(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    name = name.lower().replace(" ", "-")[:50]
    try:
        await interaction.channel.edit(name=f"ticket-{name}")
        await interaction.response.send_message(f"Ticket renamed to **ticket-{name}**.", ephemeral=False)
    except discord.Forbidden:
        await interaction.response.send_message("Missing permissions.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)

# ================================================================
#  START
# ================================================================

bot.run(TOKEN)
