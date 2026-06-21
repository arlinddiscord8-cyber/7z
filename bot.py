import sqlite3, discord, asyncio, os, re, pathlib
from discord.ext import commands
from discord.ui import View, Button
from collections import defaultdict
from datetime import datetime, timedelta

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
INVITE_RE = re.compile(r"(discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE)
SECURITY_WHITELIST_USERS: set[int] = set()
SECURITY_WHITELIST_ROLES: set[int] = set()
SECURITY_MODULES = [
    "anti_spam","anti_mention","anti_invite","anti_webhook",
    "anti_channel_delete","anti_channel_create","anti_role_delete","anti_role_create",
    "anti_mass_ban","anti_mass_kick","anti_mass_timeout","anti_admin_perm","new_account_warn",
]

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
_MSG_DEF={"WELCOME_MSG":"Hey {mention},\n\nWelcome to **Corazon**!\nPlease read the rules: <#{rules}>\n\n- Be respectful\n- Have fun!","BOOST_MSG":"thank you 🖤"}
_MSG_LABELS={"WELCOME_MSG":"Welcome message ({mention} {rules})","BOOST_MSG":"Boost message"}

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

# ================================================================
#  READY / BACKGROUND TASKS
# ================================================================

async def setup_hook():
    bot.add_view(TicketButton()); bot.add_view(TicketActionView()); bot.add_view(TicketDeleteView())
bot.setup_hook=setup_hook

# on_ready defined further below (includes night_mode_loop)

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
            try: await member.ban(reason=f"Hackban alt of {huid}")
            except: pass
            return
    if _sec(member.guild.id,"new_account_warn") and new_account(member):
        await mlog(member.guild,"New Account",f"{member} ({member.id}) — account younger than 7 days.")
    ar=member.guild.get_role(_cid(member.guild.id,"AUTO_ROLE_ID"))
    if ar:
        try: await member.add_roles(ar,reason="Auto Role")
        except: pass
    wch=member.guild.get_channel(_cid(member.guild.id,"WELCOME_CHANNEL_ID"))
    if wch:
        try:
            raw=_cmsg(member.guild.id,"WELCOME_MSG")
            await wch.send(embed=discord.Embed(description=raw.format(mention=member.mention,rules=_cid(member.guild.id,"RULES_CHANNEL_ID")),color=discord.Color.from_rgb(149,165,166)))
        except: pass
    try:
        new_invs=await member.guild.invites(); old=invite_cache.get(member.guild.id,{})
        used=next((i for i in new_invs if i.uses>old.get(i.code,0)),None)
        invite_cache[member.guild.id]={i.code:i.uses for i in new_invs}
        ich=member.guild.get_channel(_cid(member.guild.id,"INVITE_CHANNEL_ID"))
        if ich:
            if used is None:
                emb=discord.Embed(title=member.guild.name,description=f"{member.mention} joined via **Vanity Link**",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
            elif used.inviter:
                _inv_add(member.guild.id,used.inviter.id); total,left,fake=_inv_get(member.guild.id,used.inviter.id)
                emb=discord.Embed(title=member.guild.name,description=f"{member.mention} joined.\nInvited by **{used.inviter.name}** — now **{total-left-fake} invite(s)**",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
            else:
                emb=discord.Embed(title=member.guild.name,description=f"{member.mention} joined. Inviter unknown.",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
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
        try: await member.guild.ban(actor,reason="Mass kick (2+ in 20s)"); await mlog(member.guild,"Auto-Ban",f"{actor} ({actor.id}) kicked 2+ members in 20s — banned.")
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
                try: await after.add_roles(ex,reason="Trigger Role")
                except: pass

# ================================================================
#  MESSAGES
# ================================================================

@bot.event
async def on_message(message:discord.Message):
    if message.author.bot: await bot.process_commands(message); return
    g=message.guild
    if not g or g.id!=ALLOWED_GUILD_ID: await bot.process_commands(message); return

    # Activity check channel: delete @everyone/@here silently
    if message.channel.id==ACTIVITY_CHECK_CHANNEL_ID:
        if "@everyone" in message.content or "@here" in message.content:
            try: await message.delete()
            except: pass
            return

    if not whitelisted(message.author):
        now=datetime.utcnow()
        # Anti-spam
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
                    await message.channel.send(f"{message.author.mention} You have been timed out for spamming.",delete_after=5)
                    spam_tracker[message.author.id].clear()
                    await mlog(g,"Auto-Timeout",f"{message.author} ({message.author.id}) timed out for spam.")
                except: pass
                return

        # Anti-mention (mass ping protection)
        if _sec(g.id,"anti_mention"):
            has_mass_ping="@everyone" in message.content or "@here" in message.content
            total=len(set(u.id for u in message.mentions))+len(message.role_mentions)
            if has_mass_ping or total>=MENTION_MAX:
                # Track rapid pings (2+ in 5s)
                mass_ping_tracker[message.author.id].append(now)
                mass_ping_tracker[message.author.id]=[t for t in mass_ping_tracker[message.author.id] if now-t<timedelta(seconds=5)]
                if len(mass_ping_tracker[message.author.id])>=2:
                    try:
                        await message.delete()
                        until=discord.utils.utcnow()+timedelta(minutes=10)
                        await message.author.timeout(until,reason="Mass ping spam")
                        # Remove all admin roles
                        for role in message.author.roles:
                            if role.permissions.administrator:
                                try: await message.author.remove_roles(role,reason="Mass ping — admin role removed")
                                except: pass
                        await message.channel.send(f"{message.author.mention} You have been timed out for 10 minutes for mass pinging. Admin roles removed.",delete_after=8)
                        mass_ping_tracker[message.author.id].clear()
                        await mlog(g,"Mass Ping",f"{message.author} ({message.author.id}) mass pinged — timed out 10min + admin roles removed.")
                    except: pass
                    return
                else:
                    # First offence — just delete
                    try: await message.delete()
                    except: pass
                    try: await message.channel.send(f"{message.author.mention} Mass pings are not allowed here.",delete_after=5)
                    except: pass
                    return

        # Anti-invite
        if _sec(g.id,"anti_invite") and INVITE_RE.search(message.content):
            try: await message.delete()
            except: pass
            invite_link_tracker[message.author.id].append(now)
            invite_link_tracker[message.author.id]=[t for t in invite_link_tracker[message.author.id] if now-t<timedelta(seconds=30)]
            if len(invite_link_tracker[message.author.id])>=2:
                try:
                    until=discord.utils.utcnow()+timedelta(seconds=SPAM_TIMEOUT)
                    await message.author.timeout(until,reason="Invite spam")
                    await message.channel.send(f"{message.author.mention} You have been timed out for posting invite links.",delete_after=5)
                    invite_link_tracker[message.author.id].clear()
                    await mlog(g,"Auto-Timeout",f"{message.author} ({message.author.id}) timed out for invite spam.")
                except: pass
            else:
                try: await message.channel.send(f"{message.author.mention} Invite links are not allowed here.",delete_after=5)
                except: pass
            return

    # Auto-react
    if message.channel.id in AUTO_REACT_CHANNEL_IDS:
        emoji="✅" if message.channel.id==ACTIVITY_CHECK_CHANNEL_ID else "✔️"
        try: await message.add_reaction(emoji)
        except: pass

    # Counting
    if COUNTING_CHANNEL_ID and message.channel.id==COUNTING_CHANNEL_ID:
        await handle_counting(message); return

    # AFK remove
    if message.author.id in afk_users:
        afk_users.pop(message.author.id)
        try: await message.channel.send(f"Welcome back {message.author.mention}, your AFK has been removed.",delete_after=5,allowed_mentions=discord.AllowedMentions(users=True))
        except: pass

    # AFK notify
    for u in message.mentions:
        if u.id in afk_users:
            r,ts=afk_users[u.id]
            try: await message.channel.send(f"**{u.name}** is AFK since <t:{int(ts.timestamp())}:R> — {r}",delete_after=8)
            except: pass

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message:discord.Message):
    if not message.guild or message.guild.id!=ALLOWED_GUILD_ID: return
    if COUNTING_CHANNEL_ID and message.channel.id==COUNTING_CHANNEL_ID:
        if message.author.bot: return
        try:
            n=await message.channel.send(f"A message was deleted. Next number: **{counting_state['current']+1}**.")
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
            n=await message.channel.send(f"{message.author.mention} You cannot count twice in a row.")
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
            n=await message.channel.send(f"Incorrect. Next number: **{expected}**.")
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
    try: await reaction.message.channel.send(f"{user.mention} was first!",allowed_mentions=discord.AllowedMentions(users=True))
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
    @discord.ui.button(label="Close",style=discord.ButtonStyle.secondary,custom_id="tkt_close")
    async def close_btn(self,interaction:discord.Interaction,button:Button):
        if not can_ticket(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
        await interaction.response.defer()
        sr=interaction.guild.get_role(_cid(interaction.guild.id,"SUPPORT_ROLE_ID"))
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role,read_messages=False,send_messages=False)
            if sr: await interaction.channel.set_permissions(sr,read_messages=True,send_messages=True)
            await interaction.channel.send("This ticket has been closed. Only staff can view it.")
        except Exception as e: await interaction.followup.send(f"Error: {e}",ephemeral=True)
    @discord.ui.button(label="Delete",style=discord.ButtonStyle.danger,custom_id="tkt_delete")
    async def delete_btn(self,interaction:discord.Interaction,button:Button):
        if not can_ticket(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
        await interaction.response.defer()
        try: await interaction.channel.send("Deleting ticket...")
        except: pass
        await asyncio.sleep(1)
        try: await interaction.channel.delete(reason=f"Deleted by {interaction.user}")
        except: pass

class TicketDeleteView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Delete",style=discord.ButtonStyle.danger,custom_id="tkt_delete_v2")
    async def delete_btn(self,interaction:discord.Interaction,button:Button):
        if not can_ticket(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
        await interaction.response.defer()
        try: await interaction.channel.send("Deleting ticket...")
        except: pass
        await asyncio.sleep(1)
        try: await interaction.channel.delete(reason=f"Deleted by {interaction.user}")
        except: pass

class TicketButton(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Open Ticket",style=discord.ButtonStyle.blurple,custom_id="tkt_create")
    async def create(self,interaction:discord.Interaction,button:Button):
        g=interaction.guild; cat=g.get_channel(_cid(g.id,"TICKET_CATEGORY_ID"))
        if cat:
            for ch in cat.text_channels:
                if ch.name.startswith("ticket-") and ch.overwrites_for(interaction.user).read_messages:
                    return await interaction.response.send_message(f"You already have an open ticket: {ch.mention}",ephemeral=True)
        num=_tkt_num(g.id); sr=g.get_role(_cid(g.id,"SUPPORT_ROLE_ID"))
        ow={g.default_role:discord.PermissionOverwrite(read_messages=False),
            interaction.user:discord.PermissionOverwrite(read_messages=True,send_messages=True)}
        if sr: ow[sr]=discord.PermissionOverwrite(read_messages=True,send_messages=True)
        for r in g.roles:
            if r.permissions.administrator and r not in ow: ow[r]=discord.PermissionOverwrite(read_messages=True,send_messages=True)
        try:
            tc=await g.create_text_channel(name=f"ticket-{num}",category=cat,overwrites=ow,reason=f"Ticket by {interaction.user}")
            embed=discord.Embed(title=f"Ticket #{num}",description="Please describe your issue. Our team will assist you shortly.",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
            pings=f"{sr.mention} {interaction.user.mention}" if sr else interaction.user.mention
            await tc.send(content=pings,embed=embed,view=TicketActionView())
            await interaction.response.send_message(f"Your ticket has been created: {tc.mention}",ephemeral=True)
        except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.command()
async def close(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID or not is_ticket(ctx.channel): return
    if not can_ticket(ctx.author): return await ctx.send("You do not have permission to do this.")
    try: await ctx.message.delete()
    except: pass
    sr=ctx.guild.get_role(_cid(ctx.guild.id,"SUPPORT_ROLE_ID"))
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role,read_messages=False,send_messages=False)
        if sr: await ctx.channel.set_permissions(sr,read_messages=True,send_messages=True)
        await ctx.send("This ticket has been closed. Only staff can view it.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command(name="delete")
async def delete_ticket(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID or not is_ticket(ctx.channel): return
    if not can_ticket(ctx.author): return await ctx.send("You do not have permission to do this.")
    try: await ctx.message.delete()
    except: pass
    try: await ctx.send("Deleting ticket...")
    except: pass
    await asyncio.sleep(1)
    try: await ctx.channel.delete(reason=f"Deleted by {ctx.author}")
    except Exception as e: await ctx.send(f"Error: {e}")

# ── /setup (Ticket only) ─────────────────────────────────────────

class IDModal(discord.ui.Modal):
    def __init__(self,key:str,gid:int,label:str):
        super().__init__(title=f"Set {label}")
        self.key=key; self.gid=gid
        self.field=discord.ui.TextInput(label=f"New ID",placeholder="Discord ID…",min_length=17,max_length=20)
        self.add_item(self.field)
    async def on_submit(self,interaction:discord.Interaction):
        v=self.field.value.strip()
        if not v.isdigit(): return await interaction.response.send_message("Invalid ID.",ephemeral=True)
        _sid(self.gid,self.key,int(v))
        await interaction.response.send_message(f"`{self.key}` updated to `{v}`.",ephemeral=True)
        await mlog(interaction.guild,"Config",f"{interaction.user} set `{self.key}` to `{v}`.")

class TicketSetupView(discord.ui.View):
    def __init__(self,gid): super().__init__(timeout=120); self.gid=gid

    @discord.ui.button(label="Send Panel",style=discord.ButtonStyle.primary,row=0)
    async def send_panel(self,interaction:discord.Interaction,button:discord.ui.Button):
        ch=interaction.guild.get_channel(_cid(interaction.guild.id,"TICKET_PANEL_CHANNEL_ID"))
        if not ch: return await interaction.response.send_message("Panel channel not found.",ephemeral=True)
        embed=discord.Embed(title="Support",description="Click the button below to open a support ticket.",color=discord.Color.from_rgb(149,165,166))
        await ch.send(embed=embed,view=TicketButton())
        await interaction.response.edit_message(embed=discord.Embed(description=f"Panel sent to {ch.mention}.",color=discord.Color.from_rgb(100,100,100)),view=None)

    @discord.ui.button(label="Set Category",style=discord.ButtonStyle.secondary,row=0)
    async def set_cat(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.send_modal(IDModal("TICKET_CATEGORY_ID",interaction.guild.id,"Ticket Category"))

    @discord.ui.button(label="Set Panel Channel",style=discord.ButtonStyle.secondary,row=0)
    async def set_panel_ch(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.send_modal(IDModal("TICKET_PANEL_CHANNEL_ID",interaction.guild.id,"Panel Channel"))

    @discord.ui.button(label="Set Support Role",style=discord.ButtonStyle.secondary,row=1)
    async def set_sr(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.send_modal(IDModal("SUPPORT_ROLE_ID",interaction.guild.id,"Support Role"))

    @discord.ui.button(label="Ticket Stats",style=discord.ButtonStyle.secondary,row=1)
    async def stats(self,interaction:discord.Interaction,button:discord.ui.Button):
        total=_tkt_cur(interaction.guild.id)
        cat=interaction.guild.get_channel(_cid(interaction.guild.id,"TICKET_CATEGORY_ID"))
        open_t=len([c for c in cat.text_channels if c.name.startswith("ticket-")]) if cat else 0
        embed=discord.Embed(title="Ticket Statistics",
            description=f"Total created: **{total}**\nCurrently open: **{open_t}**\nNext number: **{total+1}**",
            color=discord.Color.from_rgb(149,165,166))
        await interaction.response.send_message(embed=embed,ephemeral=True)

@bot.tree.command(name="setup",description="Configure the ticket system.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def setup_cmd(interaction:discord.Interaction):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    cat_id=_cid(interaction.guild.id,"TICKET_CATEGORY_ID"); panel_id=_cid(interaction.guild.id,"TICKET_PANEL_CHANNEL_ID"); sr_id=_cid(interaction.guild.id,"SUPPORT_ROLE_ID")
    embed=discord.Embed(title="Ticket Setup",
        description=(f"**Category:** <#{cat_id}> (`{cat_id}`)\n"
                     f"**Panel Channel:** <#{panel_id}> (`{panel_id}`)\n"
                     f"**Support Role:** <@&{sr_id}> (`{sr_id}`)\n"
                     f"**Total Tickets:** {_tkt_cur(interaction.guild.id)}"),
        color=discord.Color.from_rgb(149,165,166))
    await interaction.response.send_message(embed=embed,view=TicketSetupView(interaction.guild.id),ephemeral=True)

@bot.tree.command(name="adduser",description="Add a user to the current ticket.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def adduser(interaction:discord.Interaction,member:discord.Member):
    if not is_ticket(interaction.channel): return await interaction.response.send_message("This command can only be used in a ticket channel.",ephemeral=True)
    if not can_ticket(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    try:
        await interaction.channel.set_permissions(member,read_messages=True,send_messages=True)
        await interaction.response.send_message(f"{member.mention} has been added to this ticket.")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="removeuser",description="Remove a user from the current ticket.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def removeuser(interaction:discord.Interaction,member:discord.Member):
    if not is_ticket(interaction.channel): return await interaction.response.send_message("This command can only be used in a ticket channel.",ephemeral=True)
    if not can_ticket(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    try:
        await interaction.channel.set_permissions(member,overwrite=None)
        await interaction.response.send_message(f"{member.mention} has been removed from this ticket.")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="renameticket",description="Rename the current ticket.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def renameticket(interaction:discord.Interaction,name:str):
    if not is_ticket(interaction.channel): return await interaction.response.send_message("This command can only be used in a ticket channel.",ephemeral=True)
    if not can_ticket(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    name=name.lower().replace(" ","-")[:50]
    try:
        await interaction.channel.edit(name=f"ticket-{name}")
        await interaction.response.send_message(f"Ticket renamed to **ticket-{name}**.")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="ticketpanel",description="Send the ticket panel to the configured channel.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def ticketpanel(interaction:discord.Interaction):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    ch=interaction.guild.get_channel(_cid(interaction.guild.id,"TICKET_PANEL_CHANNEL_ID"))
    if not ch: return await interaction.response.send_message("Panel channel not found.",ephemeral=True)
    embed=discord.Embed(title="Support",description="Click the button below to open a support ticket.",color=discord.Color.from_rgb(149,165,166))
    try:
        await ch.send(embed=embed,view=TicketButton())
        await interaction.response.send_message(f"Panel sent to {ch.mention}.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

# ================================================================
#  MODERATION — PREFIX COMMANDS
# ================================================================

@bot.command()
async def kick(ctx:commands.Context,member:discord.Member=None,*,reason:str="No reason provided"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?kick @user [reason]`")
    if member.id in OWNERS: return await clean(ctx,"You cannot kick an owner.")
    if member.top_role>=ctx.guild.me.top_role: return await clean(ctx,"That member has a higher role than me.")
    try:
        await member.kick(reason=f"{ctx.author}: {reason}")
        await ctx.send(f"**{member}** has been kicked by **{ctx.author.name}**. | {reason}")
        await mlog(ctx.guild,"Kick",f"{ctx.author} kicked {member} ({member.id}). Reason: {reason}")
    except discord.Forbidden: await ctx.send("I am missing permissions to do this.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command()
async def ban(ctx:commands.Context,member:discord.Member=None,*,reason:str="No reason provided"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?ban @user [reason]`")
    if member.id in OWNERS: return await clean(ctx,"You cannot ban an owner.")
    if member.top_role>=ctx.guild.me.top_role: return await clean(ctx,"That member has a higher role than me.")
    try:
        await member.ban(reason=f"{ctx.author}: {reason}",delete_message_days=1)
        await ctx.send(f"**{member}** has been banned by **{ctx.author.name}**. | {reason}")
        await mlog(ctx.guild,"Ban",f"{ctx.author} banned {member} ({member.id}). Reason: {reason}")
    except discord.Forbidden: await ctx.send("I am missing permissions to do this.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command()
async def unban(ctx:commands.Context,user_id:str=None,*,reason:str="No reason provided"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not user_id or not user_id.isdigit(): return await clean(ctx,"Usage: `?unban <UserID> [reason]`")
    try:
        user=await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user,reason=f"{ctx.author}: {reason}")
        await ctx.send(f"**{user}** has been unbanned.")
        await mlog(ctx.guild,"Unban",f"{ctx.author} unbanned {user} ({user.id}).")
    except discord.NotFound: await ctx.send("User not found or not banned.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command(aliases=["to"])
async def timeout(ctx:commands.Context,member:discord.Member=None,duration:str=None,*,reason:str="No reason provided"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_timeout(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member or not duration: return await clean(ctx,"Usage: `?timeout @user <time> [reason]` — e.g. 10m, 2h, 1d")
    secs=parse_time(duration)
    if secs is None: return await clean(ctx,"Invalid duration. Examples: `10m`, `2h`, `1d`")
    if secs>2419200: return await clean(ctx,"Maximum timeout is 28 days.")
    try:
        until=discord.utils.utcnow()+timedelta(seconds=secs)
        await member.timeout(until,reason=f"{ctx.author}: {reason}")
        await ctx.send(f"**{member}** has been timed out for **{duration}**. | {reason}")
        await mlog(ctx.guild,"Timeout",f"{ctx.author} timed out {member} ({member.id}) for {duration}.")
    except discord.Forbidden: await ctx.send("I am missing permissions to do this.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command(name="rto")
async def rto(ctx:commands.Context,member:discord.Member=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_timeout(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?rto @user`")
    try:
        await member.timeout(None,reason=f"Timeout removed by {ctx.author}")
        await ctx.send(f"Timeout removed for **{member}**.")
        await mlog(ctx.guild,"Timeout Removed",f"{ctx.author} removed timeout from {member} ({member.id}).")
    except discord.Forbidden: await ctx.send("I am missing permissions to do this.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command()
async def warn(ctx:commands.Context,member:discord.Member=None,*,reason:str="No reason provided"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?warn @user [reason]`")
    wid=_warn_add(ctx.guild.id,member.id,ctx.author.id,reason); wl=_warn_get(ctx.guild.id,member.id)
    await ctx.send(f"**{member}** has been warned (#{wid}, total: {len(wl)}). | {reason}")
    await mlog(ctx.guild,"Warning",f"{ctx.author} warned {member} ({member.id}) — #{wid}. {reason}")
    try:
        await member.send(embed=discord.Embed(title=f"Warning — {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Warning #{wid}** — Total: {len(wl)}",
            color=discord.Color.yellow(),timestamp=datetime.utcnow()))
    except: pass

@bot.command()
async def warns(ctx:commands.Context,member:discord.Member=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?warns @user`")
    wl=_warn_get(ctx.guild.id,member.id)
    embed=discord.Embed(title=f"Warnings — {member}",color=discord.Color.yellow(),timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    if not wl: embed.description="No warnings on record."
    else:
        for wid,mid,r,ts in wl:
            m=ctx.guild.get_member(mid)
            embed.add_field(name=f"#{wid} — {ts[:10]}",value=f"**Reason:** {r}\n**Mod:** {str(m) if m else mid}",inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def clearwarn(ctx:commands.Context,warn_id:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not warn_id or not warn_id.isdigit(): return await clean(ctx,"Usage: `?clearwarn <ID>`")
    if _warn_del(int(warn_id),ctx.guild.id): await ctx.send(f"Warning **#{warn_id}** has been removed.",delete_after=5)
    else: await ctx.send(f"Warning **#{warn_id}** was not found.",delete_after=5)

@bot.command()
async def clearwarns(ctx:commands.Context,member:discord.Member=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?clearwarns @user`")
    n=_warn_clear(ctx.guild.id,member.id)
    await ctx.send(f"**{n}** warning(s) cleared for {member.mention}.",delete_after=5)

@bot.command()
async def purge(ctx:commands.Context,amount:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    try: await ctx.message.delete()
    except: pass
    if not amount: return await ctx.send("Usage: `?purge all` or `?purge <amount>`",delete_after=3)
    if amount.lower()=="all": deleted=await ctx.channel.purge(limit=None)
    else:
        if not amount.isdigit() or int(amount)<1: return await ctx.send("Invalid amount.",delete_after=3)
        if int(amount)>1000: return await ctx.send("Maximum is 1000 messages.",delete_after=3)
        deleted=await ctx.channel.purge(limit=int(amount))
    n=await ctx.send(f"{len(deleted)} message(s) deleted."); await asyncio.sleep(3)
    try: await n.delete()
    except: pass

@bot.command(name="slowmode")
async def slowmode_cmd(ctx:commands.Context,seconds:int=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if seconds is None: return await clean(ctx,"Usage: `?slowmode <seconds>` (0 to disable)")
    if seconds<0 or seconds>21600: return await clean(ctx,"Value must be between 0 and 21600.")
    try:
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.send("Slowmode disabled." if seconds==0 else f"Slowmode set to **{seconds}s**.",delete_after=5)
        try: await ctx.message.delete()
        except: pass
    except Exception as e: await ctx.send(f"Error: {e}")

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
        sel=discord.ui.Select(placeholder="Select permissions (optional)…",options=options,min_values=0,max_values=len(options),custom_id="rc_perms")
        sel.callback=self.perms_cb; self.add_item(sel)
    async def perms_cb(self,interaction:discord.Interaction): self.chosen=set(interaction.data["values"]); await interaction.response.defer()
    @discord.ui.button(label="Create Role",style=discord.ButtonStyle.success,row=1)
    async def confirm(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.ctx.author.id: return await interaction.response.send_message("This menu is not for you.",ephemeral=True)
        perms=discord.Permissions()
        for p in self.chosen:
            if hasattr(perms,p): setattr(perms,p,True)
        try:
            role=await interaction.guild.create_role(name=self.name,permissions=perms,color=self.color,hoist=self.hoist,reason=f"?rolecreate by {interaction.user}")
            # Set overwrite in all channels so role appears in channel settings
            for ch in interaction.guild.channels:
                try:
                    if ch.overwrites_for(role).is_empty():
                        await ch.set_permissions(role,view_channel=True,reason="Role created — default overwrite")
                except: pass
            await interaction.response.edit_message(content=f"Role **{role.name}** has been created ({role.mention}) with {len(self.chosen)} permission(s).",view=None)
            await mlog(interaction.guild,"Role Created",f"{interaction.user} created **{role.name}**. Permissions: {', '.join(self.chosen) or 'none'}")
        except Exception as e: await interaction.response.edit_message(content=f"Error: {e}",view=None)
    @discord.ui.button(label="Cancel",style=discord.ButtonStyle.danger,row=1)
    async def cancel(self,interaction:discord.Interaction,button:discord.ui.Button): await interaction.response.edit_message(content="Cancelled.",view=None)

@bot.command(name="role")
async def role_cmd(ctx:commands.Context,member:discord.Member=None,*,role_input:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_role(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member or not role_input: return await clean(ctx,"Usage: `?role @user <role name or ID>`")
    matches=find_role(ctx.guild,role_input)
    if not matches: return await clean(ctx,f"No role found matching **{role_input}**.")
    if len(matches)>1: return await clean(ctx,f"Multiple roles found: {', '.join(f'`{r.name}`' for r in matches[:6])} — be more specific.",delay=6)
    role=matches[0]
    if role>=ctx.guild.me.top_role: return await clean(ctx,"That role is higher than or equal to my highest role.")
    # Prevent assigning roles higher than or equal to the actor's top role, or admin roles
    if role.permissions.administrator and ctx.author.id not in OWNERS:
        return await clean(ctx,"You cannot assign administrator roles.")
    if role>=ctx.author.top_role and ctx.author.id not in OWNERS:
        return await clean(ctx,"You cannot assign a role equal to or higher than your own highest role.")
    try:
        if role in member.roles:
            await member.remove_roles(role,reason=f"?role by {ctx.author}")
            await ctx.send(f"Removed **{role.name}** from {member.mention}.")
        else:
            await member.add_roles(role,reason=f"?role by {ctx.author}")
            await ctx.send(f"Assigned **{role.name}** to {member.mention}.")
    except discord.Forbidden: await ctx.send("I am missing permissions for that role.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command(name="roleall")
async def roleall_cmd(ctx:commands.Context,role:discord.Role=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not role: return await clean(ctx,"Usage: `?roleall @role`")
    if role>=ctx.guild.me.top_role: return await clean(ctx,"That role is higher than or equal to my highest role.")
    if role.permissions.administrator and ctx.author.id not in OWNERS: return await clean(ctx,"Only owners can mass-assign admin roles.")
    msg=await ctx.send(f"Assigning **{role.name}** to all members…"); count=0
    for m in ctx.guild.members:
        if m.bot or role in m.roles: continue
        try: await m.add_roles(role,reason=f"?roleall by {ctx.author}"); count+=1
        except: pass
        await asyncio.sleep(0.3)
    await msg.edit(content=f"Done. **{role.name}** assigned to **{count}** member(s).")
    await mlog(ctx.guild,"Role All",f"{ctx.author} assigned **{role.name}** to {count} members.")

@bot.command(name="rolecreate")
async def rolecreate_cmd(ctx:commands.Context,role_name:str=None,color_hex:str="#000000",hoist:str="no"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not role_name: return await clean(ctx,"Usage: `?rolecreate <name> [#color] [yes/no]`")
    try:
        c=color_hex.lstrip("#"); color=discord.Color.from_rgb(int(c[0:2],16),int(c[2:4],16),int(c[4:6],16))
    except: color=discord.Color.default()
    view=RoleCreateView(ctx,role_name,color,hoist.lower() in("yes","ja","true","1"))
    await ctx.send(f"Select permissions for **{role_name}**:",view=view)

@bot.command(name="roleinfo")
async def roleinfo_cmd(ctx:commands.Context,*,role_input:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not role_input: return await clean(ctx,"Usage: `?roleinfo <role name or ID>`")
    matches=find_role(ctx.guild,role_input)
    if not matches: return await clean(ctx,"No role found.")
    r=matches[0]; perms=[p.replace("_"," ").title() for p,v in r.permissions if v]
    embed=discord.Embed(title=r.name,color=r.color if r.color.value else discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.add_field(name="ID",value=r.id,inline=True); embed.add_field(name="Color",value=str(r.color),inline=True)
    embed.add_field(name="Members",value=str(len(r.members)),inline=True); embed.add_field(name="Mentionable",value="Yes" if r.mentionable else "No",inline=True)
    embed.add_field(name="Hoisted",value="Yes" if r.hoist else "No",inline=True); embed.add_field(name="Created",value=f"<t:{int(r.created_at.timestamp())}:R>",inline=True)
    embed.add_field(name="Permissions",value=", ".join(perms[:20]) if perms else "None",inline=False)
    await ctx.send(embed=embed)

# ================================================================
#  HACKBAN — PREFIX
# ================================================================

@bot.command()
async def hackban(ctx:commands.Context,member:discord.Member=None,*,reason:str="No reason provided"):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not member: return await clean(ctx,"Usage: `?hackban @user [reason]`")
    if member.id in OWNERS: return await clean(ctx,"You cannot hackban an owner.")
    try:
        await ctx.guild.ban(member,reason=f"Hackban by {ctx.author}: {reason}",delete_message_days=1)
        _hb_add(ctx.guild.id,member.id,ctx.author.id,reason)
        await ctx.send(f"**{member}** has been hackbanned. | {reason}")
        await mlog(ctx.guild,"Hackban",f"{ctx.author} hackbanned {member} ({member.id}). Reason: {reason}")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command()
async def hackban_addalt(ctx:commands.Context,main_id:str=None,alt_id:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not main_id or not alt_id or not main_id.isdigit() or not alt_id.isdigit(): return await clean(ctx,"Usage: `?hackban_addalt <MainID> <AltID>`")
    if not _hb_get(ctx.guild.id,int(main_id)): return await ctx.send("No hackban found for that ID.")
    _hb_alt(ctx.guild.id,int(main_id),int(alt_id))
    try:
        await ctx.guild.ban(discord.Object(id=int(alt_id)),reason=f"Hackban alt of {main_id}")
        await ctx.send(f"Alt `{alt_id}` has been banned and linked to `{main_id}`.")
        await mlog(ctx.guild,"Hackban Alt",f"{ctx.author} linked alt {alt_id} to hackban {main_id}.")
    except Exception as e: await ctx.send(f"Alt linked. Ban failed: {e}")

@bot.command()
async def unhackban(ctx:commands.Context,user_id:str=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    if not user_id or not user_id.isdigit(): return await clean(ctx,"Usage: `?unhackban <UserID>`")
    uid=int(user_id); _hb_del(ctx.guild.id,uid)
    try:
        await ctx.guild.unban(discord.Object(id=uid),reason=f"Unhackban by {ctx.author}")
        await ctx.send(f"Hackban for `{user_id}` has been lifted.")
        await mlog(ctx.guild,"Unhackban",f"{ctx.author} lifted hackban for {user_id}.")
    except discord.NotFound: await ctx.send("Entry removed. User was no longer banned.")
    except Exception as e: await ctx.send(f"Error: {e}")

@bot.command(name="unbanall")
async def unbanall_cmd(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not can_mod(ctx.author): return await clean(ctx,"You do not have permission to do this.")
    msg=await ctx.send("Unbanning all users…"); count=0
    async for entry in ctx.guild.bans():
        try: await ctx.guild.unban(entry.user,reason=f"?unbanall by {ctx.author}"); count+=1
        except: pass
        await asyncio.sleep(0.3)
    await msg.edit(content=f"Done. **{count}** user(s) unbanned.")
    await mlog(ctx.guild,"Unban All",f"{ctx.author} unbanned all {count} users.")

@bot.command()
async def setcount(ctx:commands.Context,number:int=None):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    if not is_owner(ctx.author.id): return await clean(ctx,"You do not have permission to do this.")
    if number is None: return await clean(ctx,"Usage: `?setcount <number>`")
    counting_state["current"]=number; counting_state["last_user"]=None
    _cnt_save(ctx.guild.id,number,0)
    await ctx.send(f"Counter set to **{number}**.",delete_after=5)
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
        await ctx.send("Connected.",delete_after=3)
    except Exception as e: await ctx.send(f"Error: {e}")

# ================================================================
#  SLASH — PUBLIC
# ================================================================

@bot.tree.command(name="avatar",description="Show a user's avatar.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def avatar(interaction:discord.Interaction,member:discord.Member=None):
    m=member or interaction.user
    embed=discord.Embed(title=str(m),color=discord.Color.from_rgb(149,165,166))
    embed.set_image(url=m.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo",description="Show information about the server.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def serverinfo(interaction:discord.Interaction):
    g=interaction.guild
    embed=discord.Embed(title=g.name,color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    if g.icon: embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="ID",value=g.id,inline=True); embed.add_field(name="Owner",value=f"<@{g.owner_id}>",inline=True)
    embed.add_field(name="Created",value=f"<t:{int(g.created_at.timestamp())}:R>",inline=True)
    embed.add_field(name="Members",value=g.member_count,inline=True); embed.add_field(name="Roles",value=len(g.roles),inline=True)
    embed.add_field(name="Channels",value=len(g.channels),inline=True); embed.add_field(name="Boosts",value=g.premium_subscription_count,inline=True)
    embed.add_field(name="Boost Level",value=g.premium_tier,inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roleinfo",description="Show information about a role.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_roleinfo(interaction:discord.Interaction,role:discord.Role):
    perms=[p.replace("_"," ").title() for p,v in role.permissions if v]
    embed=discord.Embed(title=role.name,color=role.color if role.color.value else discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.add_field(name="ID",value=role.id,inline=True); embed.add_field(name="Color",value=str(role.color),inline=True)
    embed.add_field(name="Members",value=str(len(role.members)),inline=True); embed.add_field(name="Mentionable",value="Yes" if role.mentionable else "No",inline=True)
    embed.add_field(name="Hoisted",value="Yes" if role.hoist else "No",inline=True); embed.add_field(name="Created",value=f"<t:{int(role.created_at.timestamp())}:R>",inline=True)
    embed.add_field(name="Permissions",value=", ".join(perms[:20]) if perms else "None",inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="invite",description="Show a user's invite count.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def invite_cmd(interaction:discord.Interaction,member:discord.Member):
    total,left,fake=_inv_get(interaction.guild.id,member.id); real=total-left-fake
    embed=discord.Embed(color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.set_author(name=f"{member.name}'s Invites",icon_url=member.display_avatar.url)
    embed.description=f"{member.mention} has **{real}** invite(s)"
    embed.add_field(name="Total",value=total,inline=True); embed.add_field(name="Left",value=left,inline=True); embed.add_field(name="Fake",value=fake,inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard",description="Show the invite leaderboard.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def leaderboard_cmd(interaction:discord.Interaction):
    top=_inv_top(interaction.guild.id)
    if not top: return await interaction.response.send_message("No invite data available yet.",ephemeral=True)
    embed=discord.Embed(title="Invite Leaderboard",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    medals={1:"🥇",2:"🥈",3:"🥉"}
    for i,(uid,total,left,fake) in enumerate(top,1):
        u=bot.get_user(uid); real=total-left-fake
        embed.add_field(name=f"{medals.get(i,f'{i}.')} {u.name if u else uid}",value=f"**{real}** invite(s) ({total} total · {left} left · {fake} fake)",inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="afk",description="Set your AFK status.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def afk_cmd(interaction:discord.Interaction,reason:str="AFK"):
    afk_users[interaction.user.id]=(reason[:100],datetime.utcnow())
    await interaction.response.send_message(f"You are now AFK: **{reason[:100]}**",ephemeral=True)

# ================================================================
#  SLASH — MODERATION
# ================================================================

@bot.tree.command(name="kick",description="Kick a member from the server.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_kick(interaction:discord.Interaction,member:discord.Member,reason:str="No reason provided"):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if member.id in OWNERS or member.top_role>=interaction.guild.me.top_role: return await interaction.response.send_message("Unable to kick this member.",ephemeral=True)
    try:
        await member.kick(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"**{member}** has been kicked by **{interaction.user.name}**. | {reason}")
        await mlog(interaction.guild,"Kick",f"{interaction.user} kicked {member} ({member.id}). Reason: {reason}")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="ban",description="Ban a member from the server.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_ban(interaction:discord.Interaction,member:discord.Member,reason:str="No reason provided"):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if member.id in OWNERS or member.top_role>=interaction.guild.me.top_role: return await interaction.response.send_message("Unable to ban this member.",ephemeral=True)
    try:
        await member.ban(reason=f"{interaction.user}: {reason}",delete_message_days=1)
        await interaction.response.send_message(f"**{member}** has been banned by **{interaction.user.name}**. | {reason}")
        await mlog(interaction.guild,"Ban",f"{interaction.user} banned {member} ({member.id}). Reason: {reason}")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="unban",description="Unban a user by ID.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_unban(interaction:discord.Interaction,user_id:str,reason:str="No reason provided"):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if not user_id.isdigit(): return await interaction.response.send_message("Please provide a valid user ID.",ephemeral=True)
    try:
        user=await bot.fetch_user(int(user_id)); await interaction.guild.unban(user,reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"**{user}** has been unbanned.")
        await mlog(interaction.guild,"Unban",f"{interaction.user} unbanned {user} ({user.id}).")
    except discord.NotFound: await interaction.response.send_message("User not found or not banned.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="timeout",description="Timeout a member. Duration: e.g. 10m, 2h, 1d",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_timeout(interaction:discord.Interaction,member:discord.Member,duration:str="10m",reason:str="No reason provided"):
    if not can_timeout(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    secs=parse_time(duration)
    if secs is None: return await interaction.response.send_message("Invalid duration. Examples: `10m`, `2h`, `1d`",ephemeral=True)
    if secs>2419200: return await interaction.response.send_message("Maximum timeout is 28 days.",ephemeral=True)
    try:
        until=discord.utils.utcnow()+timedelta(seconds=secs)
        await member.timeout(until,reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"**{member}** has been timed out for **{duration}**. | {reason}")
        await mlog(interaction.guild,"Timeout",f"{interaction.user} timed out {member} ({member.id}) for {duration}.")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="untimeout",description="Remove a member's timeout.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_untimeout(interaction:discord.Interaction,member:discord.Member):
    if not can_timeout(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    try:
        await member.timeout(None,reason=f"Timeout removed by {interaction.user}")
        await interaction.response.send_message(f"Timeout removed for **{member}**.")
        await mlog(interaction.guild,"Timeout Removed",f"{interaction.user} removed timeout from {member} ({member.id}).")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="warn",description="Warn a member.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_warn(interaction:discord.Interaction,member:discord.Member,reason:str="No reason provided"):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    wid=_warn_add(interaction.guild.id,member.id,interaction.user.id,reason); wl=_warn_get(interaction.guild.id,member.id)
    await interaction.response.send_message(f"**{member}** has been warned (#{wid}, total: {len(wl)}). | {reason}")
    await mlog(interaction.guild,"Warning",f"{interaction.user} warned {member} ({member.id}) — #{wid}. {reason}")
    try:
        await member.send(embed=discord.Embed(title=f"Warning — {interaction.guild.name}",
            description=f"**Reason:** {reason}\n**Warning #{wid}** — Total: {len(wl)}",color=discord.Color.yellow(),timestamp=datetime.utcnow()))
    except: pass

@bot.tree.command(name="warns",description="View a member's warnings.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_warns(interaction:discord.Interaction,member:discord.Member):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    wl=_warn_get(interaction.guild.id,member.id)
    embed=discord.Embed(title=f"Warnings — {member}",color=discord.Color.yellow(),timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    if not wl: embed.description="No warnings on record."
    else:
        for wid,mid,r,ts in wl:
            m=interaction.guild.get_member(mid)
            embed.add_field(name=f"#{wid} — {ts[:10]}",value=f"**Reason:** {r}\n**Mod:** {str(m) if m else mid}",inline=False)
    await interaction.response.send_message(embed=embed,ephemeral=True)

@bot.tree.command(name="purge",description="Delete messages from this channel.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_purge(interaction:discord.Interaction,amount:int):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if amount<1 or amount>1000: return await interaction.response.send_message("Amount must be between 1 and 1000.",ephemeral=True)
    await interaction.response.defer(ephemeral=True); deleted=await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"{len(deleted)} message(s) deleted.",ephemeral=True)

@bot.tree.command(name="slowmode",description="Set slowmode for a channel.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_slowmode(interaction:discord.Interaction,seconds:int,channel:discord.TextChannel=None):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if seconds<0 or seconds>21600: return await interaction.response.send_message("Value must be between 0 and 21600.",ephemeral=True)
    target=channel or interaction.channel
    try:
        await target.edit(slowmode_delay=seconds)
        msg=f"Slowmode disabled in {target.mention}." if seconds==0 else f"Slowmode set to **{seconds}s** in {target.mention}."
        await interaction.response.send_message(msg)
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

# ================================================================
#  SLASH — ROLES
# ================================================================

@bot.tree.command(name="role",description="Assign or remove a role from a member.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_role(interaction:discord.Interaction,member:discord.Member,role:discord.Role):
    if not can_role(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if role>=interaction.guild.me.top_role: return await interaction.response.send_message("That role is higher than or equal to my highest role.",ephemeral=True)
    if role.permissions.administrator and interaction.user.id not in OWNERS: return await interaction.response.send_message("You cannot assign administrator roles.",ephemeral=True)
    if role>=interaction.user.top_role and interaction.user.id not in OWNERS: return await interaction.response.send_message("You cannot assign a role equal to or higher than your own.",ephemeral=True)
    try:
        if role in member.roles:
            await member.remove_roles(role,reason=f"/role by {interaction.user}")
            await interaction.response.send_message(f"Removed **{role.name}** from {member.mention}.")
        else:
            await member.add_roles(role,reason=f"/role by {interaction.user}")
            await interaction.response.send_message(f"Assigned **{role.name}** to {member.mention}.")
    except discord.Forbidden: await interaction.response.send_message("I am missing permissions for that role.",ephemeral=True)

@bot.tree.command(name="roleall",description="Assign a role to all members.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_roleall(interaction:discord.Interaction,role:discord.Role):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if role>=interaction.guild.me.top_role: return await interaction.response.send_message("That role is higher than or equal to my highest role.",ephemeral=True)
    if role.permissions.administrator and interaction.user.id not in OWNERS: return await interaction.response.send_message("Only owners can mass-assign admin roles.",ephemeral=True)
    await interaction.response.defer(); count=0
    for m in interaction.guild.members:
        if m.bot or role in m.roles: continue
        try: await m.add_roles(role,reason=f"/roleall by {interaction.user}"); count+=1
        except: pass
        await asyncio.sleep(0.3)
    await interaction.followup.send(f"Done. **{role.name}** assigned to **{count}** member(s).")
    await mlog(interaction.guild,"Role All",f"{interaction.user} assigned **{role.name}** to {count} members.")

@bot.tree.command(name="hackban",description="Hackban a member (bans and tracks the ID).",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_hackban(interaction:discord.Interaction,member:discord.Member,reason:str="No reason provided"):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if member.id in OWNERS: return await interaction.response.send_message("You cannot hackban an owner.",ephemeral=True)
    try:
        await interaction.guild.ban(member,reason=f"Hackban by {interaction.user}: {reason}",delete_message_days=1)
        _hb_add(interaction.guild.id,member.id,interaction.user.id,reason)
        await interaction.response.send_message(f"**{member}** has been hackbanned. | {reason}")
        await mlog(interaction.guild,"Hackban",f"{interaction.user} hackbanned {member} ({member.id}). Reason: {reason}")
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="hackban_addalt",description="Link an alt account to an existing hackban.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_hackban_addalt(interaction:discord.Interaction,main_id:str,alt_id:str):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if not main_id.isdigit() or not alt_id.isdigit(): return await interaction.response.send_message("Please provide valid IDs.",ephemeral=True)
    if not _hb_get(interaction.guild.id,int(main_id)): return await interaction.response.send_message("No hackban found for that ID.",ephemeral=True)
    _hb_alt(interaction.guild.id,int(main_id),int(alt_id))
    try:
        await interaction.guild.ban(discord.Object(id=int(alt_id)),reason=f"Hackban alt of {main_id}")
        await interaction.response.send_message(f"Alt `{alt_id}` has been banned and linked to `{main_id}`.")
        await mlog(interaction.guild,"Hackban Alt",f"{interaction.user} linked alt {alt_id} to hackban {main_id}.")
    except Exception as e: await interaction.response.send_message(f"Alt linked. Ban failed: {e}",ephemeral=True)

@bot.tree.command(name="unhackban",description="Lift a hackban.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def slash_unhackban(interaction:discord.Interaction,user_id:str):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if not user_id.isdigit(): return await interaction.response.send_message("Please provide a valid user ID.",ephemeral=True)
    uid=int(user_id); _hb_del(interaction.guild.id,uid)
    try:
        await interaction.guild.unban(discord.Object(id=uid),reason=f"Unhackban by {interaction.user}")
        await interaction.response.send_message(f"Hackban for `{user_id}` has been lifted.")
        await mlog(interaction.guild,"Unhackban",f"{interaction.user} lifted hackban for {user_id}.")
    except discord.NotFound: await interaction.response.send_message("Entry removed. User was no longer banned.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="invites_set",description="Manually set a user's invite count.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def invites_set(interaction:discord.Interaction,member:discord.Member,amount:int):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    _inv_set(interaction.guild.id,member.id,amount)
    await interaction.response.send_message(f"Invite count for {member.mention} set to **{amount}**.",ephemeral=True)

@bot.tree.command(name="alts",description="Show accounts newer than X days.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def alts_cmd(interaction:discord.Interaction,days:int=7):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if days<1 or days>365: return await interaction.response.send_message("Days must be between 1 and 365.",ephemeral=True)
    now=datetime.utcnow()
    alts=[m for m in interaction.guild.members if not m.bot and (now-m.created_at.replace(tzinfo=None))<timedelta(days=days)]
    if not alts: return await interaction.response.send_message(f"No accounts newer than {days} day(s) found.",ephemeral=True)
    embed=discord.Embed(title=f"Accounts newer than {days} day(s)",color=discord.Color.orange(),timestamp=datetime.utcnow())
    embed.set_footer(text=f"{len(alts)} result(s)")
    lines=[f"{m.mention} — {(now-m.created_at.replace(tzinfo=None)).days}d (<t:{int(m.created_at.timestamp())}:R>)" for m in sorted(alts,key=lambda x:x.created_at,reverse=True)[:20]]
    embed.description="\n".join(lines)
    if len(alts)>20: embed.description+=f"\n*…and {len(alts)-20} more*"
    await interaction.response.send_message(embed=embed)

# ================================================================
#  SLASH — CHANNEL PERMS
# ================================================================

_CH_PERMS=["view_channel","send_messages","read_message_history","attach_files","embed_links",
    "add_reactions","use_external_emojis","mention_everyone","manage_messages","manage_channels",
    "connect","speak","stream","use_voice_activation","mute_members","deafen_members","move_members",
    "send_tts_messages","create_instant_invite"]

class PermSelect(discord.ui.Select):
    def __init__(self,channel,role):
        self.channel=channel; self.role=role
        super().__init__(placeholder="Select a permission…",
            options=[discord.SelectOption(label=p.replace("_"," ").title(),value=p) for p in _CH_PERMS],custom_id="perm_sel")
    async def callback(self,interaction:discord.Interaction):
        perm=self.values[0]; view=PermValueView(self.channel,self.role,perm)
        embed=discord.Embed(description=f"Set **{perm.replace('_',' ').title()}** for **{self.role.name}** in **{self.channel.name}**:",color=discord.Color.from_rgb(100,100,100))
        await interaction.response.edit_message(embed=embed,view=view)

class PermValueView(discord.ui.View):
    def __init__(self,channel,role,perm): super().__init__(timeout=60); self.channel=channel; self.role=role; self.perm=perm
    @discord.ui.button(label="Allow",style=discord.ButtonStyle.success)
    async def allow(self,i,b): await self._apply(i,True)
    @discord.ui.button(label="Deny",style=discord.ButtonStyle.danger)
    async def deny(self,i,b): await self._apply(i,False)
    @discord.ui.button(label="Neutral",style=discord.ButtonStyle.secondary)
    async def neutral(self,i,b): await self._apply(i,None)
    async def _apply(self,interaction,value):
        try:
            ow=self.channel.overwrites_for(self.role); setattr(ow,self.perm,value)
            await self.channel.set_permissions(self.role,overwrite=ow)
            label="Allowed" if value is True else ("Denied" if value is False else "Neutral")
            await interaction.response.edit_message(embed=discord.Embed(
                description=f"**{self.perm.replace('_',' ').title()}** set to **{label}** for **{self.role.name}** in **{self.channel.name}**.",
                color=discord.Color.from_rgb(100,100,100)),view=None)
        except Exception as e:
            await interaction.response.edit_message(embed=discord.Embed(description=f"Error: {e}",color=discord.Color.red()),view=None)

@bot.tree.command(name="channel_perms",description="Set a permission override for a role in a channel.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def channel_perms_cmd(interaction:discord.Interaction,channel:discord.abc.GuildChannel,role:discord.Role):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    view=discord.ui.View(timeout=60); view.add_item(PermSelect(channel,role))
    embed=discord.Embed(description=f"Select a permission to configure for **{role.name}** in **{channel.name}**:",color=discord.Color.from_rgb(100,100,100))
    await interaction.response.send_message(embed=embed,view=view,ephemeral=True)

# ================================================================
#  SLASH — SECURITY
# ================================================================

@bot.tree.command(name="enable",description="Enable a security module.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def enable_cmd(interaction:discord.Interaction,module:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if module not in SECURITY_MODULES: return await interaction.response.send_message(f"Unknown module. Available: {', '.join(f'`{m}`' for m in SECURITY_MODULES)}",ephemeral=True)
    _ssec(interaction.guild.id,module,True)
    await interaction.response.send_message(f"`{module}` has been **enabled**.")
    await mlog(interaction.guild,"Module Enabled",f"{interaction.user} enabled `{module}`.")

@bot.tree.command(name="disable",description="Disable a security module.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def disable_cmd(interaction:discord.Interaction,module:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if module not in SECURITY_MODULES: return await interaction.response.send_message(f"Unknown module. Available: {', '.join(f'`{m}`' for m in SECURITY_MODULES)}",ephemeral=True)
    _ssec(interaction.guild.id,module,False)
    await interaction.response.send_message(f"`{module}` has been **disabled**.")
    await mlog(interaction.guild,"Module Disabled",f"{interaction.user} disabled `{module}`.")

@enable_cmd.autocomplete("module")
@disable_cmd.autocomplete("module")
async def module_ac(interaction:discord.Interaction,current:str):
    return [discord.app_commands.Choice(name=m,value=m) for m in SECURITY_MODULES if current.lower() in m.lower()][:25]

@bot.tree.command(name="modules",description="Show all security modules and their status.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def modules_cmd(interaction:discord.Interaction):
    if not can_mod(interaction.user): return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    lines=[f"{'`ON `' if _sec(interaction.guild.id,m) else '`OFF`'} {m}" for m in SECURITY_MODULES]
    embed=discord.Embed(title="Security Modules",description="\n".join(lines),color=discord.Color.from_rgb(100,100,100),timestamp=datetime.utcnow())
    await interaction.response.send_message(embed=embed,ephemeral=True)

# ================================================================
#  SLASH — CONFIG (Owner)
# ================================================================

@bot.tree.command(name="config_id",description="Update a bot channel or role ID.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def config_id_cmd(interaction:discord.Interaction,setting:str,new_id:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    setting=setting.upper().strip()
    if setting not in _ID_DEF: return await interaction.response.send_message(f"Unknown setting. Available:\n{chr(10).join(f'`{k}`' for k in _ID_DEF)}",ephemeral=True)
    if not new_id.strip().isdigit(): return await interaction.response.send_message("Please provide a valid Discord ID.",ephemeral=True)
    _sid(interaction.guild.id,setting,int(new_id))
    await interaction.response.send_message(f"`{setting}` updated to `{new_id}`.",ephemeral=True)
    await mlog(interaction.guild,"Config",f"{interaction.user} set `{setting}` to `{new_id}`.")

@config_id_cmd.autocomplete("setting")
async def config_id_ac(interaction:discord.Interaction,current:str):
    return [discord.app_commands.Choice(name=k,value=k) for k in _ID_DEF if current.lower() in k.lower()][:25]

@bot.tree.command(name="config_message",description="Update a bot message (welcome, boost).",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def config_msg_cmd(interaction:discord.Interaction,key:str,text:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    key=key.upper().strip()
    if key not in _MSG_LABELS: return await interaction.response.send_message(f"Unknown key. Available:\n{chr(10).join(f'`{k}` — {v}' for k,v in _MSG_LABELS.items())}",ephemeral=True)
    _smsg(interaction.guild.id,key,text)
    await interaction.response.send_message(f"`{key}` updated.",ephemeral=True)

@config_msg_cmd.autocomplete("key")
async def config_msg_ac(interaction:discord.Interaction,current:str):
    return [discord.app_commands.Choice(name=k,value=k) for k in _MSG_LABELS if current.lower() in k.lower()][:25]

@bot.tree.command(name="bot_edit",description="Update the bot's username or avatar.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def bot_edit_cmd(interaction:discord.Interaction,name:str=None,avatar_url:str=None):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if not name and not avatar_url: return await interaction.response.send_message("Please provide `name` and/or `avatar_url`.",ephemeral=True)
    await interaction.response.defer(ephemeral=True); kw={}
    if name: kw["username"]=name
    if avatar_url:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(avatar_url) as r:
                    if r.status==200: kw["avatar"]=await r.read()
                    else: return await interaction.followup.send(f"Could not fetch avatar (HTTP {r.status}).",ephemeral=True)
        except ImportError: return await interaction.followup.send("aiohttp is not installed.",ephemeral=True)
    try:
        await bot.user.edit(**kw)
        parts=[]
        if name: parts.append(f"Username → **{name}**")
        if avatar_url: parts.append("Avatar updated")
        await interaction.followup.send(" | ".join(parts),ephemeral=True)
    except Exception as e: await interaction.followup.send(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="send",description="Send a message as the bot (embed, image, link button).",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def send_cmd(interaction:discord.Interaction,channel:discord.TextChannel,message:str,
    embed:bool=True,color:str="black",image:bool=False,image_url:str=None,
    link_button:bool=False,link_url:str=None,link_label:str="Open"):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if image and not image_url: return await interaction.response.send_message("Please provide `image_url` when `image` is enabled.",ephemeral=True)
    if link_button and not link_url: return await interaction.response.send_message("Please provide `link_url` when `link_button` is enabled.",ephemeral=True)
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
        await interaction.response.send_message("Message sent.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="say",description="Send a plain text message as the bot.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def say_cmd(interaction:discord.Interaction,channel:discord.TextChannel,text:str):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    try:
        await channel.send(text); await interaction.response.send_message("Message sent.",ephemeral=True)
    except discord.Forbidden: await interaction.response.send_message("I am missing permissions for that channel.",ephemeral=True)
    except Exception as e: await interaction.response.send_message(f"Error: {e}",ephemeral=True)

@bot.tree.command(name="whitelist_add",description="Add a user to the security whitelist.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def wl_add(interaction:discord.Interaction,member:discord.Member):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    SECURITY_WHITELIST_USERS.add(member.id)
    await interaction.response.send_message(f"{member.mention} added to the whitelist.",ephemeral=True)

@bot.tree.command(name="whitelist_remove",description="Remove a user from the security whitelist.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def wl_remove(interaction:discord.Interaction,member:discord.Member):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    SECURITY_WHITELIST_USERS.discard(member.id)
    await interaction.response.send_message(f"{member.mention} removed from the whitelist.",ephemeral=True)

@bot.tree.command(name="whitelist_list",description="Show all whitelisted users.",guild=discord.Object(id=ALLOWED_GUILD_ID))
async def wl_list(interaction:discord.Interaction):
    if interaction.user.id not in OWNERS: return await interaction.response.send_message("You do not have permission to do this.",ephemeral=True)
    if not SECURITY_WHITELIST_USERS: return await interaction.response.send_message("The whitelist is empty.",ephemeral=True)
    names=[f"{bot.get_user(uid)} (`{uid}`)" if bot.get_user(uid) else f"Unknown (`{uid}`)" for uid in SECURITY_WHITELIST_USERS]
    await interaction.response.send_message("**Whitelist:**\n"+"\n".join(names),ephemeral=True)

# ================================================================
#  SECURITY EVENTS
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
        await channel.guild.ban(user,reason="Channel deletion — Auto Protection")
        await mlog(channel.guild,"Auto-Ban",f"{user} ({user.id}) deleted #{saved['name']} — banned and channel restored.")
    except: pass
    try:
        kw=dict(name=saved["name"],overwrites=saved["overwrites"],category=saved["category"],position=saved["position"],reason="Auto-Restore")
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
            await channel.guild.ban(user,reason=f"Channel spam ({CREATE_MAX}+ in {CREATE_WIN}s)")
            await mlog(channel.guild,"Auto-Ban",f"{user} ({user.id}) created {len(channel_create_tracker[user.id])} channels in {CREATE_WIN}s — banned.")
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
        await role.guild.ban(user,reason="Role deletion — Auto Protection")
        await mlog(role.guild,"Auto-Ban",f"{user} ({user.id}) deleted role **{saved['name']}** — banned and role restored.")
    except: pass
    try:
        await role.guild.create_role(name=saved["name"],color=saved["color"],permissions=saved["permissions"],hoist=saved["hoist"],mentionable=saved["mentionable"],reason="Auto-Restore")
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
            await role.guild.ban(user,reason=f"Role spam ({CREATE_MAX}+ in {CREATE_WIN}s)")
            await mlog(role.guild,"Auto-Ban",f"{user} ({user.id}) created {len(role_create_tracker[user.id])} roles in {CREATE_WIN}s — banned.")
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
        await channel.guild.ban(user,reason="Webhook attack — Auto Protection")
        await mlog(channel.guild,"Auto-Ban",f"{user} ({user.id}) created a webhook — banned.")
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
            await guild.ban(actor,reason="Mass ban (2+ in 20s)")
            await mlog(guild,"Auto-Ban",f"{actor} ({actor.id}) banned 2+ members in 20s — banned.")
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
                    await entry.guild.ban(actor,reason="Mass timeout (2+ in 15s)")
                    await mlog(entry.guild,"Auto-Ban",f"{actor} ({actor.id}) timed out 2+ members in 15s — banned.")
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
                await role.edit(permissions=p,reason="Admin permission grant blocked")
            except: pass
            m=entry.guild.get_member(actor.id)
            if m:
                try:
                    await m.kick(reason="Attempted to grant administrator permission")
                    await mlog(entry.guild,"Admin Perm Blocked",f"{actor} ({actor.id}) tried to grant admin to **{role.name}** — perm removed, user kicked.")
                except: pass

    if entry.action==discord.AuditLogAction.guild_update:
        actor=entry.user
        if actor and not actor.bot:
            await mlog(entry.guild,"Server Updated",f"{actor} ({actor.id}) modified server settings.")

    if entry.action==discord.AuditLogAction.bot_add:
        actor=entry.user; ba=entry.target
        await mlog(entry.guild,"Bot Added",f"{actor} ({actor.id}) added bot {ba} ({getattr(ba,'id','?')}).")

# ================================================================
#  HELP
# ================================================================

@bot.command(name="help")
async def help_cmd(ctx:commands.Context):
    if ctx.guild.id!=ALLOWED_GUILD_ID: return
    embed=discord.Embed(title="Command Overview",color=discord.Color.from_rgb(149,165,166),timestamp=datetime.utcnow())
    embed.add_field(name="Moderation",value=(
        "`?kick` `?ban` `?unban` `?unbanall`\n"
        "`?timeout` `?rto` `?purge` `?slowmode`\n"
        "`?warn` `?warns` `?clearwarn` `?clearwarns`\n"
        "Also available as slash commands."),inline=False)
    embed.add_field(name="Roles",value=(
        "`?role @user <name/ID>` — Toggle a role\n"
        "`?roleall @role` — Assign to all members\n"
        "`?rolecreate <name>` — Create with permissions\n"
        "`?roleinfo <name>` | Also `/role` `/roleall`"),inline=False)
    embed.add_field(name="Hackban",value=(
        "`?hackban @user` | `?hackban_addalt <ID> <AltID>`\n"
        "`?unhackban <ID>` | Also as slash commands."),inline=False)
    embed.add_field(name="Tickets",value=(
        "`?close` `?delete`\n"
        "`/adduser` `/removeuser` `/renameticket`\n"
        "`/setup` — Ticket panel & configuration"),inline=False)
    embed.add_field(name="Security",value="`/enable <module>` `/disable <module>` `/modules`",inline=False)
    embed.add_field(name="Config (Owner)",value=(
        "`/config_id` `/config_message` `/bot_edit`\n"
        "`/send` `/say` `/whitelist_add|remove|list`"),inline=False)
    embed.add_field(name="Public",value=(
        "`/avatar` `/serverinfo` `/roleinfo`\n"
        "`/invite` `/leaderboard` `/afk` `/alts`"),inline=False)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

# ================================================================
#  NEW FEATURES APPENDED BELOW
# ================================================================

# ================================================================
#  NIGHT MODE — auto disable/enable role perms on schedule
# ================================================================
# Roles that get their permissions stripped at 22:00 and restored at 09:00
NIGHT_MODE_ROLES = [
    1516514623413813488,
    1516453412106014851,
    1516457574151749724,
]

# Store saved permissions between disable and re-enable
_night_saved_perms: dict[int, discord.Permissions] = {}


async def night_mode_loop():
    """Runs every minute, checks time, disables/enables role perms."""
    await bot.wait_until_ready()
    last_action: str | None = None   # "off" or "on" — avoid repeating same action
    while True:
        now_utc = datetime.utcnow()
        hour    = now_utc.hour    # UTC — adjust offset if server is on different TZ

        action = None
        if hour == 22 and last_action != "off":
            action = "off"
        elif hour == 9 and last_action != "on":
            action = "on"

        if action:
            for guild in bot.guilds:
                if guild.id != ALLOWED_GUILD_ID:
                    continue
                for role_id in NIGHT_MODE_ROLES:
                    role = guild.get_role(role_id)
                    if not role:
                        continue
                    if action == "off":
                        # Save current permissions and remove all
                        _night_saved_perms[role.id] = role.permissions
                        try:
                            await role.edit(
                                permissions=discord.Permissions.none(),
                                reason="Night Mode — 22:00 auto-disable")
                        except Exception:
                            pass
                    else:
                        # Restore saved permissions (or leave as-is if no save)
                        saved = _night_saved_perms.get(role.id)
                        if saved:
                            try:
                                await role.edit(
                                    permissions=saved,
                                    reason="Night Mode — 09:00 auto-enable")
                            except Exception:
                                pass
            last_action = action

        await asyncio.sleep(60)


# Register the night-mode loop in on_ready
_orig_ready = bot.get_listener("on_ready")

@bot.event
async def on_ready():
    print(f"Online: {bot.user}")
    try:
        await bot.tree.sync(guild=discord.Object(id=ALLOWED_GUILD_ID))
    except Exception:
        pass
    asyncio.create_task(voice_loop())
    asyncio.create_task(tracker_cleanup())
    asyncio.create_task(night_mode_loop())       # ← night mode task
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
#  BOT-ADD SECURITY — kick bot, ban adder
# ================================================================

@bot.event
async def on_member_join_bot(member: discord.Member):
    """Fires when any member joins; we filter for bots below."""
    pass  # handled inside the main on_member_join via audit log


# Override the security part inside on_audit_log_entry_create
# (we already have that event; just add bot_add action handling there)
# The existing on_audit_log_entry_create already logs bot_add.
# We extend it to also kick the bot and ban the adder.
# We do this by monkey-patching the existing listener is not clean,
# so we register a second listener via bot.add_listener.

async def _on_audit_bot_add_security(entry: discord.AuditLogEntry):
    if entry.guild.id != ALLOWED_GUILD_ID: return
    if entry.action != discord.AuditLogAction.bot_add: return

    added_bot = entry.target
    actor     = entry.user

    # Kick the added bot (if still in server)
    if added_bot:
        member = entry.guild.get_member(added_bot.id)
        if member:
            try:
                await member.kick(reason="Unauthorized bot addition — Auto Security")
            except Exception:
                pass

    # Ban the person who added the bot (unless owner/whitelisted)
    if actor and not whitelisted(actor) and actor.id not in OWNERS:
        m = entry.guild.get_member(actor.id)
        if m and bot_can_act(entry.guild, m):
            try:
                await entry.guild.ban(
                    actor,
                    reason="Added an unauthorized bot — Auto Security")
                await mlog(entry.guild, "Auto-Ban",
                    f"{actor} ({actor.id}) added bot {added_bot} "
                    f"({getattr(added_bot, 'id', '?')}) — bot kicked, adder banned.")
            except Exception:
                pass

bot.add_listener(_on_audit_bot_add_security, "on_audit_log_entry_create")


# ================================================================
#  MASS-PING BAN — @everyone/@here 2+ times in 5s → BAN + strip roles
# ================================================================
# The existing anti_mention module already times out users.
# This new rule is separate and stricter: ban after 2 pings in 5s.
# We hook into on_message via a second listener.

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
            # Strip admin roles first
            for r in list(m.roles):
                if r.permissions.administrator and r < message.guild.me.top_role:
                    try: await m.remove_roles(r, reason="Mass ping — admin role stripped")
                    except Exception: pass
            # Ban the user
            try:
                await message.guild.ban(
                    m,
                    reason=f"Mass ping abuse — {PING_MAX}+ @everyone/@here in {PING_WINDOW}s",
                    delete_message_days=1)
                await mlog(message.guild, "Auto-Ban",
                    f"{m} ({m.id}) sent {len(mass_ping_tracker[m.id])} "
                    f"mass pings in {PING_WINDOW}s — admin roles stripped + banned.")
            except Exception:
                pass
            mass_ping_tracker[message.author.id].clear()

bot.add_listener(_on_message_mass_ping_ban, "on_message")


# ================================================================
#  /role_for_all_channels — apply a role's permissions to all channels
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
    """Multi-select to pick which permissions the role should have in all channels."""
    def __init__(self):
        options = [
            discord.SelectOption(
                label=p.replace("_", " ").title(), value=p)
            for p in _PERM_FLAGS_READABLE
        ]
        super().__init__(
            placeholder="Select permissions to ALLOW…",
            options=options,
            min_values=0,
            max_values=len(options),
            custom_id="rac_allow_sel")

    async def callback(self, interaction: discord.Interaction):
        # Store selection in the parent view
        self.view.allowed_perms = set(interaction.data["values"])
        await interaction.response.defer()


class RoleAllChannelsDenySelect(discord.ui.Select):
    """Multi-select to pick which permissions to DENY."""
    def __init__(self):
        options = [
            discord.SelectOption(
                label=p.replace("_", " ").title(), value=p)
            for p in _PERM_FLAGS_READABLE
        ]
        super().__init__(
            placeholder="Select permissions to DENY…",
            options=options,
            min_values=0,
            max_values=len(options),
            custom_id="rac_deny_sel")

    async def callback(self, interaction: discord.Interaction):
        self.view.denied_perms = set(interaction.data["values"])
        await interaction.response.defer()


class RoleAllChannelsView(discord.ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=180)
        self.role          = role
        self.allowed_perms : set[str] = set()
        self.denied_perms  : set[str] = set()
        self.add_item(RoleAllChannelsPermSelect())
        self.add_item(RoleAllChannelsDenySelect())

    @discord.ui.button(label="Apply to all channels",
                       style=discord.ButtonStyle.success, row=2)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNERS:
            return await interaction.response.send_message(
                "You do not have permission to do this.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        count   = 0
        errors  = 0
        guild   = interaction.guild
        role    = self.role

        for ch in guild.channels:
            ow = ch.overwrites_for(role)
            # Apply allowed
            for perm in self.allowed_perms:
                if hasattr(ow, perm):
                    setattr(ow, perm, True)
            # Apply denied
            for perm in self.denied_perms:
                if hasattr(ow, perm):
                    setattr(ow, perm, False)
            try:
                await ch.set_permissions(role, overwrite=ow,
                    reason=f"/role_for_all_channels by {interaction.user}")
                count += 1
            except Exception:
                errors += 1
            await asyncio.sleep(0.3)   # rate-limit friendly

        summary_allow = ", ".join(self.allowed_perms) or "none"
        summary_deny  = ", ".join(self.denied_perms)  or "none"
        await interaction.followup.send(
            f"Done. **{role.name}** updated in **{count}** channel(s) "
            f"(errors: {errors}).\n"
            f"Allowed: `{summary_allow}`\n"
            f"Denied: `{summary_deny}`",
            ephemeral=True)
        await mlog(guild, "Role Applied to All Channels",
            f"{interaction.user} applied **{role.name}** to {count} channels. "
            f"Allow: {summary_allow} | Deny: {summary_deny}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


@bot.tree.command(
    name="role_for_all_channels",
    description="Apply custom permission overrides for a role across all channels.",
    guild=discord.Object(id=ALLOWED_GUILD_ID))
async def role_for_all_channels(interaction: discord.Interaction, role: discord.Role):
    if interaction.user.id not in OWNERS:
        return await interaction.response.send_message(
            "You do not have permission to do this.", ephemeral=True)
    embed = discord.Embed(
        title="Role — All Channels",
        description=(
            f"Configuring **{role.name}** across all channels.\n\n"
            "1. Select which permissions to **allow**.\n"
            "2. Select which permissions to **deny**.\n"
            "3. Click **Apply to all channels**."),
        color=discord.Color.from_rgb(149, 165, 166))
    view = RoleAllChannelsView(role)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ================================================================
#  RUN
# ================================================================

bot.run(TOKEN)
