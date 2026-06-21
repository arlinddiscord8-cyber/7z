import sqlite3, discord, asyncio, os, re, pathlib
from discord.ext import commands
from discord.ui import View, Button
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN")

ALLOWED_GUILD_ID         = 1512857571344515344
OWNERS: set[int]         = {1393725545853882509, 1325204584829947914}
CALL_VOICE_CHANNEL_ID    = 1516453482230583458
LOG_CHANNEL_ID           = 1516453487322595409
WELCOME_CHANNEL_ID       = 1516453500765208596
RULES_CHANNEL_ID         = 1516453504955187230
TICKET_PANEL_CHANNEL_ID  = 1516453513717219489
TICKET_CATEGORY_ID       = 1516453498269597697
SUPPORT_ROLE_ID          = 1516453478564630659
BOOST_CHANNEL_ID         = 1516453537024966708
AUTO_REACT_CHANNEL_IDS   = {1516453525041713225, 1516453552464203806}
ACTIVITY_CHECK_CHANNEL_ID= 1516453525041713225
COUNTING_CHANNEL_ID      = 1516453550996324392
AUTO_ROLE_ID             = 1516453463188307970
TRIGGER_ROLE_ID          = 1516453466921242875
EXTRA_ROLE_ID_1          = 1516453459115638876
EXTRA_ROLE_ID_2          = 1516453459115638876
INVITE_CHANNEL_ID        = 1516453511716405421
ROLE_CMD_ALLOWED_ROLE_ID = 1516453466921242875
TIMEOUT_ROLE_ID          = 1516453465810014460
VOICE_ALWAYS_ON          = True
SPAM_MAX=5; SPAM_INTERVAL=3; SPAM_TIMEOUT=300; MENTION_MAX=3; CREATE_MAX=3; CREATE_WIN=15
PING_MAX=2; PING_WINDOW=5
INVITE_RE = re.compile(r"(discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE)
SECURITY_WHITELIST_USERS: set[int] = set()
SECURITY_WHITELIST_ROLES: set[int] = set()
SECURITY_MODULES = [
    "anti_spam","anti_mention","anti_invite","anti_webhook",
    "anti_channel_delete","anti_channel_create","anti_role_delete","anti_role_create",
    "anti_mass_ban","anti_mass_kick","anti_mass_timeout","anti_admin_perm","new_account_warn",
]

# Berlin Timezone
BERLIN_TZ = ZoneInfo("Europe/Berlin")

NIGHT_MODE_ROLES = [
    1516514623413813488,
    1516453412106014851,
    1516457574151749724,
]
_night_saved_perms: dict[int, discord.Permissions] = {}

intents = discord.Intents.default()
intents.members=intents.guilds=intents.message_content=True
intents.reactions=intents.voice_states=True
intents.guild_messages=intents.moderation=True
bot = commands.Bot(command_prefix=["!","?"],intents=intents,help_command=None,
    allowed_mentions=discord.AllowedMentions(everyone=False,roles=False,users=False,replied_user=False))

timeout_tracker=defaultdict(list); kick_tracker=defaultdict(list); ban_tracker=defaultdict(list)
spam_tracker=defaultdict(list); mention_tracker=defaultdict(list); invite_link_tracker=defaultdict(list)
channel_create_tracker=defaultdict(list); role_create_tracker=defaultdict(list)
mass_ping_tracker=defaultdict(list)
counting_state:dict={"current":0,"last_user":None,"delete_notice":None}
first_react_announced:set=set(); invite_cache:dict={}; afk_users:dict={}

_DB="/data/bot.db" if pathlib.Path("/data").exists() else "bot.db"
if not pathlib.Path("/data").exists(): print("WARNING: /data not found — DB resets on restart.")
_db=sqlite3.connect(_DB,check_same_thread=False); _cur=_db.cursor()
_cur.executescript("""
CREATE TABLE IF NOT EXISTS invites(guild_id INT,user_id INT,invites INT DEFAULT 0,left_invites INT DEFAULT 0,fake_invites INT DEFAULT 0,PRIMARY KEY(guild_id,user_id));
CREATE TABLE IF NOT EXISTS warns(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INT NOT NULL,user_id INT NOT NULL,mod_id INT NOT NULL,reason TEXT NOT NULL,timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS counting(guild_id INT PRIMARY KEY,current INT DEFAULT 0,last_user INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS ticket_counter(guild_id INT PRIMARY KEY,counter INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS hackbans(guild_id INT,user_id INT,mod_id INT,reason TEXT,alts TEXT DEFAULT '',PRIMARY KEY(guild_id,user_id));
CREATE TABLE IF NOT EXISTS cfg_ids(guild_id INT,key TEXT,value INT,PRIMARY KEY(guild_id,key));
CREATE TABLE IF NOT EXISTS cfg_msgs(guild_id INT,key TEXT,value TEXT,PRIMARY KEY(guild_id,key));
CREATE TABLE IF NOT EXISTS sec_modules(guild_id INT,module TEXT,enabled INT DEFAULT 1,PRIMARY KEY(guild_id,module));
CREATE TABLE IF NOT EXISTS night_roles(guild_id INT,role_id INT,PRIMARY KEY(guild_id,role_id));
"""); _db.commit()

_ID_DEF={
    "LOG_CHANNEL_ID":LOG_CHANNEL_ID,"WELCOME_CHANNEL_ID":WELCOME_CHANNEL_ID,"RULES_CHANNEL_ID":RULES_CHANNEL_ID,
    "TICKET_PANEL_CHANNEL_ID":TICKET_PANEL_CHANNEL_ID,"TICKET_CATEGORY_ID":TICKET_CATEGORY_ID,
    "SUPPORT_ROLE_ID":SUPPORT_ROLE_ID,"BOOST_CHANNEL_ID":BOOST_CHANNEL_ID,"COUNTING_CHANNEL_ID":COUNTING_CHANNEL_ID,
    "AUTO_ROLE_ID":AUTO_ROLE_ID,"TRIGGER_ROLE_ID":TRIGGER_ROLE_ID,"EXTRA_ROLE_ID_1":EXTRA_ROLE_ID_1,
    "EXTRA_ROLE_ID_2":EXTRA_ROLE_ID_2,"INVITE_CHANNEL_ID":INVITE_CHANNEL_ID,
    "ROLE_CMD_ALLOWED_ROLE_ID":ROLE_CMD_ALLOWED_ROLE_ID,"TIMEOUT_ROLE_ID":TIMEOUT_ROLE_ID,
    "CALL_VOICE_CHANNEL_ID":CALL_VOICE_CHANNEL_ID,
}
_MSG_DEF={
    "WELCOME_MSG":"Hey {mention},\n\nWillkommen auf **Corazon**!\nBitte lies dir die Regeln durch: <#{rules}>\n\n- Sei respektvoll\n- Hab Spaß!",
    "BOOST_MSG":"danke 🖤",
    "TICKET_PANEL_DESC":"Klicke auf den Button unten, um ein Support-Ticket zu öffnen.",
    "TICKET_OPEN_MSG":"Bitte beschreibe dein Anliegen. Unser Team wird dir in Kürze helfen.",
}
_MSG_LABELS={
    "WELCOME_MSG":"Willkommensnachricht ({mention} {rules})",
    "BOOST_MSG":"Boost-Nachricht",
    "TICKET_PANEL_DESC":"Ticket Panel Beschreibung",
    "TICKET_OPEN_MSG":"Nachricht beim Öffnen eines Tickets",
}

def _cid(g,k): _cur.execute("SELECT value FROM cfg_ids WHERE guild_id=? AND key=?",(g,k)); r=_cur.fetchone(); return r[0] if r else _ID_DEF.get(k,0)
def _sid(g,k,v):
    _cur.execute("INSERT INTO cfg_ids(guild_id,key,value)VALUES(?,?,?)ON CONFLICT(guild_id,key)DO UPDATE SET value=?",(g,k,v,v)); _db.commit()
    if k in globals(): globals()[k]=v
def _cmsg(g,k): _cur.execute("SELECT value FROM cfg_msgs WHERE guild_id=? AND key=?",(g,k)); r=_cur.fetchone(); return r[0] if r else _MSG_DEF.get(k,"")
def _smsg(g,k,v): _cur.execute("INSERT INTO cfg_msgs(guild_id,key,value)VALUES(?,?,?)ON CONFLICT(guild_id,key)DO UPDATE SET value=?",(g,k,v,v)); _db.commit()
def _sec(g,m): _cur.execute("SELECT enabled FROM sec_modules WHERE guild_id=? AND module=?",(g,m)); r=_cur.fetchone(); return r[0]==1 if r else True
def _ssec(g,m,e): _cur.execute("INSERT INTO sec_modules(guild_id,module,enabled)VALUES(?,?,?)ON CONFLICT(guild_id,module)DO UPDATE SET enabled=?",(g,m,int(e),int(e))); _db.commit()
def _inv_add(g,u,n=1): _cur.execute("INSERT INTO invites(guild_id,user_id,invites)VALUES(?,?,?)ON CONFLICT(guild_id,user_id)DO UPDATE SET invites=invites+?",(g,u,n,n)); _db.commit()
def _inv_get(g,u): _cur.execute("SELECT invites,left_invites,fake_invites FROM invites WHERE guild_id=? AND user_id=?",(g,u)); r=_cur.fetchone(); return r if r else (0,0,0)
def _inv_set(g,u,n): _cur.execute("INSERT INTO invites(guild_id,user_id,invites)VALUES(?,?,?)ON CONFLICT(guild_id,user_id)DO UPDATE SET invites=?",(g,u,n,n)); _db.commit()
def _inv_top(g,n=10): _cur.execute("SELECT user_id,invites,left_invites,fake_invites FROM invites WHERE guild_id=? ORDER BY invites DESC LIMIT ?",(g,n)); return _cur.fetchall()
def _warn_add(g,u,m,r): _cur.execute("INSERT INTO warns(guild_id,user_id,mod_id,reason,timestamp)VALUES(?,?,?,?,?)",(g,u,m,r,datetime.utcnow().isoformat())); _db.commit(); return _cur.lastrowid
def _warn_get(g,u): _cur.execute("SELECT id,mod_id,reason,timestamp FROM warns WHERE guild_id=? AND user_id=? ORDER BY id",(g,u)); return _cur.fetchall()
def _warn_del(w,g): _cur.execute("DELETE FROM warns WHERE id=? AND guild_id=?",(w,g)); _db.commit(); return _cur.rowcount>0
def _warn_clear(g,u): _cur.execute("DELETE FROM warns WHERE guild_id=? AND user_id=?",(g,u)); _db.commit(); return _cur.rowcount
def _cnt_save(g,c,l): _cur.execute("INSERT INTO counting(guild_id,current,last_user)VALUES(?,?,?)ON CONFLICT(guild_id)DO UPDATE SET current=?,last_user=?",(g,c,l,c,l)); _db.commit()
def _cnt_load(g): _cur.execute("SELECT current,last_user FROM counting WHERE guild_id=?",(g,)); r=_cur.fetchone(); return (r[0],r[1]) if r else (0,0)
def _tkt_num(g): _cur.execute("INSERT INTO ticket_counter(guild_id,counter)VALUES(?,1)ON CONFLICT(guild_id)DO UPDATE SET counter=counter+1",(g,)); _db.commit(); _cur.execute("SELECT counter FROM ticket_counter WHERE guild_id=?",(g,)); return _cur.fetchone()[0]
def _tkt_cur(g): _cur.execute("SELECT counter FROM ticket_counter WHERE guild_id=?",(g,)); r=_cur.fetchone(); return r[0] if r else 0
def _hb_add(g,u,m,r,a=""): _cur.execute("INSERT INTO hackbans(guild_id,user_id,mod_id,reason,alts)VALUES(?,?,?,?,?)ON CONFLICT(guild_id,user_id)DO UPDATE SET mod_id=?,reason=?,alts=?",(g,u,m,r,a,m,r,a)); _db.commit()
def _hb_del(g,u): _cur.execute("DELETE FROM hackbans WHERE guild_id=? AND user_id=?",(g,u)); _db.commit(); return _cur.rowcount>0
def _hb_get(g,u): _cur.execute("SELECT mod_id,reason,alts FROM hackbans WHERE guild_id=? AND user_id=?",(g,u)); return _cur.fetchone()
def _hb_all(g): _cur.execute("SELECT user_id,reason,alts FROM hackbans WHERE guild_id=?",(g,)); return _cur.fetchall()
def _hb_alt(g,u,alt):
    r=_hb_get(g,u)
    if not r: return
    alts=set(r[2].split(",")) if r[2] else set(); alts.add(str(alt))
    _cur.execute("UPDATE hackbans SET alts=? WHERE guild_id=? AND user_id=?",(",".join(filter(None,alts)),g,u)); _db.commit()

# Night mode role DB helpers
def _night_roles_get(g):
    _cur.execute("SELECT role_id FROM night_roles WHERE guild_id=?",(g,)); return [r[0] for r in _cur.fetchall()]
def _night_role_add(g,rid):
    _cur.execute("INSERT OR IGNORE INTO night_roles(guild_id,role_id)VALUES(?,?)",(g,rid)); _db.commit()
def _night_role_del(g,rid):
    _cur.execute("DELETE FROM night_roles WHERE guild_id=? AND role_id=?",(g,rid)); _db.commit(); return _cur.rowcount>0

# ================================================================
#  HELPERS
# ================================================================

def is_owner(uid): return uid in OWNERS
def can_mod(m):
    if m.id in OWNERS: return True
    return any(r.permissions.administrator or r.permissions.manage_messages for r in m.roles)
def can_role(m):
    if m.id in OWNERS: return True
    aid=_cid(m.guild.id,"ROLE_CMD_ALLOWED_ROLE_ID"); return any(r.id==aid for r in m.roles)
def can_timeout(m):
    if m.id in OWNERS: return True
    if can_mod(m): return True
    tid=_cid(m.guild.id,"TIMEOUT_ROLE_ID"); return tid!=0 and any(r.id==tid for r in m.roles)
def whitelisted(m):
    if not m: return False
    if getattr(m,"id",None) in OWNERS: return True
    if getattr(m,"id",None) in SECURITY_WHITELIST_USERS: return True
    if hasattr(m,"roles"):
        if any(r.id in SECURITY_WHITELIST_ROLES for r in m.roles): return True
        g=getattr(m,"guild",None)
        if g and g.me and m.top_role>=g.me.top_role: return True
    return False
def new_account(u,days=7): return (datetime.utcnow()-u.created_at.replace(tzinfo=None))<timedelta(days=days)
def parse_color(c:str)->discord.Color:
    return {"white":discord.Color.from_rgb(255,255,255),"red":discord.Color.from_rgb(220,50,50),
            "green":discord.Color.from_rgb(50,200,50),"blue":discord.Color.from_rgb(50,100,220)
            }.get(c.lower(),discord.Color.from_rgb(0,0,0))
def parse_time(s:str):
    if not s or s[-1].lower() not in "smhd" or not s[:-1].isdigit(): return None
    return int(s[:-1])*{"s":1,"m":60,"h":3600,"d":86400}[s[-1].lower()]
def eval_math(expr:str):
    import ast as _a
    if not re.fullmatch(r"[\d\s\+\-\*\/\(\)\.]+",expr.strip()): return None
    try:
        t=_a.parse(expr.strip(),mode="eval")
        ok=(_a.Expression,_a.BinOp,_a.UnaryOp,_a.Num,_a.Add,_a.Sub,_a.Mult,_a.Div,_a.FloorDiv,_a.Mod,_a.Pow,_a.UAdd,_a.USub,_a.Constant)
        for n in _a.walk(t):
            if not isinstance(n,ok): return None
        r=eval(compile(t,"<m>","eval"),{"__builtins__":{}},{})
        return int(r) if isinstance(r,(int,float)) and r==int(r) else None
    except: return None
async def audit(guild,action,tid=None):
    try:
        async for e in guild.audit_logs(limit=5,action=action):
            if tid is None or (e.target and e.target.id==tid): return e
    except: pass
    return None
async def mlog(guild,action,line):
    ch=guild.get_channel(_cid(guild.id,"LOG_CHANNEL_ID"))
    if not ch: return
    try:
        await ch.send(embed=discord.Embed(description=f"**{action}** — {line}",
            color=discord.Color.from_rgb(100,100,100),timestamp=datetime.utcnow()).set_footer(text="Security"))
    except: pass
async def clean(ctx,text,delay=4.0):
    msg=await ctx.send(text); await asyncio.sleep(delay)
    for m in(ctx.message,msg):
        try: await m.delete()
        except: pass
def find_role(guild,q):
    q=q.strip()
    if q.isdigit():
        r=guild.get_role(int(q)); return [r] if r else []
    ex=[r for r in guild.roles if r.name.lower()==q.lower()]
    return ex or [r for r in guild.roles if q.lower() in r.name.lower()]
def bot_can_act(guild, member):
    return guild.me and member.top_role < guild.me.top_role

# ================================================================
#  NIGHT MODE — Berlin Zeit
# ================================================================

async def do_night_off(guild):
    """Schaltet alle Night-Mode-Rollen aus (22:00 Berliner Zeit)."""
    role_ids = _night_roles_get(guild.id)
    if not role_ids:
        role_ids = NIGHT_MODE_ROLES
    changed = []
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if not role: continue
        _night_saved_perms[role.id] = role.permissions
        try:
            await role.edit(permissions=discord.Permissions.none(), reason="Night Mode — 22:00 Berliner Zeit")
            changed.append(role.name)
        except Exception: pass
    if changed:
        await mlog(guild, "🌙 Night Mode AN",
            f"Folgende Rollen wurden **deaktiviert**: {', '.join(f'`{n}`' for n in changed)}")

async def do_night_on(guild):
    """Stellt alle Night-Mode-Rollen wieder her (09:00 Berliner Zeit)."""
    role_ids = _night_roles_get(guild.id)
    if not role_ids:
        role_ids = NIGHT_MODE_ROLES
    changed = []
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if not role: continue
        saved = _night_saved_perms.get(role.id)
        if saved:
            try:
                await role.edit(permissions=saved, reason="Night Mode — 09:00 Berliner Zeit")
                changed.append(role.name)
            except Exception: pass
        else:
            changed.append(f"{role.name} (keine gespeicherten Berechtigungen)")
    if changed:
        await mlog(guild, "☀️ Night Mode AUS",
            f"Folgende Rollen wurden **wiederhergestellt**: {', '.join(f'`{n}`' for n in changed)}")

async def night_mode_loop():
    """Läuft jede Minute, prüft Berliner Zeit."""
    await bot.wait_until_ready()
    last_action: str | None = None
    while True:
        now_berlin = datetime.now(BERLIN_TZ)
        hour = now_berlin.hour

        action = None
        if hour == 22 and last_action != "off":
            action = "off"
        elif hour == 9 and last_action != "on":
            action = "on"

        if action:
            for guild in bot.guilds:
                if guild.id != ALLOWED_GUILD_ID: continue
                if action == "off":
                    await do_night_off(guild)
                else:
                    await do_night_on(guild)
            last_action = action

        await asyncio.sleep(60)

# ================================================================
#  SLASH — NIGHT MODE STEUERUNG
# ================================================================

class NightModeRoleSelect(discord.ui.Select):
    """Rollenliste zum Auswählen für Night Mode."""
    def __init__(self, guild: discord.Guild, action: str):
        self.action = action
        options = []
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if role.is_default(): continue
            options.append(discord.SelectOption(
                label=role.name[:100],
                value=str(role.id),
                description=f"ID: {role.id}"
            ))
        options = options[:25]
        super().__init__(
            placeholder="Rolle auswählen…",
            options=options,
            min_values=1,
            max_values=min(len(options), 10),
            custom_id="nm_role_sel"
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_roles = [int(v) for v in self.values]
        role_names = [interaction.guild.get_role(int(v)).name for v in self.values if interaction.guild.get_role(int(v))]
        await interaction.response.send_message(
            f"Ausgewählt: {', '.join(f'`{n}`' for n in role_names)}",
            ephemeral=True)


class NightModeManualView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=120)
        self.guild = guild
        self.selected_roles: list[int] = []

    @discord.ui.button(label="🌙 Jetzt ausschalten", style=discord.ButtonStyle.danger, row=0)
    async def turn_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNERS:
            return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await do_night_off(self.guild)
        await interaction.followup.send("✅ Night Mode wurde **aktiviert** (Rollen ausgeschaltet).", ephemeral=True)

    @discord.ui.button(label="☀️ Jetzt einschalten", style=discord.ButtonStyle.success, row=0)
    async def turn_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNERS:
            return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await do_night_on(self.guild)
        await interaction.followup.send("✅ Night Mode wurde **deaktiviert** (Rollen wiederhergestellt).", ephemeral=True)

    @discord.ui.button(label="➕ Rolle hinzufügen", style=discord.ButtonStyle.secondary, row=1)
    async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNERS:
            return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        sel = NightModeRoleSelect(interaction.guild, "add")
        view.add_item(sel)

        async def confirm_add(i2: discord.Interaction):
            for rid in sel.values:
                _night_role_add(i2.guild.id, int(rid))
            role_names = [i2.guild.get_role(int(r)).name for r in sel.values if i2.guild.get_role(int(r))]
            await i2.response.edit_message(
                content=f"✅ Hinzugefügt: {', '.join(f'`{n}`' for n in role_names)}", view=None)

        btn = discord.ui.Button(label="Bestätigen", style=discord.ButtonStyle.success)
        btn.callback = confirm_add
        view.add_item(btn)
        await interaction.response.send_message("Wähle Rolle(n) aus:", view=view, ephemeral=True)

    @discord.ui.button(label="➖ Rolle entfernen", style=discord.ButtonStyle.secondary, row=1)
    async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNERS:
            return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
        current_ids = _night_roles_get(interaction.guild.id) or NIGHT_MODE_ROLES
        options = []
        for rid in current_ids:
            role = interaction.guild.get_role(rid)
            if role:
                options.append(discord.SelectOption(label=role.name, value=str(rid)))
        if not options:
            return await interaction.response.send_message("Keine Night-Mode-Rollen gespeichert.", ephemeral=True)

        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="Rolle entfernen…", options=options, min_values=1, max_values=len(options))

        async def do_remove(i2: discord.Interaction):
            removed = []
            for rid in sel.values:
                if _night_role_del(i2.guild.id, int(rid)):
                    r = i2.guild.get_role(int(rid))
                    removed.append(r.name if r else rid)
            await i2.response.edit_message(
                content=f"✅ Entfernt: {', '.join(f'`{n}`' for n in removed)}", view=None)

        sel.callback = do_remove
        view.add_item(sel)
        await interaction.response.send_message("Wähle Rollen zum Entfernen:", view=view, ephemeral=True)

    @discord.ui.button(label="📋 Aktuelle Liste", style=discord.ButtonStyle.secondary, row=1)
    async def list_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_ids = _night_roles_get(interaction.guild.id) or NIGHT_MODE_ROLES
        lines = []
        for rid in current_ids:
            role = interaction.guild.get_role(rid)
            lines.append(f"• {role.mention if role else f'Unbekannte Rolle (`{rid}`)'}")
        embed = discord.Embed(
            title="🌙 Night Mode Rollen",
            description="\n".join(lines) if lines else "Keine Rollen konfiguriert.",
            color=discord.Color.from_rgb(50, 50, 100))
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="nightmode", description="Night Mode verwalten — Rollen aus/einschalten.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def nightmode_cmd(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
    current_ids = _night_roles_get(interaction.guild.id) or NIGHT_MODE_ROLES
    role_lines = []
    for rid in current_ids:
        role = interaction.guild.get_role(rid)
        role_lines.append(f"• {role.mention if role else f'`{rid}`'}")
    embed = discord.Embed(
        title="🌙 Night Mode Steuerung",
        description=(
            "**Aktuelle Night-Mode-Rollen:**\n" +
            ("\n".join(role_lines) if role_lines else "Keine") +
            "\n\n**22:00 Berliner Zeit** → Rollen werden deaktiviert\n"
            "**09:00 Berliner Zeit** → Rollen werden wiederhergestellt\n\n"
            "Nutze die Buttons um Night Mode manuell zu steuern oder Rollen zu ändern."
        ),
        color=discord.Color.from_rgb(50, 50, 100))
    view = NightModeManualView(interaction.guild)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ================================================================
#  READY / BACKGROUND TASKS
# ================================================================

async def setup_hook():
    bot.add_view(TicketButton()); bot.add_view(TicketActionView()); bot.add_view(TicketDeleteView())
bot.setup_hook=setup_hook

async def tracker_cleanup():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(10); now=datetime.utcnow()
        for t,w in[(timeout_tracker,15),(kick_tracker,20),(ban_tracker,20),(spam_tracker,SPAM_INTERVAL),
                   (mention_tracker,10),(invite_link_tracker,30),(mass_ping_tracker,5),
                   (channel_create_tracker,CREATE_WIN),(role_create_tracker,CREATE_WIN)]:
            dead=[uid for uid,ts in t.items() if not[x for x in ts if now-x<timedelta(seconds=w)]]
            for uid in dead: del t[uid]

async def voice_loop():
    await bot.wait_until_ready()
    while VOICE_ALWAYS_ON:
        try:
            ch=bot.get_channel(CALL_VOICE_CHANNEL_ID)
            if ch:
                vc=discord.utils.get(bot.voice_clients,guild=ch.guild)
                if vc is None:
                    try: await ch.connect()
                    except: pass
                elif not vc.is_connected():
                    try: await vc.disconnect()
                    except: pass
                    try: await ch.connect()
                    except: pass
        except: pass
        await asyncio.sleep(20)

@bot.event
async def on_invite_create(inv:discord.Invite):
    if inv.guild.id!=ALLOWED_GUILD_ID: return
    invite_cache.setdefault(inv.guild.id,{})[inv.code]=inv.uses
@bot.event
async def on_invite_delete(inv:discord.Invite):
    if inv.guild.id!=ALLOWED_GUILD_ID: return
    invite_cache.get(inv.guild.id,{}).pop(inv.code,None)

# ================================================================
#  MEMBER JOIN / LEAVE / UPDATE
# ================================================================

@bot.event
async def on_member_join(member:discord.Member):
    if member.guild.id!=ALLOWED_GUILD_ID: return
    row=_hb_get(member.guild.id,member.id)
    if row:
        try: await member.ban(reason=f"Hackban — {row[1]}")
        except: pass
        return
    for huid,_,halts in _hb_all(member.guild.id):
        if str(member.id) in [a for a in halts.split(",") if a]:
            try: await member.ban(reason=f"Hackban Alt von {huid}")
            except: pass
            return
    if _sec(member.guild.id,"new_account_warn") and new_account(member):
        await mlog(member.guild,"Neuer Account",f"{member} ({member.id}) — Account jünger als 7 Tage.")
    ar=member.guild.get_role(_cid(member.guild.id,"AUTO_ROLE_ID"))
    if ar:
        try: await member.add_roles(ar,reason="Auto Rolle")
        except: pass

    # Willkommensnachricht auf Deutsch
    wch=member.guild.get_channel(_cid(member.guild.id,"WELCOME_CHANNEL_ID"))
    if wch:
        try:
            raw=_cmsg(member.guild.id,"WELCOME_MSG")
            await wch.send(
                embed=discord.Embed(
                    description=raw.format(mention=member.mention,rules=_cid(member.guild.id,"RULES_CHANNEL_ID")),
                    color=discord.Color.from_rgb(149,165,166)),
                allowed_mentions=discord.AllowedMentions(users=True))
        except: pass

    # Einladungs-Tracking — auf Deutsch
    try:
        new_invs=await member.guild.invites(); old=invite_cache.get(member.guild.id,{})
        used=next((i for i in new_invs if i.uses>old.get(i.code,0)),None)
        invite_cache[member.guild.id]={i.code:i.uses for i in new_invs}
        ich=member.guild.get_channel(_cid(member.guild.id,"INVITE_CHANNEL_ID"))
        if ich:
            if used is None:
                emb=discord.Embed(
                    title=member.guild.name,
                    description=f"{member.mention} ist über den **Vanity-Link** beigetreten.",
                    color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
            elif used.inviter:
                _inv_add(member.guild.id,used.inviter.id); total,left,fake=_inv_get(member.guild.id,used.inviter.id)
                real=total-left-fake
                emb=discord.Embed(
                    title=member.guild.name,
                    description=(
                        f"{member.mention} ist dem Server beigetreten.\n"
                        f"Eingeladen von **{used.inviter.name}** — jetzt **{real} Einladung(en)**"
                    ),
                    color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
            else:
                emb=discord.Embed(
                    title=member.guild.name,
                    description=f"{member.mention} ist beigetreten. Einlader unbekannt.",
                    color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
            emb.set_thumbnail(url=member.display_avatar.url)
            await ich.send(embed=emb,allowed_mentions=discord.AllowedMentions(users=True))
    except: pass

@bot.event
async def on_member_remove(member:discord.Member):
    if member.guild.id!=ALLOWED_GUILD_ID: return
    try: invite_cache[member.guild.id]={i.code:i.uses for i in await member.guild.invites()}
    except: pass
    if not _sec(member.guild.id,"anti_mass_kick"): return
    await asyncio.sleep(0.3)
    e=await audit(member.guild,discord.AuditLogAction.kick,member.id)
    if not e or e.target.id!=member.id: return
    actor=e.user
    if not actor or whitelisted(member.guild.get_member(actor.id) or actor): return
    now=datetime.utcnow()
    kick_tracker[actor.id]=[t for t in kick_tracker[actor.id] if now-t<timedelta(seconds=20)]
    kick_tracker[actor.id].append(now)
    if len(kick_tracker[actor.id])>=2:
        try: await member.guild.ban(actor,reason="Massen-Kick (2+ in 20s)"); await mlog(member.guild,"Auto-Ban",f"{actor} ({actor.id}) hat 2+ Mitglieder in 20s gekickt — gebannt.")
        except: pass

@bot.event
async def on_member_update(before:discord.Member,after:discord.Member):
    if after.guild.id!=ALLOWED_GUILD_ID: return
    if not before.premium_since and after.premium_since:
        ch=after.guild.get_channel(_cid(after.guild.id,"BOOST_CHANNEL_ID"))
        if ch:
            try: await ch.send(_cmsg(after.guild.id,"BOOST_MSG"))
            except: pass
    b={r.id for r in before.roles}; a={r.id for r in after.roles}
    tr=_cid(after.guild.id,"TRIGGER_ROLE_ID")
    if tr and tr in a and tr not in b:
        for k in("EXTRA_ROLE_ID_1","EXTRA_ROLE_ID_2"):
            eid=_cid(after.guild.id,k)
            if not eid: continue
            ex=after.guild.get_role(eid)
            if ex and ex not in after.roles:
                try: await after.add_roles(ex,reason="Trigger Rolle")
                except: pass

# ================================================================
#  MESSAGES
# ================================================================

@bot.event
async def on_message(message:discord.Message):
    if message.author.bot: await bot.process_commands(message); return
    g=message.guild
    if not g or g.id!=ALLOWED_GUILD_ID: await bot.process_commands(message); return

    if message.channel.id==ACTIVITY_CHECK_CHANNEL_ID:
        if "@everyone" in message.content or "@here" in message.content:
            try: await message.delete()
            except: pass
            return

    if not whitelisted(message.author):
        now=datetime.utcnow()
        if _sec(g.id,"anti_spam"):
            spam_tracker[message.author.id].append(now)
            spam_tracker[message.author.id]=[t for t in spam_tracker[message.author.id] if now-t<timedelta(seconds=SPAM_INTERVAL)]
            if len(spam_tracker[message.author.id])>=SPAM_MAX:
                try:
                    until=discord.utils.utcnow()+timedelta(seconds=SPAM_TIMEOUT)
                    await message.author.timeout(until,reason="Spam")
                    def chk(m): return m.author.id==message.author.id
                    try: await message.channel.purge(limit=20,check=chk,bulk=True)
                    except: pass
                    await message.channel.send(f"{message.author.mention} Du wurdest wegen Spam stummgeschaltet.",delete_after=5)
                    spam_tracker[message.author.id].clear()
                    await mlog(g,"Auto-Timeout",f"{message.author} ({message.author.id}) wegen Spam stummgeschaltet.")
                except: pass
                return

        if _sec(g.id,"anti_mention"):
            has_mass_ping="@everyone" in message.content or "@here" in message.content
            total=len(set(u.id for u in message.mentions))+len(message.role_mentions)
            if has_mass_ping or total>=MENTION_MAX:
                mass_ping_tracker[message.author.id].append(now)
                mass_ping_tracker[message.author.id]=[t for t in mass_ping_tracker[message.author.id] if now-t<timedelta(seconds=5)]
                if len(mass_ping_tracker[message.author.id])>=2:
                    try:
                        await message.delete()
                        until=discord.utils.utcnow()+timedelta(minutes=10)
                        await message.author.timeout(until,reason="Massen-Ping Spam")
                        for role in message.author.roles:
                            if role.permissions.administrator:
                                try: await message.author.remove_roles(role,reason="Massen-Ping — Admin-Rolle entfernt")
                                except: pass
                        await message.channel.send(f"{message.author.mention} Du wurdest für 10 Minuten stummgeschaltet wegen Massen-Pings.",delete_after=8)
                        mass_ping_tracker[message.author.id].clear()
                        await mlog(g,"Massen-Ping",f"{message.author} ({message.author.id}) hat Massen-Pings gesendet — 10min Timeout + Admin-Rollen entfernt.")
                    except: pass
                    return
                else:
                    try: await message.delete()
                    except: pass
                    try: await message.channel.send(f"{message.author.mention} Massen-Pings sind hier nicht erlaubt.",delete_after=5)
                    except: pass
                    return

        if _sec(g.id,"anti_invite") and INVITE_RE.search(message.content):
            try: await message.delete()
            except: pass
            invite_link_tracker[message.author.id].append(now)
            invite_link_tracker[message.author.id]=[t for t in invite_link_tracker[message.author.id] if now-t<timedelta(seconds=30)]
            if len(invite_link_tracker[message.author.id])>=2:
                try:
                    until=discord.utils.utcnow()+timedelta(seconds=SPAM_TIMEOUT)
                    await message.author.timeout(until,reason="Einladungslink-Spam")
                    await message.channel.send(f"{message.author.mention} Du wurdest wegen Einladungslinks stummgeschaltet.",delete_after=5)
                    invite_link_tracker[message.author.id].clear()
                    await mlog(g,"Auto-Timeout",f"{message.author} ({message.author.id}) wegen Einladungslink-Spam stummgeschaltet.")
                except: pass
            else:
                try: await message.channel.send(f"{message.author.mention} Einladungslinks sind hier nicht erlaubt.",delete_after=5)
                except: pass
            return

    if message.channel.id in AUTO_REACT_CHANNEL_IDS:
        emoji="✅" if message.channel.id==ACTIVITY_CHECK_CHANNEL_ID else "✔️"
        try: await message.add_reaction(emoji)
        except: pass

    if COUNTING_CHANNEL_ID and message.channel.id==COUNTING_CHANNEL_ID:
        await handle_counting(message); return

    if message.author.id in afk_users:
        afk_users.pop(message.author.id)
        try: await message.channel.send(f"Willkommen zurück {message.author.mention}, dein AFK-Status wurde entfernt.",delete_after=5,allowed_mentions=discord.AllowedMentions(users=True))
        except: pass

    for u in message.mentions:
        if u.id in afk_users:
            r,ts=afk_users[u.id]
            try: await message.channel.send(f"**{u.name}** ist AFK seit <t:{int(ts.timestamp())}:R> — {r}",delete_after=8)
            except: pass

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message:discord.Message):
    if not message.guild or message.guild.id!=ALLOWED_GUILD_ID: return
    if COUNTING_CHANNEL_ID and message.channel.id==COUNTING_CHANNEL_ID:
        if message.author.bot: return
        try:
            n=await message.channel.send(f"Eine Nachricht wurde gelöscht. Nächste Zahl: **{counting_state['current']+1}**.")
            counting_state["delete_notice"]=n
        except: pass

async def handle_counting(message:discord.Message):
    c=message.content.strip(); expected=counting_state["current"]+1
    value=int(c) if c.lstrip("-").isdigit() else eval_math(c)
    if value is None:
        try: await message.delete()
        except: pass
        return
    if message.author.id==counting_state["last_user"]:
        try: await message.delete()
        except: pass
        try:
            n=await message.channel.send(f"{message.author.mention} Du kannst nicht zweimal hintereinander zählen.")
            await asyncio.sleep(2); await n.delete()
        except: pass
        return
    if value==expected:
        counting_state["current"]=expected; counting_state["last_user"]=message.author.id
        _cnt_save(message.guild.id,expected,message.author.id)
        if counting_state["delete_notice"]:
            try: await counting_state["delete_notice"].delete()
            except: pass
            counting_state["delete_notice"]=None
        try: await message.add_reaction("✔️")
        except: pass
    else:
        try:
            n=await message.channel.send(f"Falsch. Nächste Zahl: **{expected}**.")
            await asyncio.sleep(2); await n.delete()
        except: pass

@bot.event
async def on_reaction_add(reaction:discord.Reaction,user:discord.User):
    if user.bot: return
    if not reaction.message.guild or reaction.message.guild.id!=ALLOWED_GUILD_ID: return
    if reaction.message.channel.id!=ACTIVITY_CHECK_CHANNEL_ID: return
    mid=reaction.message.id
    if mid in first_react_announced: return
    first_react_announced.add(mid)
    try: await reaction.message.channel.send(f"{user.mention} war Erster!",allowed_mentions=discord.AllowedMentions(users=True))
    except: pass

# ================================================================
#  TICKET SYSTEM
# ================================================================

def is_ticket(ch)->bool:
    if not hasattr(ch,"guild"): return False
    return ch.category_id==_cid(ch.guild.id,"TICKET_CATEGORY_ID") and ch.name.startswith("ticket-")
def can_ticket(m)->bool:
    if m.id in OWNERS: return True
    sid=_cid(m.guild.id,"SUPPORT_ROLE_ID")
    return any(r.id==sid or r.permissions.administrator for r in m.roles)

class TicketActionView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Schließen",style=discord.ButtonStyle.secondary,custom_id="tkt_close")
    async def close_btn(self,interaction:discord.Interaction,button:Button):
        if not can_ticket(interaction.user): return await interaction.response.send_message("Du hast keine Berechtigung.",ephemeral=True)
        await interaction.response.defer()
        sr=interaction.guild.get_role(_cid(interaction.guild.id,"SUPPORT_ROLE_ID"))
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role,read_messages=False,send_messages=False)
            if sr: await interaction.channel.set_permissions(sr,read_messages=True,send_messages=True)
            await interaction.channel.send("Dieses Ticket wurde geschlossen. Nur Staff kann es noch sehen.")
        except Exception as e: await interaction.followup.send(f"Fehler: {e}",ephemeral=True)
    @discord.ui.button(label="Löschen",style=discord.ButtonStyle.danger,custom_id="tkt_delete")
    async def delete_btn(self,interaction:discord.Interaction,button:Button):
        if not can_ticket(interaction.user): return await interaction.response.send_message("Du hast keine Berechtigung.",ephemeral=True)
        await interaction.response.defer()
        try: await interaction.channel.send("Ticket wird gelöscht...")
        except: pass
        await asyncio.sleep(1)
        try: await interaction.channel.delete(reason=f"Gelöscht von {interaction.user}")
        except: pass

class TicketDeleteView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Löschen",style=discord.ButtonStyle.danger,custom_id="tkt_delete_v2")
    async def delete_btn(self,interaction:discord.Interaction,button:Button):
        if not can_ticket(interaction.user): return await interaction.response.send_message("Du hast keine Berechtigung.",ephemeral=True)
        await interaction.response.defer()
        try: await interaction.channel.send("Ticket wird gelöscht...")
        except: pass
        await asyncio.sleep(1)
        try: await interaction.channel.delete(reason=f"Gelöscht von {interaction.user}")
        except: pass

class TicketButton(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Ticket öffnen",style=discord.ButtonStyle.blurple,custom_id="tkt_create")
    async def create(self,interaction:discord.Interaction,button:Button):
        g=interaction.guild; cat=g.get_channel(_cid(g.id,"TICKET_CATEGORY_ID"))
        if cat:
            for ch in cat.text_channels:
                if ch.name.startswith("ticket-") and ch.overwrites_for(interaction.user).read_messages:
                    return await interaction.response.send_message(f"Du hast bereits ein offenes Ticket: {ch.mention}",ephemeral=True)
        num=_tkt_num(g.id); sr=g.get_role(_cid(g.id,"SUPPORT_ROLE_ID"))
        ow={g.default_role:discord.PermissionOverwrite(read_messages=False),
            interaction.user:discord.PermissionOverwrite(read_messages=True,send_messages=True)}
        if sr: ow[sr]=discord.PermissionOverwrite(read_messages=True,send_messages=True)
        for r in g.roles:
            if r.permissions.administrator and r not in ow: ow[r]=discord.PermissionOverwrite(read_messages=True,send_messages=True)
        try:
            tc=await g.create_text_channel(name=f"ticket-{num}",category=cat,overwrites=ow,reason=f"Ticket von {interaction.user}")
            open_msg = _cmsg(g.id, "TICKET_OPEN_MSG")
            embed=discord.Embed(
                title=f"Ticket #{num}",
                description=open_msg,
                color=discord.Color.from_rgb(149,165,166),
                timestamp=datetime.utcnow())
            pings=f"{sr.mention} {interaction.user.mention}" if sr else interaction.user.mention
            await tc.send(content=pings,embed=embed,view=TicketActionView(),
                allowed_mentions=discord.AllowedMentions(roles=True,users=True))
            await interaction.response.send_message(f"Dein Ticket wurde erstellt: {tc.mention}",ephemeral=True)
        except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.command()
async def close(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID or not is_ticket(ctx.channel): return
    if not can_ticket(ctx.author): return await ctx.send("Du hast keine Berechtigung.")
    try: await ctx.message.delete()
    except: pass
    sr=ctx.guild.get_role(_cid(ctx.guild.id,"SUPPORT_ROLE_ID"))
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role,read_messages=False,send_messages=False)
        if sr: await ctx.channel.set_permissions(sr,read_messages=True,send_messages=True)
        await ctx.send("Dieses Ticket wurde geschlossen. Nur Staff kann es noch sehen.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="delete")
async def delete_ticket(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID or not is_ticket(ctx.channel): return
    if not can_ticket(ctx.author): return await ctx.send("Du hast keine Berechtigung.")
    try: await ctx.message.delete()
    except: pass
    try: await ctx.send("Ticket wird gelöscht...")
    except: pass
    await asyncio.sleep(1)
    try: await ctx.channel.delete(reason=f"Gelöscht von {ctx.author}")
    except Exception as e: await ctx.send(f"Fehler: {e}")


# ================================================================
#  /setup — Ticket + alle Einstellungen (mit Channel/Rollen-Auswahl)
# ================================================================

class ChannelSelectSetup(discord.ui.ChannelSelect):
    """Universal Channel-Auswahl für Setup."""
    def __init__(self, key: str, label: str, channel_types=None):
        self.cfg_key = key
        types = channel_types or [discord.ChannelType.text]
        super().__init__(
            placeholder=f"{label} auswählen…",
            channel_types=types,
            min_values=1, max_values=1,
            custom_id=f"setup_ch_{key}")

    async def callback(self, interaction: discord.Interaction):
        ch = self.values[0]
        _sid(interaction.guild.id, self.cfg_key, ch.id)
        await interaction.response.send_message(
            f"✅ **{self.cfg_key}** gesetzt auf {ch.mention}", ephemeral=True)
        await mlog(interaction.guild, "Config", f"{interaction.user} setzte `{self.cfg_key}` auf #{ch.name} ({ch.id})")


class RoleSelectSetup(discord.ui.RoleSelect):
    """Universal Rollen-Auswahl für Setup."""
    def __init__(self, key: str, label: str):
        self.cfg_key = key
        super().__init__(
            placeholder=f"{label} auswählen…",
            min_values=1, max_values=1,
            custom_id=f"setup_role_{key}")

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        _sid(interaction.guild.id, self.cfg_key, role.id)
        await interaction.response.send_message(
            f"✅ **{self.cfg_key}** gesetzt auf {role.mention}", ephemeral=True)
        await mlog(interaction.guild, "Config", f"{interaction.user} setzte `{self.cfg_key}` auf {role.name} ({role.id})")


class CategorySelectSetup(discord.ui.ChannelSelect):
    """Kategorie-Auswahl für Setup."""
    def __init__(self, key: str, label: str):
        self.cfg_key = key
        super().__init__(
            placeholder=f"{label} auswählen…",
            channel_types=[discord.ChannelType.category],
            min_values=1, max_values=1,
            custom_id=f"setup_cat_{key}")

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        _sid(interaction.guild.id, self.cfg_key, cat.id)
        await interaction.response.send_message(
            f"✅ **{self.cfg_key}** gesetzt auf Kategorie `{cat.name}`", ephemeral=True)
        await mlog(interaction.guild, "Config", f"{interaction.user} setzte `{self.cfg_key}` auf Kategorie {cat.name} ({cat.id})")


class TextEditModal(discord.ui.Modal):
    def __init__(self, key: str, label: str, current: str):
        super().__init__(title=f"{label} bearbeiten")
        self.key = key
        self.field = discord.ui.TextInput(
            label=label[:45],
            style=discord.TextStyle.paragraph,
            default=current[:4000],
            max_length=4000)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        _smsg(interaction.guild.id, self.key, self.field.value)
        await interaction.response.send_message(
            f"✅ **{self.key}** wurde aktualisiert.", ephemeral=True)


class SetupView(discord.ui.View):
    """Haupt-Setup-Menü — öffentlich gesendet, nach Einstellung automatisch gelöscht."""
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

    # ── Kanal-Buttons ──────────────────────────────────────────
    @discord.ui.button(label="📋 Panel-Kanal", style=discord.ButtonStyle.secondary, row=0)
    async def set_panel_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(ChannelSelectSetup("TICKET_PANEL_CHANNEL_ID", "Panel-Kanal"))
        await interaction.response.send_message("Wähle den Panel-Kanal:", view=view, ephemeral=True)

    @discord.ui.button(label="📁 Ticket-Kategorie", style=discord.ButtonStyle.secondary, row=0)
    async def set_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(CategorySelectSetup("TICKET_CATEGORY_ID", "Ticket-Kategorie"))
        await interaction.response.send_message("Wähle die Ticket-Kategorie:", view=view, ephemeral=True)

    @discord.ui.button(label="👥 Support-Rolle", style=discord.ButtonStyle.secondary, row=0)
    async def set_support_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(RoleSelectSetup("SUPPORT_ROLE_ID", "Support-Rolle"))
        await interaction.response.send_message("Wähle die Support-Rolle:", view=view, ephemeral=True)

    @discord.ui.button(label="📝 Panel-Text bearbeiten", style=discord.ButtonStyle.secondary, row=1)
    async def edit_panel_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = _cmsg(interaction.guild.id, "TICKET_PANEL_DESC")
        await interaction.response.send_modal(TextEditModal("TICKET_PANEL_DESC", "Panel-Beschreibung", current))

    @discord.ui.button(label="💬 Ticket-Öffnen-Text", style=discord.ButtonStyle.secondary, row=1)
    async def edit_open_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = _cmsg(interaction.guild.id, "TICKET_OPEN_MSG")
        await interaction.response.send_modal(TextEditModal("TICKET_OPEN_MSG", "Ticket-Öffnen-Nachricht", current))

    @discord.ui.button(label="🌍 Willkommens-Text", style=discord.ButtonStyle.secondary, row=1)
    async def edit_welcome_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = _cmsg(interaction.guild.id, "WELCOME_MSG")
        await interaction.response.send_modal(TextEditModal("WELCOME_MSG", "Willkommensnachricht", current))

    @discord.ui.button(label="🏠 Willkommens-Kanal", style=discord.ButtonStyle.secondary, row=2)
    async def set_welcome_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(ChannelSelectSetup("WELCOME_CHANNEL_ID", "Willkommens-Kanal"))
        await interaction.response.send_message("Wähle den Willkommens-Kanal:", view=view, ephemeral=True)

    @discord.ui.button(label="📜 Regeln-Kanal", style=discord.ButtonStyle.secondary, row=2)
    async def set_rules_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(ChannelSelectSetup("RULES_CHANNEL_ID", "Regeln-Kanal"))
        await interaction.response.send_message("Wähle den Regeln-Kanal:", view=view, ephemeral=True)

    @discord.ui.button(label="📊 Log-Kanal", style=discord.ButtonStyle.secondary, row=2)
    async def set_log_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(ChannelSelectSetup("LOG_CHANNEL_ID", "Log-Kanal"))
        await interaction.response.send_message("Wähle den Log-Kanal:", view=view, ephemeral=True)

    @discord.ui.button(label="🎫 Panel senden & Setup schließen", style=discord.ButtonStyle.primary, row=3)
    async def send_panel_and_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNERS:
            return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
        ch = interaction.guild.get_channel(_cid(interaction.guild.id, "TICKET_PANEL_CHANNEL_ID"))
        if not ch:
            return await interaction.response.send_message("Panel-Kanal nicht gefunden. Bitte zuerst einstellen.", ephemeral=True)
        panel_desc = _cmsg(interaction.guild.id, "TICKET_PANEL_DESC")
        embed = discord.Embed(
            title="Support",
            description=panel_desc,
            color=discord.Color.from_rgb(149, 165, 166))
        try:
            await ch.send(embed=embed, view=TicketButton())
            await interaction.response.send_message(
                f"✅ Panel wurde in {ch.mention} gesendet.", ephemeral=True)
            # Setup-Nachricht automatisch löschen
            await asyncio.sleep(2)
            try:
                await interaction.message.delete()
            except: pass
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)

    @discord.ui.button(label="📈 Ticket-Statistik", style=discord.ButtonStyle.secondary, row=3)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        total = _tkt_cur(interaction.guild.id)
        cat = interaction.guild.get_channel(_cid(interaction.guild.id, "TICKET_CATEGORY_ID"))
        open_t = len([c for c in cat.text_channels if c.name.startswith("ticket-")]) if cat else 0
        embed = discord.Embed(
            title="Ticket-Statistik",
            description=f"Gesamt erstellt: **{total}**\nAktuell offen: **{open_t}**\nNächste Nummer: **{total+1}**",
            color=discord.Color.from_rgb(149, 165, 166))
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setup", description="Bot-Einstellungen & Ticket-System konfigurieren.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def setup_cmd(interaction: discord.Interaction):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)

    g = interaction.guild
    cat_id   = _cid(g.id, "TICKET_CATEGORY_ID")
    panel_id = _cid(g.id, "TICKET_PANEL_CHANNEL_ID")
    sr_id    = _cid(g.id, "SUPPORT_ROLE_ID")
    wch_id   = _cid(g.id, "WELCOME_CHANNEL_ID")
    log_id   = _cid(g.id, "LOG_CHANNEL_ID")

    embed = discord.Embed(
        title="⚙️ Bot Setup",
        description=(
            f"**Ticket-Kategorie:** <#{cat_id}> (`{cat_id}`)\n"
            f"**Panel-Kanal:** <#{panel_id}> (`{panel_id}`)\n"
            f"**Support-Rolle:** <@&{sr_id}> (`{sr_id}`)\n"
            f"**Willkommens-Kanal:** <#{wch_id}> (`{wch_id}`)\n"
            f"**Log-Kanal:** <#{log_id}> (`{log_id}`)\n"
            f"**Tickets gesamt:** {_tkt_cur(g.id)}\n\n"
            "Nutze die Buttons um Einstellungen zu ändern.\n"
            "Diese Nachricht wird nach dem Senden des Panels automatisch gelöscht."
        ),
        color=discord.Color.from_rgb(149, 165, 166))

    # Öffentlich senden (nicht ephemeral) — wird nach Panel-Senden auto gelöscht
    await interaction.response.send_message(embed=embed, view=SetupView(g.id))


@bot.tree.command(name="adduser", description="Benutzer zum aktuellen Ticket hinzufügen.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def adduser(interaction:discord.Interaction, member:discord.Member):
    if not is_ticket(interaction.channel): return await interaction.response.send_message("Nur in Ticket-Kanälen nutzbar.",ephemeral=True)
    if not can_ticket(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    try:
        await interaction.channel.set_permissions(member,read_messages=True,send_messages=True)
        await interaction.response.send_message(f"{member.mention} wurde zum Ticket hinzugefügt.")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="removeuser", description="Benutzer aus dem aktuellen Ticket entfernen.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def removeuser(interaction:discord.Interaction, member:discord.Member):
    if not is_ticket(interaction.channel): return await interaction.response.send_message("Nur in Ticket-Kanälen nutzbar.",ephemeral=True)
    if not can_ticket(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    try:
        await interaction.channel.set_permissions(member,overwrite=None)
        await interaction.response.send_message(f"{member.mention} wurde aus dem Ticket entfernt.")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="renameticket", description="Aktuelles Ticket umbenennen.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def renameticket(interaction:discord.Interaction, name:str):
    if not is_ticket(interaction.channel): return await interaction.response.send_message("Nur in Ticket-Kanälen nutzbar.",ephemeral=True)
    if not can_ticket(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    name=name.lower().replace(" ","-")[:50]
    try:
        await interaction.channel.edit(name=f"ticket-{name}")
        await interaction.response.send_message(f"Ticket umbenannt zu **ticket-{name}**.")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Ticket-Panel in den konfigurierten Kanal senden.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def ticketpanel(interaction:discord.Interaction):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    ch=interaction.guild.get_channel(_cid(interaction.guild.id,"TICKET_PANEL_CHANNEL_ID"))
    if not ch: return await interaction.response.send_message("Panel-Kanal nicht gefunden.",ephemeral=True)
    panel_desc = _cmsg(interaction.guild.id, "TICKET_PANEL_DESC")
    embed=discord.Embed(title="Support",description=panel_desc,color=discord.Color.from_rgb(149,165,166))
    try:
        await ch.send(embed=embed,view=TicketButton())
        await interaction.response.send_message(f"Panel wurde in {ch.mention} gesendet.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

# ================================================================
#  MODERATION — PREFIX COMMANDS
# ================================================================

@bot.command()
async def kick(ctx:commands.Context,member:discord.Member=None,*,reason:str="Kein Grund angegeben"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?kick @user [Grund]`")
    if member.id in OWNERS: return await clean(ctx,"Du kannst keinen Owner kicken.")
    if member.top_role>=ctx.guild.me.top_role: return await clean(ctx,"Dieses Mitglied hat eine höhere Rolle als ich.")
    try:
        await member.kick(reason=f"{ctx.author}: {reason}")
        await ctx.send(f"**{member}** wurde von **{ctx.author.name}** gekickt. | {reason}")
        await mlog(ctx.guild,"Kick",f"{ctx.author} hat {member} ({member.id}) gekickt. Grund: {reason}")
    except discord.Forbidden: await ctx.send("Ich habe keine Berechtigung dafür.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command()
async def ban(ctx:commands.Context,member:discord.Member=None,*,reason:str="Kein Grund angegeben"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?ban @user [Grund]`")
    if member.id in OWNERS: return await clean(ctx,"Du kannst keinen Owner bannen.")
    if member.top_role>=ctx.guild.me.top_role: return await clean(ctx,"Dieses Mitglied hat eine höhere Rolle als ich.")
    try:
        await member.ban(reason=f"{ctx.author}: {reason}",delete_message_days=1)
        await ctx.send(f"**{member}** wurde von **{ctx.author.name}** gebannt. | {reason}")
        await mlog(ctx.guild,"Ban",f"{ctx.author} hat {member} ({member.id}) gebannt. Grund: {reason}")
    except discord.Forbidden: await ctx.send("Ich habe keine Berechtigung dafür.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command()
async def unban(ctx:commands.Context,user_id:str=None,*,reason:str="Kein Grund angegeben"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not user_id or not user_id.isdigit(): return await clean(ctx,"Verwendung: `?unban <UserID> [Grund]`")
    try:
        user=await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user,reason=f"{ctx.author}: {reason}")
        await ctx.send(f"**{user}** wurde entbannt.")
        await mlog(ctx.guild,"Unban",f"{ctx.author} hat {user} ({user.id}) entbannt.")
    except discord.NotFound: await ctx.send("Benutzer nicht gefunden oder nicht gebannt.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(aliases=["to"])
async def timeout(ctx:commands.Context,member:discord.Member=None,duration:str=None,*,reason:str="Kein Grund angegeben"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_timeout(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member or not duration: return await clean(ctx,"Verwendung: `?timeout @user <Zeit> [Grund]` — z.B. 10m, 2h, 1d")
    secs=parse_time(duration)
    if secs is None: return await clean(ctx,"Ungültige Zeit. Beispiele: `10m`, `2h`, `1d`")
    if secs>2419200: return await clean(ctx,"Maximaler Timeout beträgt 28 Tage.")
    try:
        until=discord.utils.utcnow()+timedelta(seconds=secs)
        await member.timeout(until,reason=f"{ctx.author}: {reason}")
        await ctx.send(f"**{member}** wurde für **{duration}** stummgeschaltet. | {reason}")
        await mlog(ctx.guild,"Timeout",f"{ctx.author} hat {member} ({member.id}) für {duration} stummgeschaltet.")
    except discord.Forbidden: await ctx.send("Ich habe keine Berechtigung dafür.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="rto")
async def rto(ctx:commands.Context,member:discord.Member=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_timeout(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?rto @user`")
    try:
        await member.timeout(None,reason=f"Timeout entfernt von {ctx.author}")
        await ctx.send(f"Timeout für **{member}** wurde aufgehoben.")
        await mlog(ctx.guild,"Timeout entfernt",f"{ctx.author} hat Timeout von {member} ({member.id}) aufgehoben.")
    except discord.Forbidden: await ctx.send("Ich habe keine Berechtigung dafür.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command()
async def warn(ctx:commands.Context,member:discord.Member=None,*,reason:str="Kein Grund angegeben"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?warn @user [Grund]`")
    wid=_warn_add(ctx.guild.id,member.id,ctx.author.id,reason); wl=_warn_get(ctx.guild.id,member.id)
    await ctx.send(f"**{member}** wurde verwarnt (#{wid}, gesamt: {len(wl)}). | {reason}")
    await mlog(ctx.guild,"Verwarnung",f"{ctx.author} hat {member} ({member.id}) verwarnt — #{wid}. {reason}")
    try:
        await member.send(embed=discord.Embed(title=f"Verwarnung — {ctx.guild.name}",
            description=f"**Grund:** {reason}\n**Verwarnung #{wid}** — Gesamt: {len(wl)}",
            color=discord.Color.yellow(),timestamp=datetime.utcnow()))
    except: pass

@bot.command()
async def warns(ctx:commands.Context,member:discord.Member=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?warns @user`")
    wl=_warn_get(ctx.guild.id,member.id)
    embed=discord.Embed(title=f"Verwarnungen — {member}",color=discord.Color.yellow(),timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    if not wl: embed.description="Keine Verwarnungen eingetragen."
    else:
        for wid,mid,r,ts in wl:
            m=ctx.guild.get_member(mid)
            embed.add_field(name=f"#{wid} — {ts[:10]}",value=f"**Grund:** {r}\n**Mod:** {str(m) if m else mid}",inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def clearwarn(ctx:commands.Context,warn_id:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not warn_id or not warn_id.isdigit(): return await clean(ctx,"Verwendung: `?clearwarn <ID>`")
    if _warn_del(int(warn_id),ctx.guild.id): await ctx.send(f"Verwarnung **#{warn_id}** wurde entfernt.",delete_after=5)
    else: await ctx.send(f"Verwarnung **#{warn_id}** nicht gefunden.",delete_after=5)

@bot.command()
async def clearwarns(ctx:commands.Context,member:discord.Member=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?clearwarns @user`")
    n=_warn_clear(ctx.guild.id,member.id)
    await ctx.send(f"**{n}** Verwarnung(en) für {member.mention} gelöscht.",delete_after=5)

@bot.command()
async def purge(ctx:commands.Context,amount:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    try: await ctx.message.delete()
    except: pass
    if not amount: return await ctx.send("Verwendung: `?purge all` oder `?purge <Anzahl>`",delete_after=3)
    if amount.lower()=="all": deleted=await ctx.channel.purge(limit=None)
    else:
        if not amount.isdigit() or int(amount)<1: return await ctx.send("Ungültige Anzahl.",delete_after=3)
        if int(amount)>1000: return await ctx.send("Maximum sind 1000 Nachrichten.",delete_after=3)
        deleted=await ctx.channel.purge(limit=int(amount))
    n=await ctx.send(f"{len(deleted)} Nachricht(en) gelöscht."); await asyncio.sleep(3)
    try: await n.delete()
    except: pass

@bot.command(name="slowmode")
async def slowmode_cmd(ctx:commands.Context,seconds:int=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if seconds is None: return await clean(ctx,"Verwendung: `?slowmode <Sekunden>` (0 zum Deaktivieren)")
    if seconds<0 or seconds>21600: return await clean(ctx,"Wert muss zwischen 0 und 21600 liegen.")
    try:
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.send("Slowmode deaktiviert." if seconds==0 else f"Slowmode auf **{seconds}s** gesetzt.",delete_after=5)
        try: await ctx.message.delete()
        except: pass
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ================================================================
#  ROLES — PREFIX
# ================================================================

_PERMS_LIST=["administrator","manage_guild","manage_roles","manage_channels","manage_messages",
    "manage_nicknames","kick_members","ban_members","moderate_members","view_audit_log",
    "mention_everyone","send_messages","read_messages","attach_files","embed_links",
    "add_reactions","use_external_emojis","connect","speak","move_members",
    "mute_members","deafen_members","create_instant_invite"]

class RoleCreateView(discord.ui.View):
    def __init__(self,ctx,name,color,hoist):
        super().__init__(timeout=120); self.ctx=ctx; self.name=name; self.color=color; self.hoist=hoist; self.chosen=set()
        options=[discord.SelectOption(label=p.replace("_"," ").title(),value=p) for p in _PERMS_LIST]
        sel=discord.ui.Select(placeholder="Berechtigungen auswählen (optional)…",options=options,min_values=0,max_values=len(options),custom_id="rc_perms")
        sel.callback=self.perms_cb; self.add_item(sel)
    async def perms_cb(self,interaction:discord.Interaction): self.chosen=set(interaction.data["values"]); await interaction.response.defer()
    @discord.ui.button(label="Rolle erstellen",style=discord.ButtonStyle.success,row=1)
    async def confirm(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.ctx.author.id: return await interaction.response.send_message("Dieses Menü ist nicht für dich.",ephemeral=True)
        perms=discord.Permissions()
        for p in self.chosen:
            if hasattr(perms,p): setattr(perms,p,True)
        try:
            role=await interaction.guild.create_role(name=self.name,permissions=perms,color=self.color,hoist=self.hoist,reason=f"?rolecreate von {interaction.user}")
            for ch in interaction.guild.channels:
                try:
                    if ch.overwrites_for(role).is_empty():
                        await ch.set_permissions(role,view_channel=True,reason="Rolle erstellt — Standard-Berechtigung")
                except: pass
            await interaction.response.edit_message(content=f"Rolle **{role.name}** wurde erstellt ({role.mention}) mit {len(self.chosen)} Berechtigung(en).",view=None)
            await mlog(interaction.guild,"Rolle erstellt",f"{interaction.user} hat **{role.name}** erstellt. Berechtigungen: {', '.join(self.chosen) or 'keine'}")
        except Exception as e: await interaction.response.edit_message(content=f"Fehler: {e}",view=None)
    @discord.ui.button(label="Abbrechen",style=discord.ButtonStyle.danger,row=1)
    async def cancel(self,interaction:discord.Interaction,button:discord.ui.Button): await interaction.response.edit_message(content="Abgebrochen.",view=None)

@bot.command(name="role")
async def role_cmd(ctx:commands.Context,member:discord.Member=None,*,role_input:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_role(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member or not role_input: return await clean(ctx,"Verwendung: `?role @user <Rollenname oder ID>`")
    matches=find_role(ctx.guild,role_input)
    if not matches: return await clean(ctx,f"Keine Rolle gefunden: **{role_input}**.")
    if len(matches)>1: return await clean(ctx,f"Mehrere Rollen gefunden: {', '.join(f'`{r.name}`' for r in matches[:6])} — bitte genauer angeben.",delay=6)
    role=matches[0]
    if role>=ctx.guild.me.top_role: return await clean(ctx,"Diese Rolle ist höher als oder gleich meiner höchsten Rolle.")
    if role.permissions.administrator and ctx.author.id not in OWNERS:
        return await clean(ctx,"Du kannst keine Administrator-Rollen zuweisen.")
    if role>=ctx.author.top_role and ctx.author.id not in OWNERS:
        return await clean(ctx,"Du kannst keine Rolle zuweisen, die gleich oder höher als deine eigene ist.")
    try:
        if role in member.roles:
            await member.remove_roles(role,reason=f"?role von {ctx.author}")
            await ctx.send(f"**{role.name}** von {member.mention} entfernt.")
        else:
            await member.add_roles(role,reason=f"?role von {ctx.author}")
            await ctx.send(f"**{role.name}** an {member.mention} vergeben.")
    except discord.Forbidden: await ctx.send("Ich habe keine Berechtigung für diese Rolle.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="roleall")
async def roleall_cmd(ctx:commands.Context,role:discord.Role=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not role: return await clean(ctx,"Verwendung: `?roleall @role`")
    if role>=ctx.guild.me.top_role: return await clean(ctx,"Diese Rolle ist höher als oder gleich meiner höchsten Rolle.")
    if role.permissions.administrator and ctx.author.id not in OWNERS: return await clean(ctx,"Nur Owner können Admin-Rollen massenweise zuweisen.")
    msg=await ctx.send(f"Weise **{role.name}** allen Mitgliedern zu…"); count=0
    for m in ctx.guild.members:
        if m.bot or role in m.roles: continue
        try: await m.add_roles(role,reason=f"?roleall von {ctx.author}"); count+=1
        except: pass
        await asyncio.sleep(0.3)
    await msg.edit(content=f"Fertig. **{role.name}** an **{count}** Mitglied(er) vergeben.")
    await mlog(ctx.guild,"Rolle an alle",f"{ctx.author} hat **{role.name}** an {count} Mitglieder vergeben.")

@bot.command(name="rolecreate")
async def rolecreate_cmd(ctx:commands.Context,role_name:str=None,color_hex:str="#000000",hoist:str="no"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not role_name: return await clean(ctx,"Verwendung: `?rolecreate <Name> [#Farbe] [ja/nein]`")
    try:
        c=color_hex.lstrip("#"); color=discord.Color.from_rgb(int(c[0:2],16),int(c[2:4],16),int(c[4:6],16))
    except: color=discord.Color.default()
    view=RoleCreateView(ctx,role_name,color,hoist.lower() in("yes","ja","true","1"))
    await ctx.send(f"Berechtigungen für **{role_name}** auswählen:",view=view)

@bot.command(name="roleinfo")
async def roleinfo_cmd(ctx:commands.Context,*,role_input:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not role_input: return await clean(ctx,"Verwendung: `?roleinfo <Rollenname oder ID>`")
    matches=find_role(ctx.guild,role_input)
    if not matches: return await clean(ctx,"Keine Rolle gefunden.")
    r=matches[0]; perms=[p.replace("_"," ").title() for p,v in r.permissions if v]
    embed=discord.Embed(title=r.name,color=r.color if r.color.value else discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.add_field(name="ID",value=r.id,inline=True); embed.add_field(name="Farbe",value=str(r.color),inline=True)
    embed.add_field(name="Mitglieder",value=str(len(r.members)),inline=True); embed.add_field(name="Erwähnbar",value="Ja" if r.mentionable else "Nein",inline=True)
    embed.add_field(name="Angeheftet",value="Ja" if r.hoist else "Nein",inline=True); embed.add_field(name="Erstellt",value=f"<t:{int(r.created_at.timestamp())}:R>",inline=True)
    embed.add_field(name="Berechtigungen",value=", ".join(perms[:20]) if perms else "Keine",inline=False)
    await ctx.send(embed=embed)

# ================================================================
#  HACKBAN — PREFIX
# ================================================================

@bot.command()
async def hackban(ctx:commands.Context,member:discord.Member=None,*,reason:str="Kein Grund angegeben"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not member: return await clean(ctx,"Verwendung: `?hackban @user [Grund]`")
    if member.id in OWNERS: return await clean(ctx,"Du kannst keinen Owner hackkbannen.")
    try:
        await ctx.guild.ban(member,reason=f"Hackban von {ctx.author}: {reason}",delete_message_days=1)
        _hb_add(ctx.guild.id,member.id,ctx.author.id,reason)
        await ctx.send(f"**{member}** wurde hackgebannt. | {reason}")
        await mlog(ctx.guild,"Hackban",f"{ctx.author} hat {member} ({member.id}) hackgebannt. Grund: {reason}")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command()
async def hackban_addalt(ctx:commands.Context,main_id:str=None,alt_id:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not main_id or not alt_id or not main_id.isdigit() or not alt_id.isdigit(): return await clean(ctx,"Verwendung: `?hackban_addalt <HauptID> <AltID>`")
    if not _hb_get(ctx.guild.id,int(main_id)): return await ctx.send("Kein Hackban für diese ID gefunden.")
    _hb_alt(ctx.guild.id,int(main_id),int(alt_id))
    try:
        await ctx.guild.ban(discord.Object(id=int(alt_id)),reason=f"Hackban-Alt von {main_id}")
        await ctx.send(f"Alt `{alt_id}` wurde gebannt und mit `{main_id}` verknüpft.")
        await mlog(ctx.guild,"Hackban Alt",f"{ctx.author} hat Alt {alt_id} mit Hackban {main_id} verknüpft.")
    except Exception as e: await ctx.send(f"Alt verknüpft. Ban fehlgeschlagen: {e}")

@bot.command()
async def unhackban(ctx:commands.Context,user_id:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    if not user_id or not user_id.isdigit(): return await clean(ctx,"Verwendung: `?unhackban <UserID>`")
    uid=int(user_id); _hb_del(ctx.guild.id,uid)
    try:
        await ctx.guild.unban(discord.Object(id=uid),reason=f"Unhackban von {ctx.author}")
        await ctx.send(f"Hackban für `{user_id}` wurde aufgehoben.")
        await mlog(ctx.guild,"Unhackban",f"{ctx.author} hat Hackban für {user_id} aufgehoben.")
    except discord.NotFound: await ctx.send("Eintrag entfernt. Benutzer war nicht mehr gebannt.")
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="unbanall")
async def unbanall_cmd(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"Du hast keine Berechtigung.")
    msg=await ctx.send("Alle Benutzer werden entbannt…"); count=0
    async for entry in ctx.guild.bans():
        try: await ctx.guild.unban(entry.user,reason=f"?unbanall von {ctx.author}"); count+=1
        except: pass
        await asyncio.sleep(0.3)
    await msg.edit(content=f"Fertig. **{count}** Benutzer entbannt.")
    await mlog(ctx.guild,"Alle entbannt",f"{ctx.author} hat alle {count} Benutzer entbannt.")

@bot.command()
async def setcount(ctx:commands.Context,number:int=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not is_owner(ctx.author.id): return await clean(ctx,"Du hast keine Berechtigung.")
    if number is None: return await clean(ctx,"Verwendung: `?setcount <Zahl>`")
    counting_state["current"]=number; counting_state["last_user"]=None
    _cnt_save(ctx.guild.id,number,0)
    await ctx.send(f"Zähler auf **{number}** gesetzt.",delete_after=5)
    try: await ctx.message.delete()
    except: pass

@bot.command()
async def call(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID or not is_owner(ctx.author.id): return
    ch=bot.get_channel(CALL_VOICE_CHANNEL_ID)
    try:
        vc=ctx.voice_client
        if vc and vc.is_connected(): await vc.move_to(ch)
        else: await ch.connect()
        await ctx.send("Verbunden.",delete_after=3)
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ================================================================
#  SLASH — PUBLIC
# ================================================================

@bot.tree.command(name="avatar",description="Avatar eines Benutzers anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def avatar(interaction:discord.Interaction,member:discord.Member=None):
    m=member or interaction.user
    embed=discord.Embed(title=str(m),color=discord.Color.from_rgb(149,165,166))
    embed.set_image(url=m.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo",description="Informationen über den Server anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def serverinfo(interaction:discord.Interaction):
    g=interaction.guild
    embed=discord.Embed(title=g.name,color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    if g.icon: embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="ID",value=g.id,inline=True); embed.add_field(name="Inhaber",value=f"<@{g.owner_id}>",inline=True)
    embed.add_field(name="Erstellt",value=f"<t:{int(g.created_at.timestamp())}:R>",inline=True)
    embed.add_field(name="Mitglieder",value=g.member_count,inline=True); embed.add_field(name="Rollen",value=len(g.roles),inline=True)
    embed.add_field(name="Kanäle",value=len(g.channels),inline=True); embed.add_field(name="Boosts",value=g.premium_subscription_count,inline=True)
    embed.add_field(name="Boost-Level",value=g.premium_tier,inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roleinfo",description="Informationen über eine Rolle anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_roleinfo(interaction:discord.Interaction,role:discord.Role):
    perms=[p.replace("_"," ").title() for p,v in role.permissions if v]
    embed=discord.Embed(title=role.name,color=role.color if role.color.value else discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.add_field(name="ID",value=role.id,inline=True); embed.add_field(name="Farbe",value=str(role.color),inline=True)
    embed.add_field(name="Mitglieder",value=str(len(role.members)),inline=True); embed.add_field(name="Erwähnbar",value="Ja" if role.mentionable else "Nein",inline=True)
    embed.add_field(name="Angeheftet",value="Ja" if role.hoist else "Nein",inline=True); embed.add_field(name="Erstellt",value=f"<t:{int(role.created_at.timestamp())}:R>",inline=True)
    embed.add_field(name="Berechtigungen",value=", ".join(perms[:20]) if perms else "Keine",inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="invite",description="Einladungsanzahl eines Benutzers anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def invite_cmd(interaction:discord.Interaction,member:discord.Member):
    total,left,fake=_inv_get(interaction.guild.id,member.id); real=total-left-fake
    embed=discord.Embed(color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.set_author(name=f"Einladungen von {member.name}",icon_url=member.display_avatar.url)
    embed.description=f"{member.mention} hat **{real}** Einladung(en)"
    embed.add_field(name="Gesamt",value=total,inline=True); embed.add_field(name="Verlassen",value=left,inline=True); embed.add_field(name="Fake",value=fake,inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard",description="Einladungs-Rangliste anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def leaderboard_cmd(interaction:discord.Interaction):
    top=_inv_top(interaction.guild.id)
    if not top: return await interaction.response.send_message("Noch keine Einladungsdaten verfügbar.",ephemeral=True)
    embed=discord.Embed(title="Einladungs-Rangliste",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    medals={1:"🥇",2:"🥈",3:"🥉"}
    for i,(uid,total,left,fake) in enumerate(top,1):
        u=bot.get_user(uid); real=total-left-fake
        embed.add_field(name=f"{medals.get(i,f'{i}.')} {u.name if u else uid}",value=f"**{real}** Einladung(en) ({total} gesamt · {left} verlassen · {fake} fake)",inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="afk",description="AFK-Status setzen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def afk_cmd(interaction:discord.Interaction,reason:str="AFK"):
    afk_users[interaction.user.id]=(reason[:100],datetime.utcnow())
    await interaction.response.send_message(f"Du bist jetzt AFK: **{reason[:100]}**",ephemeral=True)

# ================================================================
#  SLASH — MODERATION
# ================================================================

@bot.tree.command(name="kick",description="Mitglied vom Server kicken.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_kick(interaction:discord.Interaction,member:discord.Member,reason:str="Kein Grund angegeben"):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if member.id in OWNERS or member.top_role>=interaction.guild.me.top_role: return await interaction.response.send_message("Dieses Mitglied kann nicht gekickt werden.",ephemeral=True)
    try:
        await member.kick(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"**{member}** wurde von **{interaction.user.name}** gekickt. | {reason}")
        await mlog(interaction.guild,"Kick",f"{interaction.user} hat {member} ({member.id}) gekickt. Grund: {reason}")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="ban",description="Mitglied vom Server bannen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_ban(interaction:discord.Interaction,member:discord.Member,reason:str="Kein Grund angegeben"):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if member.id in OWNERS or member.top_role>=interaction.guild.me.top_role: return await interaction.response.send_message("Dieses Mitglied kann nicht gebannt werden.",ephemeral=True)
    try:
        await member.ban(reason=f"{interaction.user}: {reason}",delete_message_days=1)
        await interaction.response.send_message(f"**{member}** wurde von **{interaction.user.name}** gebannt. | {reason}")
        await mlog(interaction.guild,"Ban",f"{interaction.user} hat {member} ({member.id}) gebannt. Grund: {reason}")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="unban",description="Benutzer per ID entbannen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_unban(interaction:discord.Interaction,user_id:str,reason:str="Kein Grund angegeben"):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if not user_id.isdigit(): return await interaction.response.send_message("Bitte eine gültige Benutzer-ID angeben.",ephemeral=True)
    try:
        user=await bot.fetch_user(int(user_id)); await interaction.guild.unban(user,reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"**{user}** wurde entbannt.")
        await mlog(interaction.guild,"Unban",f"{interaction.user} hat {user} ({user.id}) entbannt.")
    except discord.NotFound: await interaction.response.send_message("Benutzer nicht gefunden oder nicht gebannt.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="timeout",description="Mitglied stummschalten. Dauer: z.B. 10m, 2h, 1d",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_timeout(interaction:discord.Interaction,member:discord.Member,duration:str="10m",reason:str="Kein Grund angegeben"):
    if not can_timeout(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    secs=parse_time(duration)
    if secs is None: return await interaction.response.send_message("Ungültige Zeit. Beispiele: `10m`, `2h`, `1d`",ephemeral=True)
    if secs>2419200: return await interaction.response.send_message("Maximaler Timeout beträgt 28 Tage.",ephemeral=True)
    try:
        until=discord.utils.utcnow()+timedelta(seconds=secs)
        await member.timeout(until,reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"**{member}** wurde für **{duration}** stummgeschaltet. | {reason}")
        await mlog(interaction.guild,"Timeout",f"{interaction.user} hat {member} ({member.id}) für {duration} stummgeschaltet.")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="untimeout",description="Stummschaltung eines Mitglieds aufheben.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_untimeout(interaction:discord.Interaction,member:discord.Member):
    if not can_timeout(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    try:
        await member.timeout(None,reason=f"Timeout aufgehoben von {interaction.user}")
        await interaction.response.send_message(f"Timeout für **{member}** wurde aufgehoben.")
        await mlog(interaction.guild,"Timeout aufgehoben",f"{interaction.user} hat Timeout von {member} ({member.id}) aufgehoben.")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="warn",description="Mitglied verwarnen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_warn(interaction:discord.Interaction,member:discord.Member,reason:str="Kein Grund angegeben"):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    wid=_warn_add(interaction.guild.id,member.id,interaction.user.id,reason); wl=_warn_get(interaction.guild.id,member.id)
    await interaction.response.send_message(f"**{member}** wurde verwarnt (#{wid}, gesamt: {len(wl)}). | {reason}")
    await mlog(interaction.guild,"Verwarnung",f"{interaction.user} hat {member} ({member.id}) verwarnt — #{wid}. {reason}")
    try:
        await member.send(embed=discord.Embed(title=f"Verwarnung — {interaction.guild.name}",
            description=f"**Grund:** {reason}\n**Verwarnung #{wid}** — Gesamt: {len(wl)}",color=discord.Color.yellow(),timestamp=datetime.utcnow()))
    except: pass

@bot.tree.command(name="warns",description="Verwarnungen eines Mitglieds anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_warns(interaction:discord.Interaction,member:discord.Member):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    wl=_warn_get(interaction.guild.id,member.id)
    embed=discord.Embed(title=f"Verwarnungen — {member}",color=discord.Color.yellow(),timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    if not wl: embed.description="Keine Verwarnungen eingetragen."
    else:
        for wid,mid,r,ts in wl:
            m=interaction.guild.get_member(mid)
            embed.add_field(name=f"#{wid} — {ts[:10]}",value=f"**Grund:** {r}\n**Mod:** {str(m) if m else mid}",inline=False)
    await interaction.response.send_message(embed=embed,ephemeral=True)

@bot.tree.command(name="purge",description="Nachrichten in diesem Kanal löschen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_purge(interaction:discord.Interaction,amount:int):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if amount<1 or amount>1000: return await interaction.response.send_message("Anzahl muss zwischen 1 und 1000 liegen.",ephemeral=True)
    await interaction.response.defer(ephemeral=True); deleted=await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"{len(deleted)} Nachricht(en) gelöscht.",ephemeral=True)

@bot.tree.command(name="slowmode",description="Slowmode für einen Kanal setzen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_slowmode(interaction:discord.Interaction,seconds:int,channel:discord.TextChannel=None):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if seconds<0 or seconds>21600: return await interaction.response.send_message("Wert muss zwischen 0 und 21600 liegen.",ephemeral=True)
    target=channel or interaction.channel
    try:
        await target.edit(slowmode_delay=seconds)
        msg=f"Slowmode in {target.mention} deaktiviert." if seconds==0 else f"Slowmode auf **{seconds}s** in {target.mention} gesetzt."
        await interaction.response.send_message(msg)
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

# ================================================================
#  SLASH — ROLLEN
# ================================================================

@bot.tree.command(name="role",description="Rolle einem Mitglied zuweisen oder entfernen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_role(interaction:discord.Interaction,member:discord.Member,role:discord.Role):
    if not can_role(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if role>=interaction.guild.me.top_role: return await interaction.response.send_message("Diese Rolle ist höher als oder gleich meiner höchsten Rolle.",ephemeral=True)
    if role.permissions.administrator and interaction.user.id not in OWNERS: return await interaction.response.send_message("Du kannst keine Administrator-Rollen zuweisen.",ephemeral=True)
    if role>=interaction.user.top_role and interaction.user.id not in OWNERS: return await interaction.response.send_message("Du kannst keine Rolle zuweisen, die gleich oder höher als deine eigene ist.",ephemeral=True)
    try:
        if role in member.roles:
            await member.remove_roles(role,reason=f"/role von {interaction.user}")
            await interaction.response.send_message(f"**{role.name}** von {member.mention} entfernt.")
        else:
            await member.add_roles(role,reason=f"/role von {interaction.user}")
            await interaction.response.send_message(f"**{role.name}** an {member.mention} vergeben.")
    except discord.Forbidden: await interaction.response.send_message("Ich habe keine Berechtigung für diese Rolle.",ephemeral=True)

@bot.tree.command(name="roleall",description="Rolle allen Mitgliedern zuweisen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_roleall(interaction:discord.Interaction,role:discord.Role):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if role>=interaction.guild.me.top_role: return await interaction.response.send_message("Diese Rolle ist höher als oder gleich meiner höchsten Rolle.",ephemeral=True)
    if role.permissions.administrator and interaction.user.id not in OWNERS: return await interaction.response.send_message("Nur Owner können Admin-Rollen massenweise zuweisen.",ephemeral=True)
    await interaction.response.defer(); count=0
    for m in interaction.guild.members:
        if m.bot or role in m.roles: continue
        try: await m.add_roles(role,reason=f"/roleall von {interaction.user}"); count+=1
        except: pass
        await asyncio.sleep(0.3)
    await interaction.followup.send(f"Fertig. **{role.name}** an **{count}** Mitglied(er) vergeben.")
    await mlog(interaction.guild,"Rolle an alle",f"{interaction.user} hat **{role.name}** an {count} Mitglieder vergeben.")

@bot.tree.command(name="hackban",description="Mitglied hackbannen (bannt und speichert die ID).",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_hackban(interaction:discord.Interaction,member:discord.Member,reason:str="Kein Grund angegeben"):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if member.id in OWNERS: return await interaction.response.send_message("Du kannst keinen Owner hackbannen.",ephemeral=True)
    try:
        await interaction.guild.ban(member,reason=f"Hackban von {interaction.user}: {reason}",delete_message_days=1)
        _hb_add(interaction.guild.id,member.id,interaction.user.id,reason)
        await interaction.response.send_message(f"**{member}** wurde hackgebannt. | {reason}")
        await mlog(interaction.guild,"Hackban",f"{interaction.user} hat {member} ({member.id}) hackgebannt. Grund: {reason}")
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="hackban_addalt",description="Alt-Account mit einem Hackban verknüpfen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_hackban_addalt(interaction:discord.Interaction,main_id:str,alt_id:str):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if not main_id.isdigit() or not alt_id.isdigit(): return await interaction.response.send_message("Bitte gültige IDs angeben.",ephemeral=True)
    if not _hb_get(interaction.guild.id,int(main_id)): return await interaction.response.send_message("Kein Hackban für diese ID gefunden.",ephemeral=True)
    _hb_alt(interaction.guild.id,int(main_id),int(alt_id))
    try:
        await interaction.guild.ban(discord.Object(id=int(alt_id)),reason=f"Hackban Alt von {main_id}")
        await interaction.response.send_message(f"Alt `{alt_id}` wurde gebannt und mit `{main_id}` verknüpft.")
        await mlog(interaction.guild,"Hackban Alt",f"{interaction.user} hat Alt {alt_id} mit Hackban {main_id} verknüpft.")
    except Exception as e: await interaction.response.send_message(f"Alt verknüpft. Ban fehlgeschlagen: {e}",ephemeral=True)

@bot.tree.command(name="unhackban",description="Hackban aufheben.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_unhackban(interaction:discord.Interaction,user_id:str):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if not user_id.isdigit(): return await interaction.response.send_message("Bitte eine gültige Benutzer-ID angeben.",ephemeral=True)
    uid=int(user_id); _hb_del(interaction.guild.id,uid)
    try:
        await interaction.guild.unban(discord.Object(id=uid),reason=f"Unhackban von {interaction.user}")
        await interaction.response.send_message(f"Hackban für `{user_id}` wurde aufgehoben.")
        await mlog(interaction.guild,"Unhackban",f"{interaction.user} hat Hackban für {user_id} aufgehoben.")
    except discord.NotFound: await interaction.response.send_message("Eintrag entfernt. Benutzer war nicht mehr gebannt.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="invites_set",description="Einladungsanzahl eines Benutzers manuell setzen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def invites_set(interaction:discord.Interaction,member:discord.Member,amount:int):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    _inv_set(interaction.guild.id,member.id,amount)
    await interaction.response.send_message(f"Einladungsanzahl für {member.mention} auf **{amount}** gesetzt.",ephemeral=True)

@bot.tree.command(name="alts",description="Accounts anzeigen, die jünger als X Tage sind.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def alts_cmd(interaction:discord.Interaction,days:int=7):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if days<1 or days>365: return await interaction.response.send_message("Tage müssen zwischen 1 und 365 liegen.",ephemeral=True)
    now=datetime.utcnow()
    alts=[m for m in interaction.guild.members if not m.bot and (now-m.created_at.replace(tzinfo=None))<timedelta(days=days)]
    if not alts: return await interaction.response.send_message(f"Keine Accounts jünger als {days} Tag(e) gefunden.",ephemeral=True)
    embed=discord.Embed(title=f"Accounts jünger als {days} Tag(e)",color=discord.Color.orange(),timestamp=datetime.utcnow())
    embed.set_footer(text=f"{len(alts)} Ergebnis(se)")
    lines=[f"{m.mention} — {(now-m.created_at.replace(tzinfo=None)).days}d (<t:{int(m.created_at.timestamp())}:R>)" for m in sorted(alts,key=lambda x:x.created_at,reverse=True)[:20]]
    embed.description="\n".join(lines)
    if len(alts)>20: embed.description+=f"\n*…und {len(alts)-20} weitere*"
    await interaction.response.send_message(embed=embed)

# ================================================================
#  SLASH — KANAL-BERECHTIGUNGEN
# ================================================================

_CH_PERMS=["view_channel","send_messages","read_message_history","attach_files","embed_links",
    "add_reactions","use_external_emojis","mention_everyone","manage_messages","manage_channels",
    "connect","speak","stream","use_voice_activation","mute_members","deafen_members","move_members",
    "send_tts_messages","create_instant_invite"]

class PermSelect(discord.ui.Select):
    def __init__(self,channel,role):
        self.channel=channel; self.role=role
        super().__init__(placeholder="Berechtigung auswählen…",
            options=[discord.SelectOption(label=p.replace("_"," ").title(),value=p) for p in _CH_PERMS],custom_id="perm_sel")
    async def callback(self,interaction:discord.Interaction):
        perm=self.values[0]; view=PermValueView(self.channel,self.role,perm)
        embed=discord.Embed(description=f"**{perm.replace('_',' ').title()}** für **{self.role.name}** in **{self.channel.name}** setzen:",color=discord.Color.from_rgb(100,100,100))
        await interaction.response.edit_message(embed=embed,view=view)

class PermValueView(discord.ui.View):
    def __init__(self,channel,role,perm): super().__init__(timeout=60); self.channel=channel; self.role=role; self.perm=perm
    @discord.ui.button(label="Erlauben",style=discord.ButtonStyle.success)
    async def allow(self,i,b): await self._apply(i,True)
    @discord.ui.button(label="Verweigern",style=discord.ButtonStyle.danger)
    async def deny(self,i,b): await self._apply(i,False)
    @discord.ui.button(label="Neutral",style=discord.ButtonStyle.secondary)
    async def neutral(self,i,b): await self._apply(i,None)
    async def _apply(self,interaction,value):
        try:
            ow=self.channel.overwrites_for(self.role); setattr(ow,self.perm,value)
            await self.channel.set_permissions(self.role,overwrite=ow)
            label="Erlaubt" if value is True else ("Verweigert" if value is False else "Neutral")
            await interaction.response.edit_message(embed=discord.Embed(
                description=f"**{self.perm.replace('_',' ').title()}** auf **{label}** gesetzt für **{self.role.name}** in **{self.channel.name}**.",
                color=discord.Color.from_rgb(100,100,100)),view=None)
        except Exception as e:
            await interaction.response.edit_message(embed=discord.Embed(description=f"Fehler: {e}",color=discord.Color.red()),view=None)

@bot.tree.command(name="channel_perms",description="Berechtigungs-Override für eine Rolle in einem Kanal setzen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def channel_perms_cmd(interaction:discord.Interaction,channel:discord.abc.GuildChannel,role:discord.Role):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    view=discord.ui.View(timeout=60); view.add_item(PermSelect(channel,role))
    embed=discord.Embed(description=f"Berechtigung für **{role.name}** in **{channel.name}** auswählen:",color=discord.Color.from_rgb(100,100,100))
    await interaction.response.send_message(embed=embed,view=view,ephemeral=True)

# ================================================================
#  SLASH — SICHERHEIT
# ================================================================

@bot.tree.command(name="enable",description="Sicherheitsmodul aktivieren.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def enable_cmd(interaction:discord.Interaction,module:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if module not in SECURITY_MODULES: return await interaction.response.send_message(f"Unbekanntes Modul. Verfügbar: {', '.join(f'`{m}`' for m in SECURITY_MODULES)}",ephemeral=True)
    _ssec(interaction.guild.id,module,True)
    await interaction.response.send_message(f"`{module}` wurde **aktiviert**.")
    await mlog(interaction.guild,"Modul aktiviert",f"{interaction.user} hat `{module}` aktiviert.")

@bot.tree.command(name="disable",description="Sicherheitsmodul deaktivieren.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def disable_cmd(interaction:discord.Interaction,module:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if module not in SECURITY_MODULES: return await interaction.response.send_message(f"Unbekanntes Modul. Verfügbar: {', '.join(f'`{m}`' for m in SECURITY_MODULES)}",ephemeral=True)
    _ssec(interaction.guild.id,module,False)
    await interaction.response.send_message(f"`{module}` wurde **deaktiviert**.")
    await mlog(interaction.guild,"Modul deaktiviert",f"{interaction.user} hat `{module}` deaktiviert.")

@enable_cmd.autocomplete("module")
@disable_cmd.autocomplete("module")
async def module_ac(interaction:discord.Interaction,current:str):
    return [discord.app_commands.Choice(name=m,value=m) for m in SECURITY_MODULES if current.lower() in m.lower()][:25]

@bot.tree.command(name="modules",description="Alle Sicherheitsmodule und ihren Status anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def modules_cmd(interaction:discord.Interaction):
    if not can_mod(interaction.user): return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    lines=[f"{'`AN `' if _sec(interaction.guild.id,m) else '`AUS`'} {m}" for m in SECURITY_MODULES]
    embed=discord.Embed(title="Sicherheitsmodule",description="\n".join(lines),color=discord.Color.from_rgb(100,100,100),timestamp=datetime.utcnow())
    await interaction.response.send_message(embed=embed,ephemeral=True)

# ================================================================
#  SLASH — CONFIG (Owner)
# ================================================================

@bot.tree.command(name="config_id",description="Kanal- oder Rollen-ID des Bots aktualisieren.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def config_id_cmd(interaction:discord.Interaction,setting:str,new_id:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    setting=setting.upper().strip()
    if setting not in _ID_DEF: return await interaction.response.send_message(f"Unbekannte Einstellung. Verfügbar:\n{chr(10).join(f'`{k}`' for k in _ID_DEF)}",ephemeral=True)
    if not new_id.strip().isdigit(): return await interaction.response.send_message("Bitte eine gültige Discord-ID angeben.",ephemeral=True)
    _sid(interaction.guild.id,setting,int(new_id))
    await interaction.response.send_message(f"`{setting}` auf `{new_id}` aktualisiert.",ephemeral=True)
    await mlog(interaction.guild,"Config",f"{interaction.user} hat `{setting}` auf `{new_id}` gesetzt.")

@config_id_cmd.autocomplete("setting")
async def config_id_ac(interaction:discord.Interaction,current:str):
    return [discord.app_commands.Choice(name=k,value=k) for k in _ID_DEF if current.lower() in k.lower()][:25]

@bot.tree.command(name="config_message",description="Bot-Nachricht aktualisieren (Willkommen, Boost).",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def config_msg_cmd(interaction:discord.Interaction,key:str,text:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    key=key.upper().strip()
    if key not in _MSG_LABELS: return await interaction.response.send_message(f"Unbekannter Schlüssel. Verfügbar:\n{chr(10).join(f'`{k}` — {v}' for k,v in _MSG_LABELS.items())}",ephemeral=True)
    _smsg(interaction.guild.id,key,text)
    await interaction.response.send_message(f"`{key}` aktualisiert.",ephemeral=True)

@config_msg_cmd.autocomplete("key")
async def config_msg_ac(interaction:discord.Interaction,current:str):
    return [discord.app_commands.Choice(name=k,value=k) for k in _MSG_LABELS if current.lower() in k.lower()][:25]

@bot.tree.command(name="bot_edit",description="Benutzernamen oder Avatar des Bots ändern.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def bot_edit_cmd(interaction:discord.Interaction,name:str=None,avatar_url:str=None):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if not name and not avatar_url: return await interaction.response.send_message("Bitte `name` und/oder `avatar_url` angeben.",ephemeral=True)
    await interaction.response.defer(ephemeral=True); kw={}
    if name: kw["username"]=name
    if avatar_url:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(avatar_url) as r:
                    if r.status==200: kw["avatar"]=await r.read()
                    else: return await interaction.followup.send(f"Avatar konnte nicht geladen werden (HTTP {r.status}).",ephemeral=True)
        except ImportError: return await interaction.followup.send("aiohttp ist nicht installiert.",ephemeral=True)
    try:
        await bot.user.edit(**kw)
        parts=[]
        if name: parts.append(f"Benutzername → **{name}**")
        if avatar_url: parts.append("Avatar aktualisiert")
        await interaction.followup.send(" | ".join(parts),ephemeral=True)
    except Exception as e: await interaction.followup.send(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="send",description="Nachricht als Bot senden (Embed, Bild, Link-Button).",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def send_cmd(interaction:discord.Interaction,channel:discord.TextChannel,message:str,
    embed:bool=True,color:str="black",image:bool=False,image_url:str=None,
    link_button:bool=False,link_url:str=None,link_label:str="Öffnen"):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if image and not image_url: return await interaction.response.send_message("Bitte `image_url` angeben wenn `image` aktiviert ist.",ephemeral=True)
    if link_button and not link_url: return await interaction.response.send_message("Bitte `link_url` angeben wenn `link_button` aktiviert ist.",ephemeral=True)
    view=discord.utils.MISSING
    if link_button and link_url:
        v=discord.ui.View(); v.add_item(discord.ui.Button(label=link_label,url=link_url,style=discord.ButtonStyle.link)); view=v
    try:
        if embed:
            emb=discord.Embed(description=message,color=parse_color(color))
            if image and image_url: emb.set_image(url=image_url)
            await channel.send(embed=emb,view=view if view is not discord.utils.MISSING else discord.utils.MISSING)
        else:
            content=f"{message}\n{image_url}" if image and image_url else message
            await channel.send(content,view=view if view is not discord.utils.MISSING else discord.utils.MISSING)
        await interaction.response.send_message("Nachricht gesendet.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="say",description="Einfache Textnachricht als Bot senden.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def say_cmd(interaction:discord.Interaction,channel:discord.TextChannel,text:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    try:
        await channel.send(text); await interaction.response.send_message("Nachricht gesendet.",ephemeral=True)
    except discord.Forbidden: await interaction.response.send_message("Ich habe keine Berechtigung für diesen Kanal.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Fehler: {e}",ephemeral=True)

@bot.tree.command(name="whitelist_add",description="Benutzer zur Sicherheits-Whitelist hinzufügen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def wl_add(interaction:discord.Interaction,member:discord.Member):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    SECURITY_WHITELIST_USERS.add(member.id)
    await interaction.response.send_message(f"{member.mention} zur Whitelist hinzugefügt.",ephemeral=True)

@bot.tree.command(name="whitelist_remove",description="Benutzer von der Sicherheits-Whitelist entfernen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def wl_remove(interaction:discord.Interaction,member:discord.Member):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    SECURITY_WHITELIST_USERS.discard(member.id)
    await interaction.response.send_message(f"{member.mention} von der Whitelist entfernt.",ephemeral=True)

@bot.tree.command(name="whitelist_list",description="Alle whitegelisteten Benutzer anzeigen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def wl_list(interaction:discord.Interaction):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    if not SECURITY_WHITELIST_USERS: return await interaction.response.send_message("Die Whitelist ist leer.",ephemeral=True)
    names=[f"{bot.get_user(uid)} (`{uid}`)" if bot.get_user(uid) else f"Unbekannt (`{uid}`)" for uid in SECURITY_WHITELIST_USERS]
    await interaction.response.send_message("**Whitelist:**\n"+"\n".join(names),ephemeral=True)

# ================================================================
#  SICHERHEITS-EVENTS
# ================================================================

@bot.event
async def on_guild_channel_delete(channel:discord.abc.GuildChannel):
    if channel.guild.id!=ALLOWED_GUILD_ID: return
    if not _sec(channel.guild.id,"anti_channel_delete"): return
    if getattr(channel,"category_id",None)==_cid(channel.guild.id,"TICKET_CATEGORY_ID") and channel.name.startswith("ticket-"): return
    saved={"name":channel.name,"type":channel.type,"category":channel.category,"position":channel.position,
           "overwrites":channel.overwrites,"topic":getattr(channel,"topic",None),"nsfw":getattr(channel,"nsfw",False),"slowmode":getattr(channel,"slowmode_delay",0)}
    await asyncio.sleep(0.3)
    e=await audit(channel.guild,discord.AuditLogAction.channel_delete)
    if not e: return
    user=e.user
    if not user or whitelisted(channel.guild.get_member(user.id) or user): return
    try:
        await channel.guild.ban(user,reason="Kanal-Löschung — Auto-Schutz")
        await mlog(channel.guild,"Auto-Ban",f"{user} ({user.id}) hat #{saved['name']} gelöscht — gebannt und Kanal wiederhergestellt.")
    except: pass
    try:
        kw=dict(name=saved["name"],overwrites=saved["overwrites"],category=saved["category"],position=saved["position"],reason="Auto-Wiederherstellung")
        if saved["type"]==discord.ChannelType.text:
            if saved["topic"]: kw["topic"]=saved["topic"]
            kw["nsfw"]=saved["nsfw"]; kw["slowmode_delay"]=saved["slowmode"]
            await channel.guild.create_text_channel(**kw)
        elif saved["type"]==discord.ChannelType.voice: await channel.guild.create_voice_channel(**kw)
        else: await channel.guild.create_text_channel(**kw)
    except: pass

@bot.event
async def on_guild_channel_create(channel:discord.abc.GuildChannel):
    if channel.guild.id!=ALLOWED_GUILD_ID: return
    if not _sec(channel.guild.id,"anti_channel_create"): return
    await asyncio.sleep(0.3)
    e=await audit(channel.guild,discord.AuditLogAction.channel_create)
    if not e: return
    user=e.user
    if not user or whitelisted(channel.guild.get_member(user.id) or user): return
    now=datetime.utcnow()
    channel_create_tracker[user.id]=[t for t in channel_create_tracker[user.id] if now-t<timedelta(seconds=CREATE_WIN)]
    channel_create_tracker[user.id].append(now)
    if len(channel_create_tracker[user.id])>=CREATE_MAX:
        try:
            await channel.guild.ban(user,reason=f"Kanal-Spam ({CREATE_MAX}+ in {CREATE_WIN}s)")
            await mlog(channel.guild,"Auto-Ban",f"{user} ({user.id}) hat {len(channel_create_tracker[user.id])} Kanäle in {CREATE_WIN}s erstellt — gebannt.")
            channel_create_tracker[user.id].clear()
        except: pass

@bot.event
async def on_guild_role_delete(role:discord.Role):
    if role.guild.id!=ALLOWED_GUILD_ID: return
    if not _sec(role.guild.id,"anti_role_delete"): return
    saved={"name":role.name,"color":role.color,"permissions":role.permissions,"hoist":role.hoist,"mentionable":role.mentionable}
    await asyncio.sleep(0.3)
    e=await audit(role.guild,discord.AuditLogAction.role_delete)
    if not e: return
    user=e.user
    if not user or whitelisted(role.guild.get_member(user.id) or user): return
    try:
        await role.guild.ban(user,reason="Rollen-Löschung — Auto-Schutz")
        await mlog(role.guild,"Auto-Ban",f"{user} ({user.id}) hat Rolle **{saved['name']}** gelöscht — gebannt und Rolle wiederhergestellt.")
    except: pass
    try:
        await role.guild.create_role(name=saved["name"],color=saved["color"],permissions=saved["permissions"],hoist=saved["hoist"],mentionable=saved["mentionable"],reason="Auto-Wiederherstellung")
    except: pass

@bot.event
async def on_guild_role_create(role:discord.Role):
    if role.guild.id!=ALLOWED_GUILD_ID: return
    if not _sec(role.guild.id,"anti_role_create"): return
    await asyncio.sleep(0.3)
    e=await audit(role.guild,discord.AuditLogAction.role_create)
    if not e: return
    user=e.user
    if not user or whitelisted(role.guild.get_member(user.id) or user): return
    now=datetime.utcnow()
    role_create_tracker[user.id]=[t for t in role_create_tracker[user.id] if now-t<timedelta(seconds=CREATE_WIN)]
    role_create_tracker[user.id].append(now)
    if len(role_create_tracker[user.id])>=CREATE_MAX:
        try:
            await role.guild.ban(user,reason=f"Rollen-Spam ({CREATE_MAX}+ in {CREATE_WIN}s)")
            await mlog(role.guild,"Auto-Ban",f"{user} ({user.id}) hat {len(role_create_tracker[user.id])} Rollen in {CREATE_WIN}s erstellt — gebannt.")
            role_create_tracker[user.id].clear()
        except: pass

@bot.event
async def on_webhooks_update(channel:discord.TextChannel):
    if channel.guild.id!=ALLOWED_GUILD_ID: return
    if not _sec(channel.guild.id,"anti_webhook"): return
    await asyncio.sleep(0.3)
    e=await audit(channel.guild,discord.AuditLogAction.webhook_create)
    if not e: return
    user=e.user
    if not user or whitelisted(channel.guild.get_member(user.id) or user): return
    try:
        for w in await channel.webhooks(): await w.delete()
        await channel.guild.ban(user,reason="Webhook-Angriff — Auto-Schutz")
        await mlog(channel.guild,"Auto-Ban",f"{user} ({user.id}) hat einen Webhook erstellt — gebannt.")
    except: pass

@bot.event
async def on_member_ban(guild:discord.Guild,user:discord.User):
    if guild.id!=ALLOWED_GUILD_ID: return
    if not _sec(guild.id,"anti_mass_ban"): return
    await asyncio.sleep(0.3)
    e=await audit(guild,discord.AuditLogAction.ban)
    if not e: return
    actor=e.user
    if not actor or whitelisted(guild.get_member(actor.id) or actor): return
    now=datetime.utcnow()
    ban_tracker[actor.id]=[t for t in ban_tracker[actor.id] if now-t<timedelta(seconds=20)]
    ban_tracker[actor.id].append(now)
    if len(ban_tracker[actor.id])>=2:
        try:
            await guild.ban(actor,reason="Massen-Ban (2+ in 20s)")
            await mlog(guild,"Auto-Ban",f"{actor} ({actor.id}) hat 2+ Mitglieder in 20s gebannt — gebannt.")
        except: pass

@bot.event
async def on_audit_log_entry_create(entry:discord.AuditLogEntry):
    if entry.guild.id!=ALLOWED_GUILD_ID: return

    if entry.action==discord.AuditLogAction.member_update and _sec(entry.guild.id,"anti_mass_timeout"):
        actor=entry.user
        if not actor or whitelisted(entry.guild.get_member(actor.id) or actor): return
        ch=entry.changes; after={c.key:c.new for c in ch.after} if hasattr(ch,"after") else {}
        if "timed_out_until" in after and after["timed_out_until"] is not None:
            now=datetime.utcnow()
            timeout_tracker[actor.id]=[t for t in timeout_tracker[actor.id] if now-t<timedelta(seconds=15)]
            timeout_tracker[actor.id].append(now)
            if len(timeout_tracker[actor.id])>=2:
                try:
                    await entry.guild.ban(actor,reason="Massen-Timeout (2+ in 15s)")
                    await mlog(entry.guild,"Auto-Ban",f"{actor} ({actor.id}) hat 2+ Mitglieder in 15s stummgeschaltet — gebannt.")
                except: pass

    if entry.action==discord.AuditLogAction.role_update and _sec(entry.guild.id,"anti_admin_perm"):
        actor=entry.user
        if not actor or whitelisted(entry.guild.get_member(actor.id) or actor): return
        role=entry.target
        if not role or role.position>=entry.guild.me.top_role.position: return
        ap=None
        if hasattr(entry.changes,"after"):
            for c in entry.changes.after:
                if c.key=="permissions": ap=c.new; break
        if ap and ap.administrator:
            try:
                p=discord.Permissions(ap.value); p.administrator=False
                await role.edit(permissions=p,reason="Admin-Berechtigung blockiert")
            except: pass
            m=entry.guild.get_member(actor.id)
            if m:
                try:
                    await m.kick(reason="Versuch, Administrator-Berechtigung zu vergeben")
                    await mlog(entry.guild,"Admin-Berechtigung blockiert",f"{actor} ({actor.id}) versuchte Admin-Berechtigung an **{role.name}** zu vergeben — Berechtigung entfernt, Benutzer gekickt.")
                except: pass

    if entry.action==discord.AuditLogAction.guild_update:
        actor=entry.user
        if actor and not actor.bot:
            await mlog(entry.guild,"Server aktualisiert",f"{actor} ({actor.id}) hat Server-Einstellungen geändert.")

    if entry.action==discord.AuditLogAction.bot_add:
        actor=entry.user; ba=entry.target
        await mlog(entry.guild,"Bot hinzugefügt",f"{actor} ({actor.id}) hat Bot {ba} ({getattr(ba,'id','?')}) hinzugefügt.")

# ================================================================
#  HELP
# ================================================================

@bot.command(name="help")
async def help_cmd(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    embed=discord.Embed(title="Befehlsübersicht",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.add_field(name="Moderation",value=(
        "`?kick` `?ban` `?unban` `?unbanall`\n"
        "`?timeout` `?rto` `?purge` `?slowmode`\n"
        "`?warn` `?warns` `?clearwarn` `?clearwarns`\n"
        "Auch als Slash-Befehle verfügbar."),inline=False)
    embed.add_field(name="Rollen",value=(
        "`?role @user <Name/ID>` — Rolle ein-/ausschalten\n"
        "`?roleall @role` — Allen Mitgliedern zuweisen\n"
        "`?rolecreate <Name>` — Mit Berechtigungen erstellen\n"
        "`?roleinfo <Name>` | Auch `/role` `/roleall`"),inline=False)
    embed.add_field(name="Hackban",value=(
        "`?hackban @user` | `?hackban_addalt <ID> <AltID>`\n"
        "`?unhackban <ID>` | Auch als Slash-Befehle."),inline=False)
    embed.add_field(name="Tickets",value=(
        "`?close` `?delete`\n"
        "`/adduser` `/removeuser` `/renameticket`\n"
        "`/setup` — Ticket-Panel & Konfiguration"),inline=False)
    embed.add_field(name="Night Mode",value=(
        "`/nightmode` — Manuell an/aus & Rollen verwalten\n"
        "Auto: 22:00 aus | 09:00 an (Berliner Zeit)\n"
        "Log-Kanal wird benachrichtigt"),inline=False)
    embed.add_field(name="Sicherheit",value="`/enable <Modul>` `/disable <Modul>` `/modules`",inline=False)
    embed.add_field(name="Config (Owner)",value=(
        "`/config_id` `/config_message` `/bot_edit`\n"
        "`/send` `/say` `/whitelist_add|remove|list`"),inline=False)
    embed.add_field(name="Öffentlich",value=(
        "`/avatar` `/serverinfo` `/roleinfo`\n"
        "`/invite` `/leaderboard` `/afk` `/alts`"),inline=False)
    embed.set_footer(text=f"Angefragt von {ctx.author}")
    await ctx.send(embed=embed)

# ================================================================
#  BOT-ADD SICHERHEIT
# ================================================================

async def _on_audit_bot_add_security(entry: discord.AuditLogEntry):
    if entry.guild.id != ALLOWED_GUILD_ID: return
    if entry.action != discord.AuditLogAction.bot_add: return

    added_bot = entry.target
    actor     = entry.user

    if added_bot:
        member = entry.guild.get_member(added_bot.id)
        if member:
            try:
                await member.kick(reason="Nicht autorisierte Bot-Hinzufügung — Auto-Sicherheit")
            except Exception:
                pass

    if actor and not whitelisted(actor) and actor.id not in OWNERS:
        m = entry.guild.get_member(actor.id)
        if m and bot_can_act(entry.guild, m):
            try:
                await entry.guild.ban(
                    actor,
                    reason="Hat einen nicht autorisierten Bot hinzugefügt — Auto-Sicherheit")
                await mlog(entry.guild, "Auto-Ban",
                    f"{actor} ({actor.id}) hat Bot {added_bot} "
                    f"({getattr(added_bot, 'id', '?')}) hinzugefügt — Bot gekickt, Hinzufüger gebannt.")
            except Exception:
                pass

bot.add_listener(_on_audit_bot_add_security, "on_audit_log_entry_create")

# ================================================================
#  MASSEN-PING BAN
# ================================================================

async def _on_message_mass_ping_ban(message: discord.Message):
    if message.author.bot: return
    if not message.guild or message.guild.id != ALLOWED_GUILD_ID: return
    if whitelisted(message.author): return
    if not ("@everyone" in message.content or "@here" in message.content): return

    now = datetime.utcnow()
    mass_ping_tracker[message.author.id].append(now)
    mass_ping_tracker[message.author.id] = [
        t for t in mass_ping_tracker[message.author.id]
        if now - t < timedelta(seconds=PING_WINDOW)]

    if len(mass_ping_tracker[message.author.id]) >= PING_MAX:
        m = message.guild.get_member(message.author.id)
        if m and bot_can_act(message.guild, m):
            for r in list(m.roles):
                if r.permissions.administrator and r < message.guild.me.top_role:
                    try: await m.remove_roles(r, reason="Massen-Ping — Admin-Rolle entfernt")
                    except Exception: pass
            try:
                await message.guild.ban(
                    m,
                    reason=f"Massen-Ping-Missbrauch — {PING_MAX}+ @everyone/@here in {PING_WINDOW}s",
                    delete_message_days=1)
                await mlog(message.guild, "Auto-Ban",
                    f"{m} ({m.id}) hat {len(mass_ping_tracker[m.id])} "
                    f"Massen-Pings in {PING_WINDOW}s gesendet — Admin-Rollen entfernt + gebannt.")
            except Exception:
                pass
            mass_ping_tracker[message.author.id].clear()

bot.add_listener(_on_message_mass_ping_ban, "on_message")

# ================================================================
#  /role_for_all_channels
# ================================================================

_PERM_FLAGS_READABLE = [
    "view_channel", "send_messages", "read_message_history",
    "attach_files", "embed_links", "add_reactions", "use_external_emojis",
    "mention_everyone", "manage_messages", "manage_channels",
    "connect", "speak", "stream", "use_voice_activation",
    "mute_members", "deafen_members", "move_members",
    "send_tts_messages", "create_instant_invite",
]

class RoleAllChannelsPermSelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=p.replace("_"," ").title(),value=p) for p in _PERM_FLAGS_READABLE]
        super().__init__(placeholder="Berechtigungen zum ERLAUBEN auswählen…",options=options,min_values=0,max_values=len(options),custom_id="rac_allow_sel")
    async def callback(self,interaction:discord.Interaction):
        self.view.allowed_perms=set(interaction.data["values"]); await interaction.response.defer()

class RoleAllChannelsDenySelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=p.replace("_"," ").title(),value=p) for p in _PERM_FLAGS_READABLE]
        super().__init__(placeholder="Berechtigungen zum VERWEIGERN auswählen…",options=options,min_values=0,max_values=len(options),custom_id="rac_deny_sel")
    async def callback(self,interaction:discord.Interaction):
        self.view.denied_perms=set(interaction.data["values"]); await interaction.response.defer()

class RoleAllChannelsView(discord.ui.View):
    def __init__(self,role:discord.Role):
        super().__init__(timeout=180); self.role=role; self.allowed_perms:set[str]=set(); self.denied_perms:set[str]=set()
        self.add_item(RoleAllChannelsPermSelect()); self.add_item(RoleAllChannelsDenySelect())
    @discord.ui.button(label="Auf alle Kanäle anwenden",style=discord.ButtonStyle.success,row=2)
    async def apply(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        count=0; errors=0; guild=interaction.guild; role=self.role
        for ch in guild.channels:
            ow=ch.overwrites_for(role)
            for perm in self.allowed_perms:
                if hasattr(ow,perm): setattr(ow,perm,True)
            for perm in self.denied_perms:
                if hasattr(ow,perm): setattr(ow,perm,False)
            try:
                await ch.set_permissions(role,overwrite=ow,reason=f"/role_for_all_channels von {interaction.user}"); count+=1
            except Exception: errors+=1
            await asyncio.sleep(0.3)
        summary_allow=", ".join(self.allowed_perms) or "keine"; summary_deny=", ".join(self.denied_perms) or "keine"
        await interaction.followup.send(f"Fertig. **{role.name}** in **{count}** Kanal/Kanälen aktualisiert (Fehler: {errors}).\nErlaubt: `{summary_allow}`\nVerweigert: `{summary_deny}`",ephemeral=True)
        await mlog(guild,"Rolle auf alle Kanäle angewendet",f"{interaction.user} hat **{role.name}** auf {count} Kanäle angewendet. Erlaubt: {summary_allow} | Verweigert: {summary_deny}")
    @discord.ui.button(label="Abbrechen",style=discord.ButtonStyle.danger,row=2)
    async def cancel(self,interaction:discord.Interaction,button:discord.ui.Button): await interaction.response.edit_message(content="Abgebrochen.",view=None)

@bot.tree.command(name="role_for_all_channels",description="Benutzerdefinierte Berechtigungen für eine Rolle in allen Kanälen setzen.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def role_for_all_channels(interaction:discord.Interaction,role:discord.Role):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("Keine Berechtigung.",ephemeral=True)
    embed=discord.Embed(title="Rolle — Alle Kanäle",description=(f"Konfiguriere **{role.name}** für alle Kanäle.\n\n1. Berechtigungen zum **Erlauben** auswählen.\n2. Berechtigungen zum **Verweigern** auswählen.\n3. **Auf alle Kanäle anwenden** klicken."),color=discord.Color.from_rgb(149,165,166))
    view=RoleAllChannelsView(role)
    await interaction.response.send_message(embed=embed,view=view,ephemeral=True)

# ================================================================
#  ON READY
# ================================================================

@bot.event
async def on_ready():
    print(f"Online: {bot.user}")
    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
    except Exception:
        pass
    asyncio.create_task(voice_loop())
    asyncio.create_task(tracker_cleanup())
    asyncio.create_task(night_mode_loop())
    for g in bot.guilds:
        c, lu = _cnt_load(g.id)
        counting_state["current"]   = c
        counting_state["last_user"] = lu or None
    for g in bot.guilds:
        try:
            invs = await g.invites()
            invite_cache[g.id] = {i.code: i.uses for i in invs}
        except Exception:
            pass

# ================================================================
#  RUN
# ================================================================

bot.run(TOKEN)
