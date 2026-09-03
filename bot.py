#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 PREMIUM AI GROUP MANAGER BOT
 Single-file Telegram bot (python-telegram-bot v21, async)
 AI Brain: Grok (xAI) - with multi-key rotation & fallback
 Database: SQLite (auto-backed-up to a Telegram channel every 30 min)
=====================================================================

WHAT THIS BOT DOES (summary):
 - Understands admin/owner commands in natural language (Hindi/English/
   Hinglish) when the message ends with ".." -- NOT keyword based.
 - Only processes ".." commands if the sender is actually a group admin
   (checked via Telegram API) -- no wasted AI calls, no impersonation.
 - Full moderation: ban/unban/kick/mute/unmute/warn/promote/demote/
   pin/unpin/delete -- all admin, all natural language.
 - purge & lock/unlock are OWNER-ONLY.
 - dispute freeze (OWNER-ONLY, natural language, needs "..").
 - trust-level / "Trusted Trader" system, upgraded only by OWNER
   ("isko upgrade karo" style natural language).
 - Smart welcome message with profile photo, name, ID, username,
   profile link, ESCROW disclaimer (bold, English), green buttons.
 - Admin panel via bot DM: manage welcome-message channel buttons,
   export / import full database.
 - Anti-link / anti-username promotion guard -- cheap local regex
   pre-filter (only fires AI when a URL/dot-domain/@username pattern
   is actually present), then AI checks context: was this link asked
   for by an admin/owner? If not => delete + warn.
 - Escrow-impersonation guard: anyone claiming to provide escrow who
   is NOT the owner's username gets blocked automatically.
 - Admin/Owner impersonation detector: compares new members'
   name/username/bio/photo (perceptual hash) against the owner's
   profile; % match is shown; auto re-checked after a delay.
 - Anti-raid: mass-join flood gets auto-removed.
 - Antiflood + duplicate-message flood protection.
 - Gaali/abuse-word detection (fast local keyword/regex list --
   deliberately NOT AI, so it's instant) -> delete + 30 min mute + warn.
 - Ghost/deleted-account nightly cleanup.
 - Persistent ban + blacklist enforcement across restarts.
 - Warn auto-expiry after 7 days.
 - /trusted command listing all Trusted Traders.
 - Full database auto-backup to a private channel every 30 minutes
   (Railway wipes local storage on redeploy) + manual Export/Import.

HONEST LIMITATIONS (please read):
 1. Telegram's Bot API does NOT expose account-creation-date for any
    user. No bot (however advanced) can know exactly when an account
    was made. This is a hard platform limitation, not a code gap.
 2. "Vision AI" photo-matching was intentionally REMOVED per your
    instruction -- only free perceptual-hashing (pHash) is used for
    profile-photo comparison. It compares photos directly, no extra
    API key or cost.
 3. Anti-raid "real vs fake" detection is a best-effort heuristic
    (join speed + missing username/photo). It cannot be 100% perfect
    -- Telegram gives no stronger signal to a bot.
=====================================================================
"""

import os
import re
import io
import json
import time
import sqlite3
import logging
import asyncio
import unicodedata
import inspect
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    InputFile,
    MessageEntity,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError, BadRequest, Conflict as TelegramConflictError, NetworkError, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    ExtBot,
    filters,
)
from telegram.request import HTTPXRequest

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("group_manager_bot")
logging.getLogger("httpx").setLevel(logging.WARNING)

def md_escape(text):
    """HTML-escape names/usernames before putting them into an HTML-parse-mode
    message. (Bot now uses ParseMode.HTML everywhere -- much more reliable
    than legacy Markdown, which broke on underscores in usernames and only
    ever supported single-asterisk bold, not the **double-asterisk** bold
    used throughout this file.) Function name kept as md_escape so all
    existing call-sites don't need touching."""
    if text is None:
        return ""
    text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =============================================================================
# CUSTOM FANCY FONT (owner-provided small-caps style)
# Applied to the bot's own static label/message text everywhere. NEVER
# applied to: HTML tag syntax, <code>...</code> content (usernames/user IDs
# -- kept normal + tap-to-copy monospace as requested), or to <a>...</a>
# link text (that's always someone's actual name in this bot).
# =============================================================================
_FANCY_LETTERS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
}
_FANCY_DIGITS = {
    "0": "𝟎", "1": "𝟏", "2": "𝟐", "3": "𝟑", "4": "𝟒",
    "5": "𝟓", "6": "𝟔", "7": "𝟕", "8": "𝟖", "9": "𝟗",
}


def fancy(text: str) -> str:
    """Convert plain ASCII letters/digits in STATIC bot text into the
    owner's custom small-caps font. Leaves emojis, spaces, punctuation, and
    non-Latin characters untouched."""
    if not text:
        return text
    out = []
    for ch in text:
        low = ch.lower()
        if low in _FANCY_LETTERS:
            out.append(_FANCY_LETTERS[low])
        elif ch in _FANCY_DIGITS:
            out.append(_FANCY_DIGITS[ch])
        else:
            out.append(ch)
    return "".join(out)


_custom_emoji_cache_by_name = {}   # name -> (placeholder_char, custom_emoji_id)
_custom_emoji_cache_by_char = {}   # placeholder_char -> (name, custom_emoji_id)


def _refresh_custom_emoji_cache():
    """Reloads the in-memory emoji cache from DB. Called at startup and
    after every save/rename/delete -- keeps rendering DB-free on the hot path."""
    global _custom_emoji_cache_by_name, _custom_emoji_cache_by_char
    conn = db_connect()
    rows = conn.execute("SELECT name, placeholder_char, custom_emoji_id FROM custom_emojis").fetchall()
    conn.close()
    by_name, by_char = {}, {}
    for r in rows:
        by_name[r["name"]] = (r["placeholder_char"], r["custom_emoji_id"])
        if r["placeholder_char"]:
            by_char[r["placeholder_char"]] = (r["name"], r["custom_emoji_id"])
    _custom_emoji_cache_by_name = by_name
    _custom_emoji_cache_by_char = by_char


_EMOJI_NAME_TOKEN_RE = r"\{(?P<ename>[\w\u0900-\u097F]+)\}"


def stylize(html_text: str) -> str:
    """Apply fancy() to a FULLY-COMPOSED HTML message, automatically
    skipping what must stay normal: HTML tag syntax itself, <code>...</code>
    content (usernames/IDs -- stays tap-to-copy monospace), and <a>...</a>
    link text (always someone's actual name in this bot, not label text).
    NOTE: does NOT touch custom/premium emoji -- Telegram's <tg-emoji> HTML
    tag does not reliably render for bot-sent messages, so anywhere premium
    emoji needs to actually work, use render_with_emojis() + entities=
    instead of stylize() + parse_mode=HTML (see that function's docstring)."""
    if not html_text:
        return html_text
    tokens = re.split(r"(<[^>]+>)", html_text)
    result = []
    skip_mode = False
    for tok in tokens:
        if tok.startswith("<"):
            low = tok.lower()
            if low.startswith("<a ") or low.startswith("<code"):
                skip_mode = True
            elif low.startswith("</a>") or low.startswith("</code>"):
                skip_mode = False
            result.append(tok)  # tags always pass through untouched
        else:
            result.append(tok if skip_mode else fancy(tok))
    return "".join(result)


def _html_unescape_safe(s: str) -> str:
    """Decodes the small set of entities md_escape() produces. Needed
    because this pipeline sends via `entities=` (bypassing Telegram's own
    HTML parser, which normally does this decoding automatically) -- so
    without this, escaped text like "&lt;" would show up literally instead
    of being decoded back to "<"."""
    return (s.replace("&lt;", "<").replace("&gt;", ">")
              .replace("&quot;", '"').replace("&#39;", "'")
              .replace("&amp;", "&"))


def render_with_emojis(html_text: str) -> tuple:
    """Converts our small HTML subset (<b>, <code>, <pre>, <a href>) PLUS
    automatic premium-emoji substitution ({name} tokens AND any plain emoji
    that has a saved premium alternate) into (plain_text, entities) for
    sending WITHOUT parse_mode. This is the ONLY reliable way to make real
    custom/premium emoji show up in a bot-sent message -- the <tg-emoji>
    HTML tag was tried first but confirmed (via a real device screenshot)
    to render as literal text instead of an emoji, so real
    MessageEntity(CUSTOM_EMOJI) objects are used here instead, exactly
    like Telegram's own clients do it."""
    if not html_text:
        return "", []

    has_emoji_map = bool(_custom_emoji_cache_by_name or _custom_emoji_cache_by_char)
    if has_emoji_map and _custom_emoji_cache_by_char:
        char_alt = "|".join(re.escape(c) for c in _custom_emoji_cache_by_char.keys())
        emoji_pattern = re.compile(f"{_EMOJI_NAME_TOKEN_RE}|(?P<echar>{char_alt})")
    elif has_emoji_map:
        emoji_pattern = re.compile(_EMOJI_NAME_TOKEN_RE)
    else:
        emoji_pattern = None

    tokens = re.split(r"(<[^>]+>)", html_text)
    out = []
    entities = []
    open_stack = []
    utf16_pos = 0

    def emit_text(chunk, apply_fancy):
        nonlocal utf16_pos
        chunk = _html_unescape_safe(chunk)
        if emoji_pattern is None:
            piece = fancy(chunk) if apply_fancy else chunk
            out.append(piece)
            utf16_pos += _utf16_len(piece)
            return
        last = 0
        for m in emoji_pattern.finditer(chunk):
            pre = chunk[last:m.start()]
            if pre:
                piece = fancy(pre) if apply_fancy else pre
                out.append(piece)
                utf16_pos += _utf16_len(piece)
            gd = m.groupdict()
            handled = False
            eid = None
            echar = None
            if gd.get("ename"):
                key = gd["ename"].lower()
                if key in _custom_emoji_cache_by_name:
                    echar, eid = _custom_emoji_cache_by_name[key]
                    handled = True
            elif gd.get("echar") and gd["echar"] in _custom_emoji_cache_by_char:
                echar = gd["echar"]
                _, eid = _custom_emoji_cache_by_char[echar]
                handled = True
            if handled:
                out.append(echar)
                elen = _utf16_len(echar)
                entities.append(MessageEntity(type=MessageEntity.CUSTOM_EMOJI, offset=utf16_pos, length=elen, custom_emoji_id=eid))
                utf16_pos += elen
            else:
                piece = fancy(m.group(0)) if apply_fancy else m.group(0)
                out.append(piece)
                utf16_pos += _utf16_len(piece)
            last = m.end()
        tail = chunk[last:]
        if tail:
            piece = fancy(tail) if apply_fancy else tail
            out.append(piece)
            utf16_pos += _utf16_len(piece)

    for tok in tokens:
        if tok.startswith("<") and tok.endswith(">"):
            low = tok.lower()
            closing = low.startswith("</")
            tagname = None
            href = None
            if low.startswith("<b>") or low == "</b>":
                tagname = "b"
            elif low.startswith("<code") or low.startswith("</code"):
                tagname = "code"
            elif low.startswith("<pre") or low.startswith("</pre"):
                tagname = "pre"
            elif low.startswith("<a ") or low == "</a>":
                tagname = "a"
                if not closing:
                    hm = re.search(r"href=['\"]([^'\"]*)['\"]", tok, re.IGNORECASE)
                    href = hm.group(1) if hm else None
            if tagname:
                if closing:
                    for idx in range(len(open_stack) - 1, -1, -1):
                        if open_stack[idx]["tag"] == tagname:
                            opened = open_stack.pop(idx)
                            length = utf16_pos - opened["start"]
                            if length > 0:
                                if tagname == "b":
                                    entities.append(MessageEntity(type=MessageEntity.BOLD, offset=opened["start"], length=length))
                                elif tagname == "code":
                                    entities.append(MessageEntity(type=MessageEntity.CODE, offset=opened["start"], length=length))
                                elif tagname == "a" and opened.get("url"):
                                    entities.append(MessageEntity(type=MessageEntity.TEXT_LINK, offset=opened["start"], length=length, url=opened["url"]))
                            break
                else:
                    open_stack.append({"tag": tagname, "start": utf16_pos, "url": href})
            # unknown tag -> drop silently (our HTML is controlled/generated, shouldn't occur)
        else:
            apply_fancy = not any(o["tag"] in ("a", "code") for o in open_stack)
            emit_text(tok, apply_fancy)

    entities.sort(key=lambda e: e.offset)
    return "".join(out), entities


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
# NOTE: Sirf BOT_TOKEN Railway ke "Variables" tab me daalna hai (security ke
# liye token env var me rakhna best practice hai). BAAKI SAB NEECHE seedhe
# CODE ME hi likha hai jaisa tumne bola -- yahin edit kar dena jo bhi change
# karna ho, Railway Variables me kuch nahi jaana.
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()   # <-- Railway Variables me daalna hai

# 👇 Grok (xAI) API keys -- yeh Railway ke VARIABLES me daalni hain (GitHub secret
# -scanning code me seedhi keys likhne par push block kar deta hai, isliye yeh
# ek cheez env var se aa rahi hai). Railway Variables me naya variable banao:
#   Name:  GROK_API_KEYS
#   Value: key1,key2,key3,key4,key5   (sabko comma se jodkar, space mat dena)
#
# NOTE: Yeh switched hai xAI (Grok) se Groq (console.groq.com) par -- xAI ka
# API ab bina billing ke kaam nahi karta aur Indian cards accept nahi karta,
# isliye Groq use ho raha hai (free tier, no card needed). Variable ka naam
# GROK_API_KEYS hi rakha hai taaki Railway me kuch rename na karna pade --
# usme ab Groq ki "gsk_..." keys jaani hain.
GROK_API_KEYS = [k.strip() for k in os.environ.get("GROK_API_KEYS", "").split(",") if k.strip()]

GROK_MODEL = "openai/gpt-oss-120b"   # Groq ka current recommended general-purpose model
GROK_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

# 👑 Owner (tumhara) Telegram user ID aur username -- already daal diya hai
OWNER_ID = 7892255798
OWNER_USERNAME = "TSIW01"   # bina @ ke

# Premium/custom emoji IDs for specific buttons (Bot API 9.4 icon_custom_emoji_id --
# requires owner's account to have Telegram Premium, which it does).
CHANNEL_BUTTON_EMOJI_ID = "5976567633720383369"
CONTACT_OWNER_BUTTON_EMOJI_ID = "6129404354186187988"

# 🗄️ Backup channel ki ID yahan daalo (bot ko us channel me admin banana hoga)
# Channel ID nikalne ka tarika README.md me likha hai
BACKUP_CHANNEL_ID = ""   # 👈 yahan apne backup channel ki ID daalo, jaise "-1001234567890"

DB_PATH = "botdata.db"   # local file; auto-backed-up to your channel every 30 min
DB_BACKUP_FILENAME = "group_manager_backup.json"  # fixed name/format -- required for import to accept it


# Colors available on Bot API 9.4 buttons: "primary" (blue), "success" (green), "danger" (red)
BTN_GREEN = "success"
BTN_BLUE = "primary"
BTN_RED = "danger"

IST = timezone(timedelta(hours=5, minutes=30))


# =============================================================================
# DATABASE LAYER
# =============================================================================
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def db_init():
    conn = db_connect()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            chat_id INTEGER,
            join_date TEXT,
            trust_level INTEGER DEFAULT 0,
            escrow_verified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            reason TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            added_by INTEGER,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER,
            chat_id INTEGER,
            reason TEXT,
            timestamp TEXT,
            PRIMARY KEY (user_id, chat_id)
        );

        CREATE TABLE IF NOT EXISTS welcome_channels (
            username TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS admin_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            admin_name TEXT,
            action TEXT,
            target_id INTEGER,
            details TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS impersonators (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            match_percent INTEGER,
            flagged_at TEXT
        );

        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER,
            seller_id INTEGER,
            started_by INTEGER,
            chat_id INTEGER,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS group_access (
            chat_id INTEGER,
            user_id INTEGER,
            granted_by INTEGER,
            granted_at TEXT,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            welcome_text TEXT,
            button_text TEXT,
            button_url TEXT,
            channel_username TEXT,
            group_title TEXT
        );

        CREATE TABLE IF NOT EXISTS filters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            trigger TEXT,
            reply_text TEXT,
            file_id TEXT,
            file_type TEXT,
            added_by INTEGER,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS custom_emojis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            custom_emoji_id TEXT UNIQUE,
            placeholder_char TEXT,
            name TEXT,
            added_by INTEGER,
            added_at TEXT
        );

        CREATE TABLE IF NOT EXISTS known_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS approved_groups (
            chat_id INTEGER PRIMARY KEY,
            approved_by INTEGER,
            approved_at TEXT
        );
        """
    )

    # One-time grandfather migration: groups the bot was already active in
    # BEFORE this approval system existed should keep working without the
    # owner having to manually /approve every single one retroactively.
    # Only ever runs once (guarded by a flag in settings).
    already_migrated = cur.execute("SELECT value FROM settings WHERE key='migrated_approved_groups'").fetchone()
    if not already_migrated:
        cur.execute(
            "INSERT OR IGNORE INTO approved_groups (chat_id, approved_by, approved_at) "
            "SELECT chat_id, NULL, ? FROM known_groups",
            (datetime.now(IST).isoformat(),),
        )
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('migrated_approved_groups', '1')")

    conn.commit()
    conn.close()

    # Seed default welcome-message channel(s) if none exist yet.
    # (Owner said they couldn't get the panel button working, so this
    # guarantees the channel button shows up without needing the panel.)
    DEFAULT_WELCOME_CHANNELS = ["SRK_ERA"]
    conn2 = db_connect()
    existing = conn2.execute("SELECT COUNT(*) c FROM welcome_channels").fetchone()["c"]
    if existing == 0:
        for ch in DEFAULT_WELCOME_CHANNELS:
            conn2.execute("INSERT OR IGNORE INTO welcome_channels (username) VALUES (?)", (ch,))
        conn2.commit()
    conn2.close()


def db_export_json() -> str:
    """Dump the whole DB into the fixed backup JSON format."""
    conn = db_connect()
    data = {"_format": "group_manager_backup_v1", "_exported_at": datetime.now(IST).isoformat()}
    for table in [
        "users", "warns", "blacklist", "banned_users", "welcome_channels",
        "admin_log", "impersonators", "deals", "settings",
        "group_access", "group_settings", "filters", "custom_emojis",
    ]:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        data[table] = [dict(r) for r in rows]
    conn.close()
    return json.dumps(data, ensure_ascii=False, indent=2)


def db_import_json(raw: str) -> tuple[bool, str]:
    """Validate and import a backup JSON. Only accepts our exact fixed format."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "❌ <b>Invalid file — yeh JSON file nahi hai.</b>"

    if data.get("_format") != "group_manager_backup_v1":
        return False, "❌ <b>Yeh file is bot ke database format se match nahi karti. Import reject kiya gaya.</b>"

    required_tables = [
        "users", "warns", "blacklist", "banned_users", "welcome_channels",
        "admin_log", "impersonators", "deals", "settings",
    ]
    for t in required_tables:
        if t not in data or not isinstance(data[t], list):
            return False, f"❌ <b>File corrupt lag rahi hai — '{t}' table missing/invalid hai.</b>"

    try:
        conn = db_connect()
        cur = conn.cursor()
        for t in required_tables + [t for t in ("group_access", "group_settings", "filters", "custom_emojis") if t in data]:
            cur.execute(f"DELETE FROM {t}")
            rows = data[t]
            if not rows:
                continue
            cols = list(rows[0].keys())
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            for row in rows:
                cur.execute(
                    f"INSERT INTO {t} ({col_str}) VALUES ({placeholders})",
                    [row.get(c) for c in cols],
                )
        conn.commit()
        conn.close()
        _refresh_custom_emoji_cache()
        return True, "✅ <b>Database successfully import ho gaya!</b>"
    except Exception as e:
        logger.exception("Import failed")
        return False, f"❌ <b>Import ke दौरान error aaya: <code>{e}</code></b>\nDatabase change nahi kiya gaya (safe rollback)."


# --- small DB helpers -------------------------------------------------------
def upsert_user(user_id, username, first_name, chat_id):
    cache_username(user_id, username, first_name)  # keep in-memory username cache fresh too
    conn = db_connect()
    row = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET username=?, first_name=?, chat_id=? WHERE user_id=?",
            (username, first_name, chat_id, user_id),
        )
    else:
        conn.execute(
            "INSERT INTO users (user_id, username, first_name, chat_id, join_date, trust_level, escrow_verified) "
            "VALUES (?,?,?,?,?,0,0)",
            (user_id, username, first_name, chat_id, datetime.now(IST).isoformat()),
        )
    conn.commit()
    conn.close()


def add_warn(user_id, chat_id, reason):
    conn = db_connect()
    conn.execute(
        "INSERT INTO warns (user_id, chat_id, reason, timestamp) VALUES (?,?,?,?)",
        (user_id, chat_id, reason, datetime.now(IST).isoformat()),
    )
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) c FROM warns WHERE user_id=? AND chat_id=?", (user_id, chat_id)
    ).fetchone()["c"]
    conn.close()
    return count


def clear_expired_warns():
    """Warn reset after 7 days."""
    cutoff = (datetime.now(IST) - timedelta(days=7)).isoformat()
    conn = db_connect()
    conn.execute("DELETE FROM warns WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()


def get_warn_count(user_id, chat_id):
    conn = db_connect()
    c = conn.execute(
        "SELECT COUNT(*) c FROM warns WHERE user_id=? AND chat_id=?", (user_id, chat_id)
    ).fetchone()["c"]
    conn.close()
    return c


def log_admin_action(admin_id, admin_name, action, target_id, details):
    conn = db_connect()
    conn.execute(
        "INSERT INTO admin_log (admin_id, admin_name, action, target_id, details, timestamp) VALUES (?,?,?,?,?,?)",
        (admin_id, admin_name, action, target_id, details, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()


def set_trust_level(user_id, level):
    conn = db_connect()
    conn.execute("UPDATE users SET trust_level=? WHERE user_id=?", (level, user_id))
    conn.commit()
    conn.close()


def get_trust_level(user_id):
    conn = db_connect()
    row = conn.execute("SELECT trust_level FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["trust_level"] if row else 0


TRUST_LEVELS = {
    0: "🆕 New Member",
    1: "🙂 Known Member",
    2: "⭐ Trusted Trader",
    3: "💎 Verified Trader",
}
TRUST_LEVEL_MAX = max(TRUST_LEVELS.keys())  # abhi 3 -- 4 levels hain (0 se 3)

# Placeholders available: {name} {group} {id} {username} {profile}
# Plus any saved custom/premium emoji via {label}, or just paste the real
# premium emoji directly -- both work automatically (see stylize()).
DEFAULT_WELCOME_TEMPLATE = (
    "🎉 <b>WELCOME to {group}, {name}!</b> 🎉\n\n"
    "🆔 <b>User ID:</b> <code>{id}</code>\n"
    "🔗 <b>Username:</b> {username}\n"
    "👤 <b>Profile:</b> {profile}\n\n"
    "✅ <b>SELLING ALLOWED, BUT ALWAYS USE ESCROW FOR ANY DEAL.</b>\n"
    "🚫 <b>PROMOTION NOT ALLOWED.</b>\n\n"
    "💬 Chat karo, enjoy karo 🎉"
)


def get_all_trusted(chat_id):
    conn = db_connect()
    rows = conn.execute(
        "SELECT user_id, username, first_name, trust_level FROM users WHERE trust_level >= 2 AND chat_id=?",
        (chat_id,),
    ).fetchall()
    conn.close()
    return rows


def get_escrow_verified_users(chat_id):
    conn = db_connect()
    rows = conn.execute(
        "SELECT user_id, username, first_name FROM users WHERE escrow_verified=1 AND chat_id=?",
        (chat_id,),
    ).fetchall()
    conn.close()
    return rows


def add_blacklist(user_id, reason, added_by):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO blacklist (user_id, reason, added_by, timestamp) VALUES (?,?,?,?)",
        (user_id, reason, added_by, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()


def is_blacklisted(user_id):
    conn = db_connect()
    row = conn.execute("SELECT 1 FROM blacklist WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return bool(row)


def record_ban(user_id, chat_id, reason):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO banned_users (user_id, chat_id, reason, timestamp) VALUES (?,?,?,?)",
        (user_id, chat_id, reason, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()


def remove_ban_record(user_id, chat_id):
    conn = db_connect()
    conn.execute("DELETE FROM banned_users WHERE user_id=? AND chat_id=?", (user_id, chat_id))
    conn.commit()
    conn.close()


def get_all_bans(chat_id):
    conn = db_connect()
    rows = conn.execute("SELECT user_id FROM banned_users WHERE chat_id=?", (chat_id,)).fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def add_welcome_channel(username):
    conn = db_connect()
    conn.execute("INSERT OR IGNORE INTO welcome_channels (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()


def remove_welcome_channel(username):
    conn = db_connect()
    conn.execute("DELETE FROM welcome_channels WHERE username=?", (username,))
    conn.commit()
    conn.close()


def get_welcome_channels():
    conn = db_connect()
    rows = conn.execute("SELECT username FROM welcome_channels").fetchall()
    conn.close()
    return [r["username"] for r in rows]


# --- multi-group access -----------------------------------------------------
def grant_group_access(chat_id, user_id, granted_by):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO group_access (chat_id, user_id, granted_by, granted_at) VALUES (?,?,?,?)",
        (chat_id, user_id, granted_by, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()


def revoke_group_access(chat_id, user_id):
    conn = db_connect()
    conn.execute("DELETE FROM group_access WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    conn.close()


def has_group_access(chat_id, user_id):
    conn = db_connect()
    row = conn.execute("SELECT 1 FROM group_access WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    conn.close()
    return bool(row)


def get_user_accessible_groups(user_id):
    conn = db_connect()
    rows = conn.execute("SELECT chat_id FROM group_access WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return [r["chat_id"] for r in rows]


# --- per-group settings (welcome text/button overrides) --------------------
def get_group_settings(chat_id):
    conn = db_connect()
    row = conn.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def set_group_setting(chat_id, field, value):
    """field must be one of: welcome_text, button_text, button_url, channel_username, group_title."""
    conn = db_connect()
    conn.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
    conn.execute(f"UPDATE group_settings SET {field}=? WHERE chat_id=?", (value, chat_id))
    conn.commit()
    conn.close()


# --- filters (Rose-bot style keyword/command auto-reply) -------------------
def add_filter(chat_id, trigger, reply_text, file_id=None, file_type=None, added_by=None):
    conn = db_connect()
    conn.execute("DELETE FROM filters WHERE chat_id=? AND trigger=?", (chat_id, trigger.lower()))
    conn.execute(
        "INSERT INTO filters (chat_id, trigger, reply_text, file_id, file_type, added_by, timestamp) VALUES (?,?,?,?,?,?,?)",
        (chat_id, trigger.lower(), reply_text, file_id, file_type, added_by, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()


def remove_filter(chat_id, trigger):
    conn = db_connect()
    cur = conn.execute("DELETE FROM filters WHERE chat_id=? AND trigger=?", (chat_id, trigger.lower()))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def get_filters(chat_id):
    conn = db_connect()
    rows = conn.execute("SELECT trigger, reply_text, file_id, file_type FROM filters WHERE chat_id=?", (chat_id,)).fetchall()
    conn.close()
    return rows


def find_matching_filter(chat_id, text):
    """Returns the filter row that matches this message text, or None.
    A command-style trigger (starts with '/') matches only as the exact
    first word; a plain keyword trigger matches anywhere in the text."""
    if not text:
        return None
    rows = get_filters(chat_id)
    if not rows:
        return None
    lowered = text.lower().strip()
    first_word = lowered.split()[0] if lowered.split() else ""
    for row in rows:
        trig = row["trigger"]
        if trig.startswith("/"):
            if first_word == trig or first_word == trig.split("@")[0]:
                return row
        else:
            if trig in lowered:
                return row
    return None


# --- custom / premium emoji auto-save --------------------------------------
def save_custom_emoji(custom_emoji_id, placeholder_char, name, added_by):
    conn = db_connect()
    conn.execute(
        "INSERT OR IGNORE INTO custom_emojis (custom_emoji_id, placeholder_char, name, added_by, added_at) VALUES (?,?,?,?,?)",
        (custom_emoji_id, placeholder_char, name, added_by, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()
    _refresh_custom_emoji_cache()


def get_custom_emoji_by_id(custom_emoji_id):
    conn = db_connect()
    row = conn.execute("SELECT * FROM custom_emojis WHERE custom_emoji_id=?", (custom_emoji_id,)).fetchone()
    conn.close()
    return row


def get_custom_emoji_by_name(name):
    conn = db_connect()
    row = conn.execute("SELECT * FROM custom_emojis WHERE name=?", (name.lower(),)).fetchone()
    conn.close()
    return row


def name_taken_by_other(name, custom_emoji_id):
    conn = db_connect()
    row = conn.execute(
        "SELECT 1 FROM custom_emojis WHERE name=? AND custom_emoji_id!=?", (name.lower(), custom_emoji_id)
    ).fetchone()
    conn.close()
    return bool(row)


def list_custom_emojis():
    conn = db_connect()
    rows = conn.execute("SELECT * FROM custom_emojis ORDER BY id").fetchall()
    conn.close()
    return rows


def rename_custom_emoji(old_name, new_name):
    conn = db_connect()
    cur = conn.execute("UPDATE custom_emojis SET name=? WHERE name=?", (new_name.lower(), old_name.lower()))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    _refresh_custom_emoji_cache()
    return ok


def delete_custom_emoji(name):
    conn = db_connect()
    cur = conn.execute("DELETE FROM custom_emojis WHERE name=?", (name.lower(),))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    _refresh_custom_emoji_cache()
    return ok


def get_custom_emoji_map():
    conn = db_connect()
    rows = conn.execute("SELECT name, placeholder_char, custom_emoji_id FROM custom_emojis").fetchall()
    conn.close()
    return {r["name"]: (r["placeholder_char"], r["custom_emoji_id"]) for r in rows}


def count_custom_emojis():
    conn = db_connect()
    n = conn.execute("SELECT COUNT(*) c FROM custom_emojis").fetchone()["c"]
    conn.close()
    return n


def upsert_known_group(chat_id, title):
    conn = db_connect()
    conn.execute(
        "INSERT INTO known_groups (chat_id, title, last_seen) VALUES (?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, last_seen=excluded.last_seen",
        (chat_id, title, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()


def get_known_groups():
    conn = db_connect()
    rows = conn.execute("SELECT chat_id, title FROM known_groups ORDER BY last_seen DESC LIMIT 30").fetchall()
    conn.close()
    return rows


# --- group approval allowlist -----------------------------------------------
_approved_groups_cache = set()


def _refresh_approved_groups_cache():
    global _approved_groups_cache
    conn = db_connect()
    rows = conn.execute("SELECT chat_id FROM approved_groups").fetchall()
    conn.close()
    _approved_groups_cache = {r["chat_id"] for r in rows}


def is_group_approved(chat_id):
    return chat_id in _approved_groups_cache


def approve_group(chat_id, approved_by):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO approved_groups (chat_id, approved_by, approved_at) VALUES (?,?,?)",
        (chat_id, approved_by, datetime.now(IST).isoformat()),
    )
    conn.commit()
    conn.close()
    _refresh_approved_groups_cache()


def disapprove_group(chat_id):
    conn = db_connect()
    cur = conn.execute("DELETE FROM approved_groups WHERE chat_id=?", (chat_id,))
    conn.commit()
    removed = cur.rowcount > 0
    conn.close()
    _refresh_approved_groups_cache()
    return removed


def _utf16_len(s: str) -> int:
    """Telegram entity offsets/lengths are in UTF-16 code units, NOT Python
    codepoints -- most emoji sit outside the BMP and take 2 UTF-16 units."""
    return len(s.encode("utf-16-le")) // 2


def _utf16_to_str_index_map(s: str):
    """idx[i] = python string index for UTF-16 code-unit position i (needed
    to correctly pull out an emoji's exact glyph substring from a raw
    Telegram message using its UTF-16-based entity offset/length)."""
    mapping = []
    for i, ch in enumerate(s):
        mapping.append(i)
        if ord(ch) > 0xFFFF:
            mapping.append(i)
    mapping.append(len(s))
    return mapping


def auto_save_new_emojis_from_message(text, entities, added_by):
    """For every custom_emoji entity in a raw message that ISN'T already
    saved, auto-derive a name (word next to it) and save it. Silent --
    just populates the DB/cache so stylize() can pick it up automatically
    everywhere from now on. Returns the list of newly-saved names."""
    custom_ents = [e for e in (entities or []) if e.type == MessageEntity.CUSTOM_EMOJI]
    if not custom_ents:
        return []
    idx_map = _utf16_to_str_index_map(text)
    newly_saved = []
    for e in custom_ents:
        if get_custom_emoji_by_id(e.custom_emoji_id):
            continue
        str_start = idx_map[e.offset]
        str_end = idx_map[e.offset + e.length]
        glyph = text[str_start:str_end]
        before = text[:str_start].strip()
        after = text[str_end:].strip()
        raw_name = before.split()[-1] if before else (after.split()[0] if after else "")
        name = re.sub(r"[^\w\u0900-\u097F]", "", raw_name).lower()
        if not name or name_taken_by_other(name, e.custom_emoji_id):
            name = f"emj{count_custom_emojis() + 1}"
        save_custom_emoji(e.custom_emoji_id, glyph, name, added_by)
        newly_saved.append(name)
    return newly_saved


class ResolvedUser:
    """Lightweight stand-in for a Telegram User object -- has the same
    .id/.first_name/.username attributes the rest of the code expects from
    target.*, so it's a drop-in wherever msg.reply_to_message.from_user is used."""
    def __init__(self, user_id, first_name, username):
        self.id = user_id
        self.first_name = first_name or "User"
        self.username = username


# =============================================================================
# USERNAME CACHE -- simple in-memory dict, no database.
# Every normal group message silently updates this: username.lower() -> (id, name).
# This lets admins target ANYONE by typing "@username" directly, without
# needing to reply to their message and without any DM/"/start" requirement.
# =============================================================================
username_cache = {}  # {"lower_username": (user_id, first_name)}


def cache_username(user_id, username, first_name):
    """Called silently on every group message to keep the username cache fresh."""
    if username:
        username_cache[username.lower()] = (user_id, first_name)


async def find_user_by_username(username: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Resolve '@username' -> target user with a 4-step fallback chain, so a
    target resolves even if they've never messaged since the bot last
    restarted and even if they're not in the in-memory cache:

      1. Group admins (direct, fresh Telegram API call) -- always accurate,
         works even for admins who never sent a text message.
      2. SQLite `users` table -- persists across restarts (Railway wipes
         in-memory state on every redeploy, this doesn't).
      3. In-memory username_cache -- fastest path, populated by every
         group message.
      4. Telegram `get_chat("@username")` -- last resort, for people who
         aren't currently cached/DB'd at all.
    """
    uname = username.lstrip("@").lower()

    # ---- Step 1: group admins direct fetch ----
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for member in admins:
            u = member.user
            if u.username and u.username.lower() == uname:
                return ResolvedUser(u.id, u.first_name, u.username)
    except TelegramError as e:
        logger.warning("get_chat_administrators failed while resolving @%s: %s", uname, e)

    # ---- Step 2: persistent SQLite lookup ----
    try:
        conn = db_connect()
        row = conn.execute(
            "SELECT user_id, first_name, username FROM users WHERE LOWER(username) = LOWER(?)",
            (uname,),
        ).fetchone()
        conn.close()
        if row:
            return ResolvedUser(row["user_id"], row["first_name"], row["username"])
    except sqlite3.Error as e:
        logger.warning("DB lookup failed while resolving @%s: %s", uname, e)

    # ---- Step 3: in-memory cache ----
    entry = username_cache.get(uname)
    if entry:
        return ResolvedUser(entry[0], entry[1], username.lstrip("@"))

    # ---- Step 4: Telegram API fallback ----
    try:
        chat_obj = await context.bot.get_chat(f"@{uname}")
        return ResolvedUser(chat_obj.id, chat_obj.first_name, chat_obj.username)
    except TelegramError as e:
        logger.warning("get_chat fallback failed while resolving @%s: %s", uname, e)

    return None



# =============================================================================
# GROK (xAI) AI LAYER -- multi-key rotation + fallback
# =============================================================================
_grok_key_index = 0


def _grok_call_raw(messages, json_mode=True, temperature=0.2, max_tokens=400):
    """Try every configured Grok key in rotation until one works."""
    global _grok_key_index
    if not GROK_API_KEYS:
        logger.error("No GROK_API_KEYS configured!")
        return None

    n = len(GROK_API_KEYS)
    last_error = None
    for attempt in range(n):
        key = GROK_API_KEYS[(_grok_key_index + attempt) % n]
        try:
            payload = {
                "model": GROK_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            resp = requests.post(
                GROK_BASE_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=12,  # lower timeout so a slow/dead key rotates faster instead of stalling
            )
            if resp.status_code == 200:
                _grok_key_index = (_grok_key_index + attempt) % n  # remember last-good key
                content = resp.json()["choices"][0]["message"]["content"]
                return content
            elif resp.status_code in (429, 401, 403, 500, 502, 503):
                last_error = f"HTTP {resp.status_code} on key #{attempt+1}"
                logger.warning("Grok key failed (%s), rotating...", last_error)
                continue
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
        except requests.RequestException as e:
            last_error = str(e)
            logger.warning("Grok request error, rotating key: %s", e)
            continue

    logger.error("All Grok API keys failed. Last error: %s", last_error)
    return None


async def ai_classify_admin_command(command_text: str, has_reply_target: bool, recent_context: str = "") -> dict:
    """
    Ask Grok to understand a natural-language admin command (Hindi/English/
    Hinglish, any phrasing, any tone) and turn it into a structured action.
    Given real conversational context + a brief internal reasoning step
    (much stronger than blind pattern-matching), so it should handle
    indirect, sarcastic, or context-dependent phrasing correctly too.
    Returns a dict like {"action": "mute", "duration_minutes": 60, "confidence": "high"}
    """
    system_prompt = (
        "Tum ek highly capable Telegram group-management AI ho, jise ek real human "
        "language-understanding model ki tarah sochna hai -- keyword-matching ya "
        "fixed-phrase-lookup NAHI karni. Ek group admin/owner ne tumhe ek instruction "
        "diya hai (Hindi/English/Hinglish, kisi bhi tarike se likha ho -- casual, "
        "sarcastic, indirect, ghumaake bola hua, gaali-galoch/slang me, ya seedha "
        "command jaisa bhi ho sakta hai). Tumhara kaam hai: poore sentence ka ASLI "
        "matlab aur intent samajhna, jaise ek samajhdaar insaan group ka context "
        "padhkar turant samajh jaata hai ki dusra insaan kya karne ko keh raha hai.\n\n"
        "Neeche 'RECENT GROUP CONTEXT' me group ki last kuch messages di gayi hain -- "
        "ISKO ZAROOR USE KARO agar current command apne aap me ambiguous lage (jaise "
        "sirf 'isko bhi' ya 'isko theek karo' -- aisi cases me upar ki baatcheet dekhkar "
        "samjho ki kis cheez ka zikar ho raha hai, jaise ek insaan conversation follow "
        "karke samajhta.\n\n"
        "Possible actions (in JSON 'action' field): "
        "ban, unban, kick, mute, unmute, warn, unwarn, promote, demote, pin, unpin, "
        "delete, purge, lock, unlock, upgrade_trust, downgrade_trust, dispute_freeze, "
        "dispute_unfreeze, escrow_verify, escrow_unverify, info, set_title, unknown.\n\n"
        "Yeh kuch ILLUSTRATIVE examples hain -- inhe literal template mat samjho, "
        "sirf yeh dikhane ke liye hain ki har action KITNE alag-alag, indirect, ya "
        "casual tarike se bola ja sakta hai. Real messages inse bahut different bhi "
        "ho sakte hain -- tumhe pattern nahi, MEANING samajhna hai:\n"
        "- kick: 'isko laat maaro', 'isko bhagao', 'isko group se nikal do', 'kick "
        "maar isko', 'isko rasta dikha do', ya koi bhi tarika jisme temporarily "
        "nikaalne ka intent ho.\n"
        "- ban: 'isko hamesha ke liye nikal do', 'iski entry band kar do', 'dobara na "
        "aaye isliye nikal do', ya koi bhi tarika jisme PERMANENT/hamesha ke liye "
        "nikaalne ka intent ho (ban vs kick ka farak: permanent vs temporary).\n"
        "- mute: 'isko chup kara do', 'iski bakwas band karo', 'kuch der ke liye "
        "isko bolne mat do', ya koi bhi 'chup karana' ka intent (bina nikaale).\n"
        "- warn: 'isko daant do', 'ek chance aur do warning ke sath', 'thoda daata "
        "do isko' -- soft correction ka intent, bina turant hataye.\n"
        "- info: 'iski jaankari do', 'yeh kaun hai batao', 'iske baare me batao', "
        "'kaun hai yeh banda' -- sirf jaankari maang rahe hain, koi action nahi.\n"
        "- promote/demote: admin banane/hatane ka intent.\n"
        "- pin/unpin: message ko upar chipkane/hatane ka intent.\n"
        "- delete: EK specific message hatane ka intent.\n\n"
        "Rules:\n"
        "- purge, lock, unlock, dispute_freeze, dispute_unfreeze -> OWNER ONLY actions "
        "(tum flag karo, backend check karega ki sender owner hai ya nahi).\n"
        "- 'delete' vs 'purge' me FARAK hai: EK specific message hatana = 'delete'. "
        "REPLY se lekar is command tak ke SAARE messages ek saath saaf karna (jaise "
        "'yahan tak sab clean kar do') = 'purge'.\n"
        "- 'set_title' matlab admin ke naam ke bagal wala chota tag/title (jaise "
        "'Admin', 'Manager') badalna. Naya title text 'title' field me EXACTLY wahi "
        "words nikaalo jo admin ne diye hain, bina kisi bhi tarah reformat/redesign/"
        "translate kiye -- jaisa likha hai bilkul waisa hi (case, spelling, sab same), "
        "max 16 characters.\n"
        "- Duration bola gaya ho (jaise '10 minute', '1 ghanta', '2 din') to minutes "
        "me convert karke 'duration_minutes' me do, warna null.\n"
        "- 'warn'/'unwarn' ke saath kitni baar/warnings ka zikar ho to 'count' field "
        "me number do ('saari/sabhi/all' = count:999). Default count:1.\n"
        "- 'upgrade_trust'/'downgrade_trust' ke saath kitne level badhane/ghataane "
        "hain wo 'count' me do ('max/maximum/top/full' = count:999). Default count:1.\n"
        "- action='unknown' SIRF tab do jab sach me kuch bhi samajh na aaye, poore "
        "context ke baad bhi. Meaning approx clear ho raha ho (chahe ajeeb/sarcastic/"
        "casual wording ho) to closest action do, confidence 'medium'/'low' de sakte "
        "ho par 'unknown' mat do.\n"
        f"- has_reply_target = {has_reply_target}.\n\n"
        "Pehle 'reasoning' field me 1-2 chhoti lines me socho ki command ka asli "
        "matlab kya hai (context ko dhyan me rakhkar), FIR 'action' decide karo -- yeh "
        "reasoning step tumhari accuracy zyada better banata hai, isliye skip mat karo.\n\n"
        'Respond ONLY with compact JSON: {"reasoning": "...", "action": "...", '
        '"duration_minutes": null, "title": null, "count": 1, "confidence": "high|medium|low"}'
    )
    user_content = command_text
    if recent_context:
        user_content = f"RECENT GROUP CONTEXT (last few messages, for reference only):\n{recent_context}\n\nCURRENT COMMAND TO CLASSIFY:\n{command_text}"
    raw = await asyncio.to_thread(
        _grok_call_raw,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        json_mode=True,
        temperature=0.15,
        max_tokens=500,
    )
    if raw is None:
        return {"action": "unknown", "duration_minutes": None, "confidence": "low", "error": "ai_unavailable"}
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("Could not parse AI response: %s", raw)
        return {"action": "unknown", "duration_minutes": None, "confidence": "low"}


async def ai_verify_abuse(message_text: str) -> dict:
    """A local keyword/regex pre-filter flagged this message as possibly
    abusive. Some words (e.g. 'redeem', normal Hindi/English words that just
    happen to contain a banned substring after obfuscation-tolerant matching)
    can false-positive. Ask AI to confirm before any punishment is applied."""
    system_prompt = (
        "Tum ek Telegram group ke liye gaali/abuse-detection AI ho. Neeche ek message hai jise "
        "ek local keyword filter ne 'possibly abusive' flag kiya hai (ho sakta hai false positive ho -- "
        "jaise 'redeem code de do' jaisa normal message kisi keyword se galti se match ho gaya ho).\n\n"
        "Decide karo: kya yeh message me GENUINELY kisi ko gaali/abuse/insult di gayi hai (Hindi/English/"
        "Hinglish, kisi bhi obfuscation ke saath -- dots, @, #, spacing se chhupaya gaya ho tab bhi), ya "
        "yeh ek normal harmless message hai jo sirf galti se match hua?\n\n"
        'Respond ONLY JSON: {"is_abuse": true/false}'
    )
    raw = await asyncio.to_thread(
        _grok_call_raw,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_text},
        ],
        json_mode=True,
        max_tokens=100,
    )
    if raw is None:
        # AI unavailable -> trust the local keyword match (original instant
        # behaviour), so protection isn't lost when the AI service is down.
        return {"is_abuse": True}
    try:
        return json.loads(raw)
    except Exception:
        return {"is_abuse": True}


async def ai_check_escrow_impersonation(message_text: str) -> dict:
    """Detect someone other than the owner offering themselves as 'escrow'."""
    system_prompt = (
        "Tum ek scam-detection AI ho. Neeche ek Telegram group message hai jisme 'escrow' "
        "shabd ya uska context aaya hai. Sirf owner (@" + OWNER_USERNAME + ") hi legit escrow "
        "provider hai is group me. Decide karo ki kya yeh message:\n"
        "(a) genuinely kisi OR person/username ko escrow provider ke roop me promote/refer kar "
        "raha hai (jo owner nahi hai) -- yeh scam attempt hai,\n"
        "(b) ya sirf normal baat-cheet hai escrow ke baare me (jaise 'escrow karwa lo' bina kisi "
        "specific fake username ke, ya khud owner ka naam le raha hai).\n\n"
        'Respond ONLY JSON: {"is_impersonation": true/false}'
    )
    raw = await asyncio.to_thread(
        _grok_call_raw,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_text},
        ],
        json_mode=True,
        max_tokens=100,
    )
    if raw is None:
        return {"is_impersonation": False}
    try:
        return json.loads(raw)
    except Exception:
        return {"is_impersonation": False}


# =============================================================================
# "##" SELF-AWARE CHAT MODE (owner-only) -- bot can answer questions about
# its own features, and can answer precise data-questions about a user
# (warns, trust level, etc.) if the owner is replying to that user's message.
# =============================================================================
FEATURE_DOCS = """
YEH BOT (Telegram Group Manager) ke saare features:

ADMIN COMMANDS (koi bhi admin/owner, message ke aakhir me ".." lagakar,
Hindi/English/Hinglish kisi bhi tarike se bola ja sakta hai, kisi ke message
ko REPLY karke): ban, unban, kick, mute (duration ke saath), unmute, warn
(count ke saath, jaise "2 warning do"), unwarn (count ke saath, ya "saari
hata do"), promote, demote, pin, unpin, delete, info (user ki jaankari),
escrow_verify, escrow_unverify, set_title (admin ka custom tag/title badalna).

OWNER-ONLY commands (sirf owner, ".." ke saath): purge (reply se lekar
latest tak sab delete), lock (chat lock), unlock, upgrade_trust/
downgrade_trust (Trusted Trader level), dispute_freeze/dispute_unfreeze
(jhagde me dono users ko temporarily mute).

TRUST LEVELS: New Member -> Known Member -> Trusted Trader -> Verified
Trader. Sirf owner upgrade/downgrade kar sakta hai. /trusted command se
group me sabhi Trusted Traders ki list dikhti hai.

AUTOMATIC PROTECTION (kuch bolna nahi padta, khud chalta hai):
- Naye member ko photo + escrow disclaimer + channel buttons wala welcome
  message.
- Gaali dene par: message delete + 30 min mute + warning (fast local
  keyword-based check, AI nahi -- isliye instant hai).
- Link/username/promotion bhejne par: agar kisi admin/owner ne pehle nahi
  maanga tha to message delete + warning (AI context dekh kar decide karta
  hai, sirf keyword se nahi).
- Escrow impersonation guard: koi khud ko escrow provider bataye (owner ke
  alawa) to turant block.
- Antiflood: 10 second me 5+ messages bhejne par 5 min mute.
- Duplicate message spam: same message baar baar bhejne par delete +
  "Ruko zara, sabar karo!" reply.
- Forwarded messages: channel se aaya forward allowed hai, kisi USER ka
  forward turant delete hota hai.
- Edit-spam catch: message edit karke baad me link/promo daalne wale bhi
  pakde jaate hain.
- Anti-raid: 25-30+ members ek saath (20 second ke andar) join karein to
  uske baad aane wale sab members auto-remove hote hain jab tak raid rukta
  nahi.
- Admin/Owner impersonation detector: naya member agar naam/username/photo
  me owner se 50%+ match kare to group me tag karke warning aati hai.
- Ghost/deleted account cleanup: raat 1:30 baje automatic scan hota hai.
- Warn expiry: har warning 7 din baad khud expire ho jaati hai.
- Database backup: har 30 minute me poora database backup channel me
  bhejta hai. Admin panel me Export/Import Database buttons bhi hain.

ADMIN PANEL: Bot ko DM me /start bhejo (sirf owner). Wahan se welcome
channels manage kar sakte ho, database export/import kar sakte ho, aur
trusted traders dekh sakte ho.

CHAT MODE: Message ke aakhir me ".." lagane se admin-command mode chalta
hai. "##" lagane se yeh self-aware chat mode chalta hai (sirf owner ke
liye) -- bot ke features ke baare me sawal poochne ke liye, ya kisi user
ke message ko reply karke uske baare me specific sawal poochne ke liye
(jaise "iska kitna warn hua hai").
"""


async def ai_owner_chat(question: str, user_data_context: str = "") -> str:
    """Answers the owner's question about the bot itself (from FEATURE_DOCS)
    and/or about a specific user's data (if user_data_context is given,
    e.g. from a replied-to message). Always answers ONLY what was asked --
    no extra unrelated dump -- in a warm, human, conversational Hinglish way."""
    system_prompt = (
        "Tum ek friendly, human-jaisa assistant ho jo is Telegram group-manager bot "
        "ke andar chal rahe ho. Tumhe is bot ke saare features ki poori, accurate "
        "jaankari hai (neeche di gayi hai) -- tum sirf isi documentation ke aadhar par "
        "jawab doge, kabhi guess nahi karoge.\n\n"
        f"BOT DOCUMENTATION:\n{FEATURE_DOCS}\n\n"
        + (f"CURRENT USER DATA (agar sawal kisi specific user ke baare me hai to yeh "
           f"use karo):\n{user_data_context}\n\n" if user_data_context else "")
        + "BAHUT ZAROORI RULE: Owner ne jo bhi poocha hai, SIRF usi ka jawab do -- "
        "chhota, seedha, precise. Extra unrelated details, poora data-dump, ya "
        "unnecessary context kabhi mat do. Jaise agar sirf 'iska kitna warn hua hai' "
        "poocha hai to sirf warning count batao, uski poori profile info mat do. "
        "Tone friendly aur natural rakho, jaise ek insaan baat kar raha ho -- Hindi/ "
        "Hinglish me, jaisa sawal poocha gaya waisi hi bhasha me jawab do. "
        "ZAROORI: Kabhi bhi markdown formatting mat use karo -- no **, no _, no `, "
        "no # headers. Sirf plain simple text me jawab do, bina kisi symbol-based "
        "formatting ke, kyunki yeh seedha bina formatting ke bheja jaata hai."
    )
    raw = await asyncio.to_thread(
        _grok_call_raw,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        json_mode=False,
        temperature=0.4,
        max_tokens=300,
    )
    if raw is None:
        return "😕 Abhi AI se connect nahi ho paya, thodi der baad try karo."
    # Strip ALL markdown symbols outright (simple, bulletproof -- no regex
    # pairing needed) since this is sent with no parse_mode (plain text),
    # then apply the owner's custom small-caps font to the whole answer.
    clean = raw.strip()
    for sym in ("**", "__", "*", "_", "`", "#"):
        clean = clean.replace(sym, "")
    clean = clean.strip()
    if not clean:
        # The AI occasionally returns an empty/whitespace-only answer (e.g.
        # a reasoning model that used its whole token budget on internal
        # reasoning and had nothing left for the actual reply). Sending an
        # empty string to Telegram raises "Message text is empty" (a
        # permanent 400, not something that benefits from retrying) --
        # returning a real fallback line here avoids that entirely.
        return "😕 Iska clear jawab nahi mila, dobara try karo ya sawal thoda alag tarike se poochho."
    return fancy(clean)


# =============================================================================
# PROFILE-PICTURE PERCEPTUAL HASH (free, no extra API needed)
# =============================================================================
try:
    import imagehash
    from PIL import Image
    _PHASH_AVAILABLE = True
except ImportError:
    _PHASH_AVAILABLE = False
    logger.warning("imagehash/Pillow not installed -- photo comparison disabled.")


def phash_from_bytes(image_bytes: bytes):
    if not _PHASH_AVAILABLE:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        return imagehash.phash(img)
    except Exception as e:
        logger.warning("phash failed: %s", e)
        return None


def phash_similarity_percent(hash1, hash2) -> int:
    """0-100% similarity from two ImageHash objects (lower hamming distance = more similar)."""
    if hash1 is None or hash2 is None:
        return 0
    max_bits = len(hash1.hash) ** 2  # 64 for default 8x8 phash
    distance = hash1 - hash2
    similarity = max(0, 100 - int((distance / max_bits) * 100 * 4))  # scaled for sensitivity
    return min(100, similarity)


def text_similarity_percent(a: str, b: str) -> int:
    """Simple normalized similarity between two short strings (name/username/bio)."""
    if not a or not b:
        return 0
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return 100
    # simple ratio via SequenceMatcher (stdlib, free)
    from difflib import SequenceMatcher
    return int(SequenceMatcher(None, a, b).ratio() * 100)


# =============================================================================
# ABUSE / GAALI DETECTION -- fast local keyword list (NOT AI, needs to be instant)
# Includes common Hindi/English/Hinglish slurs and obfuscated variants
# (dots, @ , #, spacing used to dodge filters). Kept in a separate constant
# so you can extend it easily without touching bot logic.
# =============================================================================
ABUSE_WORDS_RAW = [
    "mc", "bc", "bhenchod", "behenchod", "madarchod", "madrchod", "chutiya", "chutiye",
    "gandu", "gaandu", "randi", "raand", "harami", "haramzada", "kutta", "kamina",
    "lund", "lauda", "loda", "chut", "gaand", "bhosdi", "bhosdike", "bhosda",
    "saala kutta", "teri maa", "teri behen", "rand", "chodu", "fuck", "fucker",
    "motherfucker", "bastard", "bitch", "asshole", "slut", "whore", "dick", "pussy",
    "cunt",
]


def _build_abuse_regex():
    patterns = []
    for word in ABUSE_WORDS_RAW:
        # allow obfuscation: letters separated by ., @, #, _, -, spaces
        escaped_chars = [re.escape(c) for c in word.replace(" ", "")]
        spacer = r"[\.\@\#\_\-\s\*]{0,2}"
        pattern = spacer.join(escaped_chars)
        patterns.append(pattern)
    combined = r"(" + "|".join(patterns) + r")"
    return re.compile(combined, re.IGNORECASE)


ABUSE_REGEX = _build_abuse_regex()


def contains_abuse(text: str) -> bool:
    if not text:
        return False
    return bool(ABUSE_REGEX.search(text))


# =============================================================================
# LINK DETECTION (cheap local pre-filter, deterministic -- no AI needed).
# Matches: http(s)://..., t.me/..., www.something, bare "word.word"-style
# domains (e.g. "amazon.com"), and spelled-out "word dot com" tricks.
# NOTE: @username matching was intentionally REMOVED on the owner's request
# -- normal @tagging between members should never be touched by this filter.
# =============================================================================
LINK_PATTERN = re.compile(
    r"(https?://\S+)"                      # http/https links
    r"|(\bt\.me/\S+)"                       # telegram links
    r"|(www\.\S+)"                          # www.something
    r"|(\bhttps?\b)"                        # bare word "http"/"https" typed without ://
    r"|(\b[a-zA-Z0-9][a-zA-Z0-9\-]{1,30}\.[a-zA-Z]{2,10}(?:/\S*)?\b)"   # bare dot-domains like amazon.com, insta.gram/xyz
    r"|(\b[a-zA-Z0-9]{2,30}\s*(?:dot|\[dot\]|\(dot\))\s*(?:com|in|net|org|io|me|xyz|co|gg|app|link|shop|site|online)\b)",  # "amazon dot com"
    re.IGNORECASE,
)


def has_midword_dot_obfuscation(text: str) -> bool:
    """Detects the 'word.word' spacing trick used to dodge filters, e.g.
    'amazon.com' typed as a single token is already caught by LINK_PATTERN,
    but this also catches a dot used *instead of a space* between two
    normal words, e.g. 'yeh.dekho' or 'bhai.check.karo'. A trailing '..'
    (used for admin natural-language commands) is explicitly excluded, and
    so is any single '.' that isn't sitting directly between two word
    characters (so normal punctuation like 'ok. thik hai' -- dot followed
    by a space -- is NOT flagged)."""
    if not text:
        return False
    stripped = text.strip()
    if stripped.endswith(".."):
        return False  # admin command syntax, not obfuscation
    # a dot with a word character immediately on both sides, and NOT part
    # of a "..", counts as suspicious mid-word obfuscation.
    for m in re.finditer(r"(?<!\.)\.(?!\.)", text):
        i = m.start()
        before = text[i - 1] if i > 0 else ""
        after = text[i + 1] if i + 1 < len(text) else ""
        if before.isalnum() and after.isalnum() and not after.isdigit():
            return True
    return False


def message_has_link_pattern(text: str) -> bool:
    if not text:
        return False
    return bool(LINK_PATTERN.search(text)) or has_midword_dot_obfuscation(text)


def extract_owner_username_mentions(text: str):
    return re.findall(r"@([A-Za-z0-9_]{4,})", text or "")


# =============================================================================
# IN-MEMORY RUNTIME STATE (per-process, resets on restart -- fine, it's all
# short-lived flood/rate tracking, not permanent data)
# =============================================================================
_msg_timestamps = defaultdict(lambda: deque())        # (chat_id,user_id) -> deque[float]
_last_message_text = {}                                # (chat_id,user_id) -> (text, ts)
_recent_chat_context = defaultdict(lambda: deque(maxlen=12))  # chat_id -> deque[str "Name: text"]
_join_timestamps = defaultdict(lambda: deque())        # chat_id -> deque[float]
_raid_active = defaultdict(bool)                        # chat_id -> bool
_raid_last_join = {}                                    # chat_id -> ts
_frozen_disputes = defaultdict(set)                     # chat_id -> set(user_id) currently frozen
_admin_cache = {}                                        # (chat_id,user_id) -> (is_admin, ts)
_known_group_seen = {}                                    # chat_id -> last upsert timestamp (throttle to once/hour)
ADMIN_CACHE_TTL = 60  # seconds

_deal_notice_last = {}   # chat_id -> last time the trusted-escrower notice was sent
DEAL_NOTICE_COOLDOWN_SECONDS = 600  # 10 minutes -- avoid spamming the same reminder repeatedly
DEAL_KEYWORDS_RE = re.compile(
    r"\b("
    r"buy|buying|buyer|sell|selling|seller|sale|sold|"
    r"deal|dealing|trade|trading|exchange|swap|"
    r"escrow|middleman|mediator|"
    r"kharid\w*|becha?\w*|bikri|len\s*den|lena\s*dena|"
    r"cod|advance\s*payment|payment\s*first|pehle\s*payment|paisa\s*pehle|"
    r"vendor|purchase|price\s*fix|rate\s*fix"
    r")\b",
    re.IGNORECASE,
)

ANTIFLOOD_WINDOW = 10       # seconds
ANTIFLOOD_MAX_MSGS = 5      # >=5 msgs in window => flood
ANTIFLOOD_MUTE_MIN = 5

DUPLICATE_WINDOW = 10       # seconds -- same text twice within this => spam

ABUSE_MUTE_MIN = 30
WARN_BAN_LIMIT = 5   # total warns (any reason) at which a user is auto-banned

RAID_JOIN_WINDOW = 20       # seconds
RAID_JOIN_THRESHOLD = 25    # >= this many joins in window => raid mode
RAID_COOLDOWN_GAP = 15      # seconds of no-joins => raid considered over


async def is_user_admin(bot, chat_id, user_id) -> bool:
    if user_id == OWNER_ID:
        return True
    key = (chat_id, user_id)
    cached = _admin_cache.get(key)
    now = time.time()
    if cached and (now - cached[1]) < ADMIN_CACHE_TTL:
        return cached[0]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except TelegramError:
        result = False
    _admin_cache[key] = (result, now)
    return result


def is_owner(user_id) -> bool:
    return user_id == OWNER_ID


def user_profile_link(user_id, username):
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


# =============================================================================
# WELCOME MESSAGE + ANTI-RAID + IMPERSONATION DETECTION (on new member join)
# =============================================================================
async def send_welcome_message(context: ContextTypes.DEFAULT_TYPE, chat, member):
    """Builds and sends the welcome message for one member. Shared by all
    three join-detection paths: normal new_chat_members, chat_join_request
    (large/public groups with 'Approve New Members' enabled), and
    chat_member status transitions (the most reliable path, works
    regardless of a group's 'Hide Members' privacy setting). Dedups so the
    same join never gets welcomed twice if more than one path fires."""
    key = (chat.id, member.id)
    now = time.time()
    last = _recently_welcomed.get(key)
    if last and (now - last) < 15:
        return
    _recently_welcomed[key] = now
    if len(_recently_welcomed) > 5000:  # cheap unbounded-growth guard
        cutoff = now - 60
        for k in [k for k, v in _recently_welcomed.items() if v < cutoff]:
            del _recently_welcomed[k]

    await asyncio.to_thread(upsert_user, member.id, member.username, member.first_name, chat.id)

    name = md_escape(member.first_name or "Member")
    profile_link = user_profile_link(member.id, member.username)
    username_html = f"<a href='https://t.me/{member.username}'>@{md_escape(member.username)}</a>" if member.username else "N/A"
    gsettings = await asyncio.to_thread(get_group_settings, chat.id)
    template = gsettings.get("welcome_text") or DEFAULT_WELCOME_TEMPLATE

    try:
        caption = template.format(
            name=name, group=md_escape(chat.title or "is group"), id=member.id,
            username=username_html,
            profile=f"<a href='{profile_link}'>Click Here</a>",
        )
    except (KeyError, IndexError, ValueError):
        # Malformed placeholder in the custom text -- fall back to default
        # rather than silently killing the whole welcome message.
        logger.warning("Malformed custom welcome_text for chat %s, using default.", chat.id)
        caption = DEFAULT_WELCOME_TEMPLATE.format(
            name=name, group=md_escape(chat.title or "is group"), id=member.id,
            username=username_html,
            profile=f"<a href='{profile_link}'>Click Here</a>",
        )

    buttons = []
    if gsettings.get("channel_username"):
        buttons.append([InlineKeyboardButton(f"{gsettings['channel_username']}", url=f"https://t.me/{gsettings['channel_username']}", style="success", icon_custom_emoji_id=CHANNEL_BUTTON_EMOJI_ID)])
    else:
        for ch_username in get_welcome_channels():
            buttons.append([InlineKeyboardButton(f"{ch_username}", url=f"https://t.me/{ch_username}", style="success", icon_custom_emoji_id=CHANNEL_BUTTON_EMOJI_ID)])

    if gsettings.get("button_text") and gsettings.get("button_url"):
        buttons.append([InlineKeyboardButton(fancy(gsettings["button_text"]), url=gsettings["button_url"], style="primary", icon_custom_emoji_id=CONTACT_OWNER_BUTTON_EMOJI_ID)])
    else:
        buttons.append([InlineKeyboardButton(fancy("Escrow: Contact Owner"), url=f"https://t.me/{OWNER_USERNAME}", style="primary", icon_custom_emoji_id=CONTACT_OWNER_BUTTON_EMOJI_ID)])
    markup = InlineKeyboardMarkup(buttons)

    # Profile picture ALWAYS attaches (if the member has one) regardless
    # of any welcome-text customization -- these are independent.
    photo_bytes = None
    try:
        photos = await context.bot.get_user_profile_photos(member.id, limit=1)
        if photos.total_count > 0:
            file = await context.bot.get_file(photos.photos[0][-1].file_id)
            photo_bytes = await file.download_as_bytearray()
    except TelegramError:
        pass

    final_text, final_entities = render_with_emojis(caption)
    try:
        if photo_bytes:
            await context.bot.send_photo(
                chat.id, photo=bytes(photo_bytes), caption=final_text, caption_entities=final_entities,
                reply_markup=markup,
            )
        else:
            await context.bot.send_message(
                chat.id, final_text, entities=final_entities,
                reply_markup=markup, disable_web_page_preview=True,
            )
    except TelegramError as e:
        logger.warning("Welcome message failed: %s", e)

    # ---------------- IMPERSONATION CHECK (name/username/bio/photo vs owner) ----------------
    asyncio.create_task(check_impersonation(context, chat.id, member, photo_bytes))
    return photo_bytes


_recently_welcomed = {}   # (chat_id, user_id) -> timestamp, dedup window


async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redundant join-detection path via chat_member status transitions --
    this is what actually makes welcome messages reliable regardless of a
    group's privacy settings (e.g. 'Hide Members'), since it doesn't depend
    on a visible join service message being generated at all. Dedups
    against handle_new_members/handle_join_request in case more than one
    update type fires for the same join."""
    cmu = update.chat_member
    if cmu is None:
        return
    chat = cmu.chat
    if not is_group_approved(chat.id):
        return

    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    member = cmu.new_chat_member.user
    if member.is_bot:
        return

    was_member = old_status in ("member", "administrator", "creator") or (old_status == "restricted" and cmu.old_chat_member.is_member)
    is_member_now = new_status in ("member", "administrator", "creator") or (new_status == "restricted" and cmu.new_chat_member.is_member)
    if was_member or not is_member_now:
        return  # not a fresh join (could be a promotion, unban, restriction change, etc.)

    await send_welcome_message(context, chat, member)


async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Large/public groups often have 'Approve New Members' (join-request
    approval) turned on. When that's ON, joins do NOT fire a normal
    new_chat_members event at all -- Telegram sends this separate
    chat_join_request update instead, and the user isn't actually a member
    until approved. Without this handler the welcome message would simply
    never fire for such groups (which is exactly what auto-added members
    bypass, since a direct admin-add skips the request queue entirely)."""
    req = update.chat_join_request
    chat = req.chat
    member = req.from_user
    if member.is_bot:
        return
    if not is_group_approved(chat.id):
        return
    try:
        await context.bot.approve_chat_join_request(chat.id, member.id)
    except TelegramError as e:
        logger.warning("Could not approve join request for %s in %s: %s", member.id, chat.id, e)
        return
    await send_welcome_message(context, chat, member)


async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_group_approved(chat.id):
        return
    now = time.time()

    for member in update.message.new_chat_members:
        if member.is_bot and member.id == context.bot.id:
            continue  # bot itself joining

        # ---------------- ANTI-RAID TRACKING ----------------
        dq = _join_timestamps[chat.id]
        dq.append(now)
        while dq and now - dq[0] > RAID_JOIN_WINDOW:
            dq.popleft()

        raid_now = len(dq) >= RAID_JOIN_THRESHOLD
        if raid_now and not _raid_active[chat.id]:
            _raid_active[chat.id] = True
            logger.warning("RAID MODE ACTIVATED in chat %s", chat.id)

        _raid_last_join[chat.id] = now

        if _raid_active[chat.id]:
            # If this join happened AFTER raid was already declared, treat as
            # part of the flood -> remove it. (Note: Telegram's User object
            # has no `photo_count` field -- that was never a valid attribute
            # here -- so the heuristic is simply "no username set", which is
            # the only signal actually available on the User object.)
            looks_fake = not member.username
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
                await context.bot.unban_chat_member(chat.id, member.id)  # kick not permaban
            except TelegramError as e:
                logger.warning("Could not remove raid-join %s: %s", member.id, e)
            continue  # skip welcome message for raid joins

        # ---------------- NORMAL WELCOME ----------------
        await send_welcome_message(context, chat, member)

    # If raid was active but no new joins are coming anymore, we let the
    # scheduled watcher (raid_watchdog job) declare it over and post the summary.


async def check_impersonation(context: ContextTypes.DEFAULT_TYPE, chat_id, member, photo_bytes):
    try:
        owner_chat = await context.bot.get_chat(OWNER_ID)
    except TelegramError:
        return

    name_sim = text_similarity_percent(member.first_name or "", owner_chat.first_name or "")
    uname_sim = text_similarity_percent(member.username or "", owner_chat.username or "")
    bio_sim = 0
    try:
        owner_bio = owner_chat.bio or ""
        member_full = await context.bot.get_chat(member.id)
        bio_sim = text_similarity_percent(member_full.bio or "", owner_bio)
    except TelegramError:
        pass

    photo_sim = 0
    if photo_bytes and _PHASH_AVAILABLE:
        try:
            owner_photos = await context.bot.get_user_profile_photos(OWNER_ID, limit=1)
            if owner_photos.total_count > 0:
                owner_file = await context.bot.get_file(owner_photos.photos[0][-1].file_id)
                owner_bytes = await owner_file.download_as_bytearray()
                h1 = phash_from_bytes(bytes(photo_bytes))
                h2 = phash_from_bytes(bytes(owner_bytes))
                photo_sim = phash_similarity_percent(h1, h2)
        except TelegramError:
            pass

    overall = max(name_sim, uname_sim, bio_sim, photo_sim)

    if overall >= 50:
        conn = db_connect()
        conn.execute(
            "INSERT OR REPLACE INTO impersonators (user_id, chat_id, match_percent, flagged_at) VALUES (?,?,?,?)",
            (member.id, chat_id, overall, datetime.now(IST).isoformat()),
        )
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(
                chat_id,
                stylize(f"⚠️ <a href='tg://user?id={member.id}'>{md_escape(member.first_name)}</a> <b>ka profile owner se "
                f"{overall}% match ho raha hai!</b>\n"
                f"🔴 <b>Kripya apna naam/username/photo change karein, warna action liya ja sakta hai.</b>"),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass


async def recheck_impersonators(context: ContextTypes.DEFAULT_TYPE):
    """Runs periodically: re-check flagged users after a delay, unflag if resolved."""
    conn = db_connect()
    rows = conn.execute(
        "SELECT user_id, chat_id, flagged_at FROM impersonators"
    ).fetchall()
    conn.close()

    now = datetime.now(IST)
    for row in rows:
        flagged_at = datetime.fromisoformat(row["flagged_at"])
        if (now - flagged_at) < timedelta(hours=2):
            continue
        try:
            owner_chat = await context.bot.get_chat(OWNER_ID)
            member_chat = await context.bot.get_chat(row["user_id"])
        except TelegramError:
            continue
        name_sim = text_similarity_percent(member_chat.first_name or "", owner_chat.first_name or "")
        uname_sim = text_similarity_percent(member_chat.username or "", owner_chat.username or "")
        overall = max(name_sim, uname_sim)
        if overall < 50:
            conn = db_connect()
            conn.execute("DELETE FROM impersonators WHERE user_id=? AND chat_id=?", (row["user_id"], row["chat_id"]))
            conn.commit()
            conn.close()


async def raid_watchdog(context: ContextTypes.DEFAULT_TYPE):
    """Runs every ~10s: declares raid over once joins stop, posts summary."""
    now = time.time()
    for chat_id, active in list(_raid_active.items()):
        if not active:
            continue
        last = _raid_last_join.get(chat_id, 0)
        if now - last > RAID_COOLDOWN_GAP:
            _raid_active[chat_id] = False
            _join_timestamps[chat_id].clear()
            try:
                await context.bot.send_message(
                    chat_id,
                    stylize("🛡️ <b>Fake members detected & removed.</b>\n"
                    f"Agar koi real member galti se remove ho gaya ho, to owner "
                    f"(@{OWNER_USERNAME}) se contact karein. 🙏"),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass


# =============================================================================
# CORE GROUP MESSAGE HANDLER
# =============================================================================
async def send_filter_reply(context, chat_id, matched_filter, reply_to_message_id):
    try:
        ftype = matched_filter["file_type"]
        if ftype == "photo":
            await context.bot.send_photo(chat_id, matched_filter["file_id"], caption=matched_filter["reply_text"] or None, reply_to_message_id=reply_to_message_id)
        elif ftype == "sticker":
            await context.bot.send_sticker(chat_id, matched_filter["file_id"], reply_to_message_id=reply_to_message_id)
        elif ftype == "animation":
            await context.bot.send_animation(chat_id, matched_filter["file_id"], caption=matched_filter["reply_text"] or None, reply_to_message_id=reply_to_message_id)
        elif ftype == "video":
            await context.bot.send_video(chat_id, matched_filter["file_id"], caption=matched_filter["reply_text"] or None, reply_to_message_id=reply_to_message_id)
        elif ftype == "document":
            await context.bot.send_document(chat_id, matched_filter["file_id"], caption=matched_filter["reply_text"] or None, reply_to_message_id=reply_to_message_id)
        elif matched_filter["reply_text"]:
            final_text, final_entities = render_with_emojis(matched_filter["reply_text"])
            await context.bot.send_message(chat_id, final_text, entities=final_entities, reply_to_message_id=reply_to_message_id)
    except TelegramError:
        pass


async def handle_unknown_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The main group-message handler excludes ALL commands (filters.COMMAND),
    so a command-style filter trigger like '/like' would never be checked
    there. This catches any command NOT already claimed by one of the bot's
    own registered commands (start/info/trusted/etc.) and checks it against
    the filters table."""
    msg = update.effective_message
    if msg is None or msg.from_user is None or msg.from_user.is_bot or msg.sender_chat is not None:
        return
    chat = update.effective_chat
    text = msg.text or msg.caption or ""
    matched_filter = await asyncio.to_thread(find_matching_filter, chat.id, text)
    if matched_filter:
        await send_filter_reply(context, chat.id, matched_filter, msg.message_id)


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    now = time.time()

    # Always track known groups (cheap, throttled) -- needed so the owner
    # can discover a brand-new group's ID (via "group id" below, or the
    # panel's "My Groups" picker) EVEN before approving it.
    if chat.id not in _known_group_seen or (now - _known_group_seen[chat.id]) > 3600:
        _known_group_seen[chat.id] = now
        await asyncio.to_thread(upsert_known_group, chat.id, chat.title or str(chat.id))

    # ---------------------------------------------------------------
    # DETERMINISTIC "group id" QUERY -- no AI involved (an AI path here
    #      previously confused an anonymous-admin's pseudo-account ID with
    #      the actual group's chat ID). Works even for anonymous-admin
    #      messages (only an actual admin CAN post as the group), and
    #      works BEFORE approval too, since the owner needs this ID to
    #      approve the group in the first place.
    # ---------------------------------------------------------------
    _gid_probe = (msg.text or msg.caption or "").strip().lower()
    if re.search(r"\b(group|chat)\s*id\b", _gid_probe) and len(_gid_probe.split()) <= 6:
        allowed = msg.sender_chat is not None
        if not allowed and msg.from_user is not None and not msg.from_user.is_bot:
            allowed = await is_user_admin(context.bot, chat.id, msg.from_user.id)
        if allowed:
            try:
                await msg.reply_text(stylize(f"🆔 <b>Group ID:</b> <code>{chat.id}</code>"), parse_mode=ParseMode.HTML)
            except TelegramError:
                pass
            return

    # ---------------------------------------------------------------
    # GROUP APPROVAL GATE -- the bot does NOTHING in a group (no
    #      moderation, no welcome, nothing) until the owner has approved
    #      it (see /approve, /revoke). Stays silent for ordinary chat;
    #      only replies when someone clearly tries an admin command (a
    #      ".."-suffixed message), so revoking doesn't leave the bot
    #      spamming a group it's no longer supposed to be active in.
    # ---------------------------------------------------------------
    if not is_group_approved(chat.id):
        raw_text = msg.text or msg.caption or ""
        if raw_text.strip().endswith(".."):
            try:
                await msg.reply_text(
                    stylize(f"🚫 <b>Yeh group approved nahi hai.</b>\nApproval ke liye owner se contact karo: @{OWNER_USERNAME}"),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
        return

    # ---------------------------------------------------------------
    # -1. CHANNEL POSTS / ANONYMOUS-ADMIN MESSAGES -- fully exempt.
    #     Anything auto-forwarded from a channel linked to this group
    #     (e.g. the owner posting in their own channel, which then shows
    #     up in the group), or anything sent "as the group/channel" by an
    #     anonymous admin, has sender_chat set instead of a normal user.
    #     These must NEVER be run through moderation (abuse/link/flood
    #     filters) -- that was previously causing the bot's own channel
    #     posts (e.g. redeem-code announcements) to get deleted + warned.
    # ---------------------------------------------------------------
    if msg.sender_chat is not None:
        return

    if msg.from_user is None:
        return

    user = msg.from_user
    text = msg.text or msg.caption or ""

    if user.is_bot:
        return

    # These two run on EVERY single group message, so they're pushed to a
    # worker thread (asyncio.to_thread) instead of blocking the event loop
    # with a synchronous sqlite3 call -- otherwise, on a busy group, a burst
    # of messages could queue up behind these DB round-trips even though
    # concurrent_updates(True) is set (that setting only helps with handlers
    # running concurrently, it doesn't make a blocking call inside one of
    # them non-blocking).
    await asyncio.to_thread(upsert_user, user.id, user.username, user.first_name, chat.id)

    key = (chat.id, user.id)
    now = time.time()

    # Admins/owner are exempt from every auto-moderation filter below
    # (forwarded-message check, antiflood, duplicate-flood, abuse filter,
    # link/promo guard). Blacklist + dispute-freeze enforcement still apply
    # to everyone, including admins, since those are explicit owner actions
    # against a specific person, not general spam heuristics.
    admin_ok = await is_user_admin(context.bot, chat.id, user.id)

    # ---------------------------------------------------------------
    # 0. BLACKLIST ENFORCEMENT (instant ban if a blacklisted user is present)
    # ---------------------------------------------------------------
    if await asyncio.to_thread(is_blacklisted, user.id):
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            await asyncio.to_thread(record_ban, user.id, chat.id, "blacklisted")
            await msg.delete()
        except TelegramError:
            pass
        return

    # ---------------------------------------------------------------
    # 0.5 DISPUTE FREEZE ENFORCEMENT -- frozen users can't type
    # ---------------------------------------------------------------
    if user.id in _frozen_disputes[chat.id]:
        try:
            await msg.delete()
        except TelegramError:
            pass
        return

    # ---------------------------------------------------------------
    # 0.6 FILTER SET / REMOVE (admin only) -- e.g. admin replies to the
    #     message they want auto-sent with "isko filter karo (hi)", or
    #     removes one with "filter hata do (hi)". Deterministic regex,
    #     no AI involved, so it's instant and never misfires.
    #     SECURITY: re-checks admin status FRESH (bypassing the 60s cache)
    #     before allowing this, since it's a rare, sensitive action and
    #     must never depend on a possibly-stale cached result.
    # ---------------------------------------------------------------
    filter_match = re.search(r"filter\s*(?:kar\w*|set\s*kar\w*|hata\w*|remove\w*|delet\w*)?\s*\(([^)]+)\)\s*$", text, re.IGNORECASE)
    if filter_match:
        is_really_admin = user.id == OWNER_ID
        if not is_really_admin:
            try:
                fresh_member = await context.bot.get_chat_member(chat.id, user.id)
                is_really_admin = fresh_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
            except TelegramError:
                is_really_admin = False
        if not is_really_admin:
            return  # not an admin -- silently ignore, don't even acknowledge the attempt
        trigger = filter_match.group(1).strip()
        is_remove = bool(re.search(r"hata|remove|delet|nikal", text, re.IGNORECASE))
        if trigger:
            if is_remove:
                deleted = await asyncio.to_thread(remove_filter, chat.id, trigger)
                await msg.reply_text(
                    stylize(f"✅ <b>Filter '<code>{md_escape(trigger)}</code>' hata diya gaya.</b>" if deleted
                            else f"ℹ️ <b>Aisa koi filter mila hi nahi.</b>"),
                    parse_mode=ParseMode.HTML,
                )
            elif msg.reply_to_message:
                rmsg = msg.reply_to_message
                reply_text_val = rmsg.text or rmsg.caption or ""
                if reply_text_val:
                    await asyncio.to_thread(auto_save_new_emojis_from_message, reply_text_val, rmsg.entities or rmsg.caption_entities, user.id)
                file_id, file_type = None, None
                if rmsg.photo:
                    file_id, file_type = rmsg.photo[-1].file_id, "photo"
                elif rmsg.sticker:
                    file_id, file_type = rmsg.sticker.file_id, "sticker"
                elif rmsg.animation:
                    file_id, file_type = rmsg.animation.file_id, "animation"
                elif rmsg.video:
                    file_id, file_type = rmsg.video.file_id, "video"
                elif rmsg.document:
                    file_id, file_type = rmsg.document.file_id, "document"
                await asyncio.to_thread(add_filter, chat.id, trigger, reply_text_val, file_id, file_type, user.id)
                await msg.reply_text(
                    stylize(f"✅ <b>Filter set ho gaya!</b> Ab jab bhi koi '<code>{md_escape(trigger)}</code>' bhejega, "
                    f"yeh message automatic reply hoga."),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await msg.reply_text(
                    stylize("↩️ <b>Jo message auto-reply banana hai, usko reply karke likho:</b>\n<code>filter karo (trigger)</code>"),
                    parse_mode=ParseMode.HTML,
                )
            return

    # ---------------------------------------------------------------
    # 0.7 FILTER AUTO-REPLY (everyone) -- if the message matches a
    #     stored filter trigger, send the saved reply instantly.
    # ---------------------------------------------------------------
    matched_filter = await asyncio.to_thread(find_matching_filter, chat.id, text)
    if matched_filter:
        await send_filter_reply(context, chat.id, matched_filter, msg.message_id)
        return

    # keep a light rolling context of chat for admin natural-language commands
    _recent_chat_context[chat.id].append(f"{user.first_name} (id:{user.id}): {text}")

    # ---------------------------------------------------------------
    # 0.8 DEAL / BUY-SELL KEYWORD DETECTION -- point people to the trusted
    #     escrowers list automatically, so nobody deals off-platform without
    #     a safety net. Cooldown per chat so it doesn't spam every message.
    # ---------------------------------------------------------------
    if not admin_ok and DEAL_KEYWORDS_RE.search(text):
        last_notice = _deal_notice_last.get(chat.id, 0)
        if (now - last_notice) > DEAL_NOTICE_COOLDOWN_SECONDS:
            _deal_notice_last[chat.id] = now
            trusted_rows = await asyncio.to_thread(get_all_trusted, chat.id)
            if trusted_rows:
                lines = ["💎 <b>Deal/escrow ki baat ho rahi hai?</b>\n", "Sirf inhi trusted escrowers se deal karo:\n"]
                for r in trusted_rows:
                    uname = f"@{md_escape(r['username'])}" if r["username"] else f"<a href='tg://user?id={r['user_id']}'>{md_escape(r['first_name'])}</a>"
                    lines.append(f"• {TRUST_LEVELS.get(r['trust_level'], '')} {uname}")
                lines.append("\n🚫 <b>Inke alawa kisi aur se deal kiya to hamari koi guarantee nahi hogi.</b>")
                final_text, final_entities = render_with_emojis("\n".join(lines))
                try:
                    await context.bot.send_message(chat.id, final_text, entities=final_entities)
                except TelegramError:
                    pass

    # ---------------------------------------------------------------
    # 1. FORWARDED MESSAGE HANDLING
    #    - forwarded FROM A CHANNEL you admin -> always allowed
    #    - forwarded from a random USER -> delete (no warn), unless it also
    #      contains a link/username -> then warn via the same link-logic below
    # ---------------------------------------------------------------
    is_user_forward = bool(msg.forward_origin and getattr(msg.forward_origin, "sender_user", None))
    if not admin_ok and is_user_forward and not message_has_link_pattern(text):
        try:
            await msg.delete()
        except TelegramError:
            pass
        return  # deleted, no warn, no further checks needed

    # ---------------------------------------------------------------
    # 2. ANTIFLOOD (rate of messages)
    # ---------------------------------------------------------------
    dq = _msg_timestamps[key]
    dq.append(now)
    while dq and now - dq[0] > ANTIFLOOD_WINDOW:
        dq.popleft()
    if not admin_ok and len(dq) >= ANTIFLOOD_MAX_MSGS:
        await mute_user(context, chat.id, user.id, ANTIFLOOD_MUTE_MIN)
        dq.clear()
        try:
            await context.bot.send_message(
                chat.id,
                stylize(f"🚫 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a> <b>spam kar raha tha — "
                f"{ANTIFLOOD_MUTE_MIN} min ke liye mute kar diya gaya.</b> 🔇"),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    # ---------------------------------------------------------------
    # 3. DUPLICATE MESSAGE FLOOD
    # ---------------------------------------------------------------
    last = _last_message_text.get(key)
    if not admin_ok and last and last[0] == text and text.strip() and (now - last[1]) < DUPLICATE_WINDOW:
        try:
            await msg.delete()
            await context.bot.send_message(chat.id, stylize("🛑 <b>Ruko zara, sabar karo!</b> 😤"), parse_mode=ParseMode.HTML)
        except TelegramError:
            pass
        return
    _last_message_text[key] = (text, now)

    # ---------------------------------------------------------------
    # 4. ABUSE / GAALI DETECTION -- fast local keyword pre-filter, THEN
    #    an AI double-check before any punishment (avoids false positives
    #    like a normal word accidentally matching the obfuscation-tolerant
    #    keyword regex).
    # ---------------------------------------------------------------
    if not admin_ok and contains_abuse(text):
        verdict = await ai_verify_abuse(text)
        if verdict.get("is_abuse"):
            try:
                await msg.delete()
            except TelegramError:
                pass
            await mute_user(context, chat.id, user.id, ABUSE_MUTE_MIN)
            count, banned = await apply_warn_and_maybe_ban(context, chat.id, user.id, "Abusive language")
            try:
                if banned:
                    await context.bot.send_message(
                        chat.id,
                        stylize(f"🔨 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a> <b>ko "
                        f"{WARN_BAN_LIMIT} warnings ke baad ban kar diya gaya.</b>"),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await context.bot.send_message(
                        chat.id,
                        stylize(f"🤬 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a> <b>ne gaali di — "
                        f"{ABUSE_MUTE_MIN} min ke liye mute + ⚠️ Warning ({count}) diya gaya.</b>"),
                        parse_mode=ParseMode.HTML,
                    )
            except TelegramError:
                pass
            return

    # ---------------------------------------------------------------
    # 5. ESCROW IMPERSONATION GUARD
    # ---------------------------------------------------------------
    if "escrow" in text.lower():
        mentioned = extract_owner_username_mentions(text)
        fake_mention = [m for m in mentioned if m.lower() != OWNER_USERNAME.lower()]
        if fake_mention:
            result = await ai_check_escrow_impersonation(text)
            if result.get("is_impersonation"):
                try:
                    await msg.delete()
                except TelegramError:
                    pass
                verified_users = await asyncio.to_thread(get_escrow_verified_users, chat.id)
                user_lines = []
                for u in verified_users:
                    if u["username"]:
                        user_lines.append(f"• <a href='https://t.me/{u['username']}'>@{md_escape(u['username'])}</a>")
                    else:
                        user_lines.append(f"• <a href='tg://openmessage?user_id={u['user_id']}'>{md_escape(u['first_name'])}</a>")
                users_block = "\n".join(user_lines) if user_lines else "<i>Abhi koi escrow-verified user nahi hai.</i>"
                markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(fancy("Main / Trusted Escrower"), url=f"https://t.me/{OWNER_USERNAME}", style="primary", icon_custom_emoji_id=CONTACT_OWNER_BUTTON_EMOJI_ID)]]
                )
                await context.bot.send_message(
                    chat.id,
                    stylize(f"⚠️ <b>Kisi aur escrow worker ke paas mat jaayein.</b>\n\n"
                    f"✅ <b>Escrow-verified users:</b>\n{users_block}\n\n"
                    f"👇 <b>Ya seedha niche wale trusted escrower se contact karein:</b>"),
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

    # ---------------------------------------------------------------
    # 6. LINK / PROMOTION GUARD (local pattern match, instant -- no AI,
    #    so it can never silently fail-open like an AI call could)
    # ---------------------------------------------------------------
    if not admin_ok and message_has_link_pattern(text):
        try:
            await msg.delete()
        except TelegramError:
            pass
        count, banned = await apply_warn_and_maybe_ban(context, chat.id, user.id, "Unauthorized link/promotion")
        try:
            if banned:
                await context.bot.send_message(
                    chat.id,
                    stylize(f"🔨 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a> <b>ko "
                    f"{WARN_BAN_LIMIT} warnings ke baad ban kar diya gaya.</b>"),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await context.bot.send_message(
                    chat.id,
                    stylize(f"🚫 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a>, <b>link/promotion mat karo "
                    f"warna ban kar diye jaoge!</b> ⚠️ Warning ({count})"),
                    parse_mode=ParseMode.HTML,
                )
        except TelegramError:
            pass
        return

    # ---------------------------------------------------------------
    # 6.6 DIRECT "info" COMMAND -- admin/owner replies to any user (admin
    #     or normal member) with just "info" (no ".." needed, no AI --
    #     instant, deterministic DB lookup).
    # ---------------------------------------------------------------
    _info_words = text.strip().lower().rstrip(".!?").split()
    if admin_ok and msg.reply_to_message is not None and "info" in _info_words and len(_info_words) <= 4:
        t = msg.reply_to_message.from_user
        if t is not None and not t.is_bot:
            await asyncio.to_thread(upsert_user, t.id, t.username, t.first_name, chat.id)

            def _fetch_info_row():
                conn = db_connect()
                r = conn.execute("SELECT * FROM users WHERE user_id=?", (t.id,)).fetchone()
                conn.close()
                return r
            row = await asyncio.to_thread(_fetch_info_row)
            warns = await asyncio.to_thread(get_warn_count, t.id, chat.id)
            trust = row["trust_level"] if row else 0
            escrow = "✅ Yes" if (row and row["escrow_verified"]) else "❌ No"
            join_date = row["join_date"][:10] if row and row["join_date"] else "N/A"
            username_html = f"<a href='https://t.me/{t.username}'>@{md_escape(t.username)}</a>" if t.username else "N/A"
            info_text = (
                f"👤 <b>User Info</b>\n\n"
                f"<b>Name:</b> {md_escape(t.first_name)}\n"
                f"<b>Username:</b> {username_html}\n"
                f"<b>User ID:</b> <code>{t.id}</code>\n"
                f"<b>Warnings:</b> {warns}\n"
                f"<b>Trust Level:</b> {TRUST_LEVELS.get(trust)}\n"
                f"<b>Escrow Verified:</b> {escrow}\n"
                f"<b>Joined:</b> {join_date}"
            )
            final_text, final_entities = render_with_emojis(info_text)
            try:
                await msg.reply_text(final_text, entities=final_entities)
            except TelegramError:
                pass
            return

    # ---------------------------------------------------------------
    # 6.5 "##" SELF-AWARE CHAT MODE -- owner-only, bot explains its own
    #     features or answers precise questions about a user (if replying).
    # ---------------------------------------------------------------
    if text.strip().endswith("##"):
        if not is_owner(user.id):
            try:
                await context.bot.send_message(
                    chat.id,
                    stylize(f"🔒 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a>, "
                    f"<b>yeh sirf owner use kar sakta hai.</b>"),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
            return

        question = text.strip().rstrip("#").strip()
        user_data_context = ""
        if msg.reply_to_message:
            t = msg.reply_to_message.from_user
            conn = db_connect()
            row = conn.execute("SELECT * FROM users WHERE user_id=?", (t.id,)).fetchone()
            conn.close()
            warns = get_warn_count(t.id, chat.id)
            trust = row["trust_level"] if row else 0
            escrow = "Yes" if (row and row["escrow_verified"]) else "No"
            join_date = row["join_date"][:10] if row and row["join_date"] else "N/A"
            user_data_context = (
                f"Name: {t.first_name}, Username: @{t.username if t.username else 'N/A'}, "
                f"User ID: {t.id}, Warnings: {warns}, Trust Level: {TRUST_LEVELS.get(trust)}, "
                f"Escrow Verified: {escrow}, Joined: {join_date}"
            )

        answer = await ai_owner_chat(question, user_data_context)
        try:
            await msg.reply_text(stylize(answer))  # plain text -- AI's own answer, no HTML parse mode needed
        except TelegramError:
            pass
        return

    # ---------------------------------------------------------------
    # 7. ADMIN NATURAL-LANGUAGE COMMAND (".." at end)
    # ---------------------------------------------------------------
    if text.strip().endswith(".."):
        if not admin_ok:
            try:
                await context.bot.send_message(
                    chat.id,
                    stylize(f"🔒 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a>, <b>aap admin nahi ho.</b>"),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
            return

        command_text = text.strip().rstrip(".").strip()
        has_reply = msg.reply_to_message is not None
        recent_ctx = "\n".join(_recent_chat_context[chat.id])
        result = await ai_classify_admin_command(command_text, has_reply, recent_ctx)
        await execute_admin_action(context, update, result, user, command_text)
        return


async def handle_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit-spam catch: re-run the same checks on edited messages (people edit
    a clean message afterwards to sneak in a link/promo past the filters)."""
    msg = update.edited_message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    text = msg.text or msg.caption or ""
    chat = update.effective_chat
    user = msg.from_user

    if not is_group_approved(chat.id):
        return

    if await is_user_admin(context.bot, chat.id, user.id):
        return  # admins/owner are exempt from the edit-spam re-check too

    if msg.sender_chat is not None:
        return

    if message_has_link_pattern(text):
        try:
            await msg.delete()
        except TelegramError:
            pass
        count, banned = await apply_warn_and_maybe_ban(context, chat.id, user.id, "Edited message to insert link/promotion")
        try:
            if banned:
                await context.bot.send_message(
                    chat.id,
                    stylize(f"🔨 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a> <b>ko "
                    f"{WARN_BAN_LIMIT} warnings ke baad ban kar diya gaya.</b>"),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await context.bot.send_message(
                    chat.id,
                    stylize(f"🚫 <a href='tg://user?id={user.id}'>{md_escape(user.first_name)}</a>, <b>message edit karke "
                    f"promotion daala — warn ({count}) diya gaya!</b>"),
                    parse_mode=ParseMode.HTML,
                )
        except TelegramError:
            pass


# =============================================================================
# ADMIN ACTION EXECUTION
# =============================================================================
async def mute_user(context, chat_id, user_id, minutes):
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    try:
        await context.bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except TelegramError as e:
        logger.warning("mute failed: %s", e)


async def unmute_user(context, chat_id, user_id):
    try:
        await context.bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
            ),
        )
    except TelegramError as e:
        logger.warning("unmute failed: %s", e)


OWNER_ONLY_ACTIONS = {"purge", "lock", "unlock", "upgrade_trust", "downgrade_trust",
                       "dispute_freeze", "dispute_unfreeze"}


async def apply_warn_and_maybe_ban(context, chat_id, user_id, reason):
    """Adds a warn; if the user has now hit WARN_BAN_LIMIT total warns, bans
    them automatically and clears their warn history. Returns
    (count, banned: bool) so callers can adjust the message they send."""
    count = await asyncio.to_thread(add_warn, user_id, chat_id, reason)
    if count >= WARN_BAN_LIMIT:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await asyncio.to_thread(record_ban, user_id, chat_id, f"Auto-banned: {WARN_BAN_LIMIT} warnings reached")
        except TelegramError as e:
            logger.warning("auto-ban after warn limit failed: %s", e)

        def _clear_warns():
            conn = db_connect()
            conn.execute("DELETE FROM warns WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            conn.commit()
            conn.close()

        await asyncio.to_thread(_clear_warns)
        return count, True
    return count, False


def _normalize_for_match(s: str) -> str:
    """Strips accents/style variants via NFKD decomposition (covers most
    'fancy font' unicode blocks -- bold/italic math letters, circled,
    fullwidth, etc. all decompose back to plain ASCII) then keeps only
    alphanumerics, lowercased -- for comparing text regardless of font."""
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if c.isalnum()).lower()


def find_original_title_substring(raw_text: str, ai_title_guess: str) -> str:
    """The AI may 'normalize' stylized/fancy unicode text when reproducing
    it in JSON (a known LLM behavior -- it tends to output plain letters
    even when the input used a decorative font). To preserve the admin's
    EXACT font choice for a tag/title, find the matching word/phrase in the
    ORIGINAL raw message (compared after normalizing) and return that exact
    untouched substring instead of the AI's re-typed version."""
    if not ai_title_guess or not raw_text:
        return ai_title_guess
    target = _normalize_for_match(ai_title_guess)
    if not target:
        return ai_title_guess
    for m in re.finditer(r"['\"“”‘’]([^'\"“”‘’]{1,20})['\"“”‘’]", raw_text):
        if _normalize_for_match(m.group(1)) == target:
            return m.group(1)
    words = raw_text.split()
    for i in range(len(words)):
        for j in range(i + 1, min(i + 4, len(words)) + 1):
            candidate = " ".join(words[i:j])
            if _normalize_for_match(candidate) == target:
                return candidate
    return ai_title_guess  # couldn't locate an exact match -- fall back to the AI's version


async def execute_admin_action(context: ContextTypes.DEFAULT_TYPE, update: Update, result: dict, admin_user, command_text: str = ""):
    msg = update.effective_message
    chat = update.effective_chat
    action = result.get("action", "unknown")
    duration = result.get("duration_minutes")
    title_text = result.get("title")
    try:
        req_count = int(result.get("count") or 1)
    except (TypeError, ValueError):
        req_count = 1
    req_count = max(1, req_count)

    if action == "unknown" or not action:
        # Not a recognized command -- but that doesn't mean it's gibberish.
        # It's very likely a QUESTION ("iska status kya hai group me?..")
        # rather than an instruction. Try answering it like a normal chat
        # reply (using the bot's own docs + the replied-to user's data as
        # context, same as "##" mode) before ever giving up.
        target_for_question = msg.reply_to_message.from_user if msg.reply_to_message else None
        user_data_context = ""
        if target_for_question:
            def _fetch_q_row():
                conn = db_connect()
                r = conn.execute("SELECT * FROM users WHERE user_id=?", (target_for_question.id,)).fetchone()
                conn.close()
                return r
            row = await asyncio.to_thread(_fetch_q_row)
            warns = await asyncio.to_thread(get_warn_count, target_for_question.id, chat.id)
            trust = row["trust_level"] if row else 0
            escrow = "Yes" if (row and row["escrow_verified"]) else "No"
            join_date = row["join_date"][:10] if row and row["join_date"] else "N/A"
            user_data_context = (
                f"Name: {target_for_question.first_name}, "
                f"Username: @{target_for_question.username if target_for_question.username else 'N/A'}, "
                f"User ID: {target_for_question.id}, Warnings: {warns}, "
                f"Trust Level: {TRUST_LEVELS.get(trust)}, Escrow Verified: {escrow}, Joined: {join_date}"
            )
        answer = await ai_owner_chat(command_text or "?", user_data_context)
        await msg.reply_text(stylize(answer))
        return

    if action in OWNER_ONLY_ACTIONS and not is_owner(admin_user.id):
        await msg.reply_text(stylize("🔒 <b>Yeh command sirf owner use kar sakta hai.</b>"), parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user if msg.reply_to_message else None
    username_not_found = False
    if not target and command_text:
        # No reply given -- resolve "@username" from the command text using
        # our in-memory cache (built from every group message, no DM/start
        # needed). Telegram's get_chat is tried only as a backup, for
        # people who aren't currently in the group at all.
        uname_match = re.search(r"@([A-Za-z0-9_]{4,})", command_text)
        if uname_match:
            target = await find_user_by_username(uname_match.group(1), chat.id, context)
            if not target:
                username_not_found = True
    if target:
        # Ensure a DB row exists for the target BEFORE any trust/warn/escrow
        # update -- otherwise UPDATE silently affects 0 rows (no error!) and
        # the change is lost, which was the exact cause of "upgrade sirf
        # Known Member tak hi ja raha tha" bug: target user had never sent a
        # text message since rejoining, so no row existed yet.
        await asyncio.to_thread(upsert_user, target.id, target.username, target.first_name, chat.id)

    try:
        # ---- USER-TARGETED MODERATION ACTIONS ----
        if action in ("ban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
                      "promote", "demote", "escrow_verify", "escrow_unverify",
                      "upgrade_trust", "downgrade_trust", "dispute_freeze",
                      "dispute_unfreeze", "info", "pin", "unpin", "delete", "set_title"):
            if not target:
                await msg.reply_text(
                    stylize(
                        "❌ <b>Yeh user group mein nahi hai ya iska data nahi mila.</b>"
                        if username_not_found else
                        "↩️ <b>Kisi user ke message ko reply karo, ya @username likh kar batao.</b>"
                    ),
                    parse_mode=ParseMode.HTML,
                )
                return

            if action == "ban":
                await context.bot.ban_chat_member(chat.id, target.id)
                await asyncio.to_thread(record_ban, target.id, chat.id, f"Banned by {admin_user.first_name}")
                await msg.reply_text(stylize(f"🔨 <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ban kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "unban":
                await context.bot.unban_chat_member(chat.id, target.id, only_if_banned=True)
                await asyncio.to_thread(remove_ban_record, target.id, chat.id)
                await msg.reply_text(stylize(f"✅ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> unban kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "kick":
                await context.bot.ban_chat_member(chat.id, target.id)
                await context.bot.unban_chat_member(chat.id, target.id)
                await msg.reply_text(stylize(f"👢 <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> kick kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "mute":
                mins = duration or 60
                await mute_user(context, chat.id, target.id, mins)
                await msg.reply_text(stylize(f"🔇 <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> {mins} min ke liye mute!</b>"), parse_mode=ParseMode.HTML)

            elif action == "unmute":
                await unmute_user(context, chat.id, target.id)
                await msg.reply_text(stylize(f"🔊 <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> unmute kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "warn":
                if msg.reply_to_message is not None:
                    try:
                        await msg.reply_to_message.delete()
                    except TelegramError:
                        pass
                # req_count: kitni warnings ek saath deni hain (default 1)
                add_count = 999 if req_count >= 999 else req_count
                count = await asyncio.to_thread(get_warn_count, target.id, chat.id)
                banned = False
                for _ in range(add_count):
                    count, banned = await apply_warn_and_maybe_ban(context, chat.id, target.id, f"Warned by {admin_user.first_name}")
                    if banned:
                        break
                if banned:
                    await msg.reply_text(
                        stylize(f"🔨 <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ko "
                        f"{WARN_BAN_LIMIT} warnings ke baad ban kar diya gaya.</b>"), parse_mode=ParseMode.HTML,
                    )
                else:
                    label = f"{add_count} warnings" if add_count > 1 else "1 warning"
                    await msg.reply_text(stylize(f"⚠️ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ko {label} diye gaye! (Total: {count})</b>"), parse_mode=ParseMode.HTML)

            elif action == "unwarn":
                current_count = await asyncio.to_thread(get_warn_count, target.id, chat.id)
                if current_count == 0:
                    await msg.reply_text(
                        stylize(f"ℹ️ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ki koi warning hai hi nahi, hataane ko kuch nahi hai.</b>"),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    # req_count >= 999 means "saari/sabhi warnings hata do"
                    to_remove = current_count if req_count >= 999 else min(req_count, current_count)

                    def _remove_warns():
                        conn = db_connect()
                        ids = conn.execute(
                            "SELECT id FROM warns WHERE user_id=? AND chat_id=? ORDER BY id DESC LIMIT ?",
                            (target.id, chat.id, to_remove),
                        ).fetchall()
                        for row in ids:
                            conn.execute("DELETE FROM warns WHERE id=?", (row["id"],))
                        conn.commit()
                        conn.close()

                    await asyncio.to_thread(_remove_warns)
                    new_count = await asyncio.to_thread(get_warn_count, target.id, chat.id)
                    label = f"{to_remove} warnings" if to_remove > 1 else "1 warning"
                    await msg.reply_text(stylize(f"✅ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ki {label} hata di gayi! (Baaki: {new_count})</b>"), parse_mode=ParseMode.HTML)

            elif action == "pin":
                if not msg.reply_to_message:
                    await msg.reply_text(stylize("↩️ <b>Jo message pin karna hai, use reply karke command do.</b>"), parse_mode=ParseMode.HTML)
                else:
                    await context.bot.pin_chat_message(chat.id, msg.reply_to_message.message_id)
                    await msg.reply_text(stylize("📌 <b>Message pin kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "unpin":
                if msg.reply_to_message:
                    await context.bot.unpin_chat_message(chat.id, msg.reply_to_message.message_id)
                else:
                    await context.bot.unpin_all_chat_messages(chat.id)
                await msg.reply_text(stylize("📌 <b>Unpin kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "delete":
                if not msg.reply_to_message:
                    await msg.reply_text(stylize("↩️ <b>Jo message delete karna hai, use reply karke command do.</b>"), parse_mode=ParseMode.HTML)
                else:
                    await context.bot.delete_message(chat.id, msg.reply_to_message.message_id)
                    await msg.reply_text(stylize("🗑️ <b>Message delete kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "promote":
                await context.bot.promote_chat_member(
                    chat.id, target.id, can_delete_messages=True, can_restrict_members=True,
                    can_invite_users=True, can_pin_messages=True,
                )
                await msg.reply_text(stylize(f"⭐ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> admin bana diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "demote":
                # Telegram's own rule: "Pass False for all boolean parameters
                # to demote a user." Any right left unspecified simply keeps
                # its previous value -- so passing only can_manage_chat=False
                # (as this used to do) left every other admin right (delete
                # messages, restrict members, invite users, pin messages)
                # untouched, meaning the user stayed effectively an admin.
                # All rights must be explicitly set to False.
                await context.bot.promote_chat_member(
                    chat.id, target.id,
                    is_anonymous=False,
                    can_manage_chat=False,
                    can_delete_messages=False,
                    can_manage_video_chats=False,
                    can_restrict_members=False,
                    can_promote_members=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_post_messages=False,
                    can_edit_messages=False,
                )
                await msg.reply_text(stylize(f"⬇️ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> demote kar diya gaya!</b>"), parse_mode=ParseMode.HTML)

            elif action == "escrow_verify":
                def _set_escrow_verified():
                    conn = db_connect()
                    conn.execute("UPDATE users SET escrow_verified=1 WHERE user_id=?", (target.id,))
                    conn.commit(); conn.close()
                await asyncio.to_thread(_set_escrow_verified)
                await msg.reply_text(stylize(f"💎 <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> escrow-verified!</b>"), parse_mode=ParseMode.HTML)

            elif action == "escrow_unverify":
                def _unset_escrow_verified():
                    conn = db_connect()
                    conn.execute("UPDATE users SET escrow_verified=0 WHERE user_id=?", (target.id,))
                    conn.commit(); conn.close()
                await asyncio.to_thread(_unset_escrow_verified)
                await msg.reply_text(stylize(f"❌ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ka escrow-verified badge hata diya gaya.</b>"), parse_mode=ParseMode.HTML)

            elif action == "upgrade_trust":
                current_lvl = await asyncio.to_thread(get_trust_level, target.id)
                lvl = TRUST_LEVEL_MAX if req_count >= 999 else min(TRUST_LEVEL_MAX, current_lvl + req_count)
                await asyncio.to_thread(set_trust_level, target.id, lvl)
                await msg.reply_text(
                    stylize(f"⭐ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> upgrade kar diya gaya — "
                    f"{TRUST_LEVELS[lvl]}</b>"), parse_mode=ParseMode.HTML,
                )

            elif action == "downgrade_trust":
                current_lvl = await asyncio.to_thread(get_trust_level, target.id)
                lvl = 0 if req_count >= 999 else max(0, current_lvl - req_count)
                await asyncio.to_thread(set_trust_level, target.id, lvl)
                await msg.reply_text(stylize(f"⬇️ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> downgrade kar diya gaya — "
                    f"{TRUST_LEVELS[lvl]}</b>"), parse_mode=ParseMode.HTML)

            elif action == "dispute_freeze":
                _frozen_disputes[chat.id].add(target.id)
                grandparent = msg.reply_to_message.reply_to_message
                # grandparent.from_user can be None (e.g. it was posted by an
                # anonymous admin or a linked channel) -- guard against that
                # instead of crashing with AttributeError.
                if grandparent is not None and grandparent.from_user is not None:
                    _frozen_disputes[chat.id].add(grandparent.from_user.id)
                await msg.reply_text(
                    stylize("🧊 <b>Dispute freeze kar diya gaya hai jab tak owner resolve nahi karta.</b>"),
                    parse_mode=ParseMode.HTML,
                )

            elif action == "dispute_unfreeze":
                _frozen_disputes[chat.id].discard(target.id)
                await msg.reply_text(stylize("✅ <b>Dispute unfreeze kar diya gaya.</b>"), parse_mode=ParseMode.HTML)

            elif action == "info":
                # Give a precise answer to exactly what was asked (e.g. "iska
                # kitna warn hua hai..") instead of always dumping the full
                # profile -- full dump only when the question is genuinely
                # broad ("iski poori info do..").
                def _fetch_user_row():
                    conn = db_connect()
                    r = conn.execute("SELECT * FROM users WHERE user_id=?", (target.id,)).fetchone()
                    conn.close()
                    return r
                row = await asyncio.to_thread(_fetch_user_row)
                warns = await asyncio.to_thread(get_warn_count, target.id, chat.id)
                trust = row["trust_level"] if row else 0
                escrow = "Yes" if (row and row["escrow_verified"]) else "No"
                join_date = row["join_date"][:10] if row and row["join_date"] else "N/A"
                user_data_context = (
                    f"Name: {target.first_name}, Username: @{target.username if target.username else 'N/A'}, "
                    f"User ID: {target.id}, Warnings: {warns}, Trust Level: {TRUST_LEVELS.get(trust)}, "
                    f"Escrow Verified: {escrow}, Joined: {join_date}"
                )
                answer = await ai_owner_chat(command_text or "Iski info do", user_data_context)
                await msg.reply_text(stylize(answer))

            elif action == "set_title":
                if target.id == OWNER_ID:
                    await msg.reply_text(
                        stylize("🔒 <b>Apna khud ka tag/title change nahi kar sakte — sirf doosron ka.</b>"),
                        parse_mode=ParseMode.HTML,
                    )
                elif not title_text:
                    await msg.reply_text(
                        stylize("🤔 <b>Naya title kya rakhna hai woh clearly bolo.</b>"),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    new_title = find_original_title_substring(command_text, str(title_text))[:16]
                    try:
                        await context.bot.set_chat_administrator_custom_title(chat.id, target.id, new_title)
                        await msg.reply_text(
                            stylize(f"🏷️ <b><a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a> ka tag "
                            f"'{md_escape(new_title)}' set kar diya gaya!</b>"),
                            parse_mode=ParseMode.HTML,
                        )
                    except BadRequest:
                        await msg.reply_text(
                            stylize("❌ <b>Yeh sirf admins ke liye kaam karta hai — Telegram ka apna rule hai.</b>\n"
                            "Normal members ka koi tag hota hi nahi Telegram par, sirf admins ke naam ke "
                            "bagal me chota title dikhta hai."),
                            parse_mode=ParseMode.HTML,
                        )

            await asyncio.to_thread(log_admin_action, admin_user.id, admin_user.first_name, action, target.id, json.dumps(result))
            await send_admin_log_dm(context, admin_user, action, target)

        # ---- OWNER-ONLY, NON-USER-TARGETED ----
        elif action == "purge":
            if not msg.reply_to_message:
                await msg.reply_text(stylize("↩️ <b>Jahan tak purge karna hai us message ko reply karo.</b>"), parse_mode=ParseMode.HTML)
                return
            start_id = msg.reply_to_message.message_id
            end_id = msg.message_id
            all_ids = list(range(start_id, end_id + 1))
            deleted = 0
            # Telegram Bot API 7.0+ delete_messages takes up to 100 IDs per
            # call. Batching like this avoids the old one-by-one loop, which
            # fired one API call per message and could trip Telegram's flood
            # limit (429) on larger purges.
            for i in range(0, len(all_ids), 100):
                batch = all_ids[i:i + 100]
                try:
                    await context.bot.delete_messages(chat.id, batch)
                    deleted += len(batch)
                except TelegramError as e:
                    # Some IDs in the batch may already be gone/too old to
                    # delete -- fall back to per-message delete for just
                    # this batch so one bad ID doesn't lose the whole batch.
                    logger.warning("Bulk delete_messages failed for a batch, retrying individually: %s", e)
                    for mid in batch:
                        try:
                            await context.bot.delete_message(chat.id, mid)
                            deleted += 1
                        except TelegramError:
                            continue
            await asyncio.to_thread(log_admin_action, admin_user.id, admin_user.first_name, "purge", 0, f"{deleted} messages")

        elif action == "lock":
            await context.bot.set_chat_permissions(chat.id, ChatPermissions(can_send_messages=False))
            await context.bot.send_message(chat.id, stylize("🔒 <b>Chat lock kar diya gaya — sirf admins bhej sakte hain.</b>"), parse_mode=ParseMode.HTML)
            await asyncio.to_thread(log_admin_action, admin_user.id, admin_user.first_name, "lock", 0, "")

        elif action == "unlock":
            await context.bot.set_chat_permissions(chat.id, ChatPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True))
            await context.bot.send_message(chat.id, stylize("🔓 <b>Chat unlock kar diya gaya!</b>"), parse_mode=ParseMode.HTML)
            await asyncio.to_thread(log_admin_action, admin_user.id, admin_user.first_name, "unlock", 0, "")

    except BadRequest as e:
        # Never dump raw Telegram/technical errors into the group -- log it
        # fully (for Railway logs) and give the admin a short, friendly,
        # non-technical line instead. Full detail also goes to the owner's DM.
        logger.warning("execute_admin_action BadRequest: %s", e)
        await msg.reply_text(
            stylize("❌ <b>Yeh action abhi possible nahi hua — shayad bot ke paas woh permission nahi hai.</b>"),
            parse_mode=ParseMode.HTML,
        )
        try:
            await context.bot.send_message(OWNER_ID, f"⚠️ Admin action failed (BadRequest): {e}")
        except TelegramError:
            pass
    except TelegramError as e:
        logger.warning("execute_admin_action TelegramError: %s", e)
        await msg.reply_text(
            stylize("❌ <b>Yeh action abhi possible nahi hua, dobara try karo.</b>"),
            parse_mode=ParseMode.HTML,
        )
        try:
            await context.bot.send_message(OWNER_ID, f"⚠️ Admin action failed: {e}")
        except TelegramError:
            pass


async def send_admin_log_dm(context, admin_user, action, target):
    # Owner ka apna action -- unhe khud ko DM bhejne ki zaroorat nahi, sirf
    # doosre admins ki actions ka log owner ke DM me jaana chahiye.
    if admin_user.id == OWNER_ID:
        return
    try:
        await context.bot.send_message(
            OWNER_ID,
            stylize(f"📋 <b>Admin Log</b>\n"
            f"👮 Admin: <a href='tg://user?id={admin_user.id}'>{md_escape(admin_user.first_name)}</a>\n"
            f"⚡ Action: <code>{action}</code>\n"
            f"🎯 Target: <a href='tg://user?id={target.id}'>{md_escape(target.first_name)}</a>\n"
            f"🕒 {datetime.now(IST).strftime('%d-%b-%Y %I:%M %p')}"),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


async def send_user_info(context, chat_id, target):
    conn = db_connect()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (target.id,)).fetchone()
    conn.close()
    warns = get_warn_count(target.id, chat_id)
    trust = row["trust_level"] if row else 0
    join_date = row["join_date"][:10] if row and row["join_date"] else "N/A"
    escrow = "💎 Yes" if (row and row["escrow_verified"]) else "❌ No"
    username_html = f"<a href='https://t.me/{target.username}'>@{md_escape(target.username)}</a>" if target.username else "N/A"

    text = (
        f"👤 <b>User Info</b>\n\n"
        f"📛 Name: {md_escape(target.first_name)}\n"
        f"🆔 User ID: <code>{target.id}</code>\n"
        f"🔗 Username: {username_html}\n"
        f"🔗 Profile: <a href='{user_profile_link(target.id, target.username)}'>Click Here</a>\n"
        f"📅 Joined: {join_date}\n"
        f"⚠️ Warnings: {warns}\n"
        f"💎 Escrow Verified: {escrow}\n"
        f"🏆 <b>Status in GC:</b> {TRUST_LEVELS.get(trust, TRUST_LEVELS[0])}"
    )
    final_text, final_entities = render_with_emojis(text)
    await context.bot.send_message(chat_id, final_text, entities=final_entities)


async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/info as a reply -- works for everyone (read-only), separate from AI command flow."""
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text(stylize("↩️ <b>Kisi user ke message ko reply karke /info bhejo.</b>"), parse_mode=ParseMode.HTML)
        return
    await send_user_info(context, update.effective_chat.id, msg.reply_to_message.from_user)


async def emojis_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    rows = await asyncio.to_thread(list_custom_emojis)
    if not rows:
        await update.effective_message.reply_text(stylize("😶 <b>Koi custom emoji saved nahi hai.</b>\nSeedha koi bhi premium emoji mujhe DM me bhejo, save ho jayega."), parse_mode=ParseMode.HTML)
        return
    html_lines = ["🎨 <b>SAVED CUSTOM EMOJIS</b> 🎨\n"]
    for r in rows:
        html_lines.append(f"• {r['placeholder_char']} — <code>{md_escape(r['name'])}</code>")
    final_text, final_entities = render_with_emojis("\n".join(html_lines))
    await context.bot.send_message(update.effective_chat.id, final_text, entities=final_entities)


async def rename_emoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    parts = (update.effective_message.text or "").split()
    if len(parts) != 3:
        await update.effective_message.reply_text(stylize("ℹ️ <b>Use:</b> <code>/renameemoji &lt;old_name&gt; &lt;new_name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    ok = await asyncio.to_thread(rename_custom_emoji, parts[1], parts[2])
    await update.effective_message.reply_text(
        stylize("✅ <b>Rename ho gaya!</b>" if ok else "❌ <b>Yeh naam mila nahi.</b>"), parse_mode=ParseMode.HTML,
    )


async def delete_emoji_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    parts = (update.effective_message.text or "").split()
    if len(parts) != 2:
        await update.effective_message.reply_text(stylize("ℹ️ <b>Use:</b> <code>/delemoji &lt;name&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    ok = await asyncio.to_thread(delete_custom_emoji, parts[1])
    await update.effective_message.reply_text(
        stylize("✅ <b>Delete ho gaya!</b>" if ok else "❌ <b>Yeh naam mila nahi.</b>"), parse_mode=ParseMode.HTML,
    )


async def filters_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    rows = await asyncio.to_thread(get_filters, update.effective_chat.id)
    if not rows:
        await update.effective_message.reply_text(stylize("😶 <b>Is group me koi filter set nahi hai.</b>"), parse_mode=ParseMode.HTML)
        return
    lines = ["🔖 <b>ACTIVE FILTERS</b> 🔖\n"] + [f"• <code>{md_escape(r['trigger'])}</code>" for r in rows]
    await update.effective_message.reply_text(stylize("\n".join(lines)), parse_mode=ParseMode.HTML)


async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only, DM: /grant <user_id> <chat_id> -- lets another person
    customize the bot's welcome message/buttons for ONE specific group
    (their own group where they've made this bot admin). This does NOT
    give Telegram-admin powers -- moderation (ban/warn/etc.) still needs
    them to be a real admin of that group; this only unlocks the bot's
    per-group customization settings for that chat_id."""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    parts = (update.effective_message.text or "").split()
    if len(parts) != 3:
        await update.effective_message.reply_text(
            stylize("ℹ️ <b>Use:</b> <code>/grant &lt;user_id&gt; &lt;group_id&gt;</code>\n\n"
            "Pehle bot ko us group me admin (full permissions ke saath) banao, "
            "phir yeh command bhejo."), parse_mode=ParseMode.HTML,
        )
        return
    try:
        target_user_id = int(parts[1])
        target_chat_id = int(parts[2])
    except ValueError:
        await update.effective_message.reply_text(stylize("❌ <b>user_id aur group_id dono number hone chahiye.</b>"), parse_mode=ParseMode.HTML)
        return

    try:
        member = await context.bot.get_chat_member(target_chat_id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            raise TelegramError("not admin")
    except TelegramError:
        await update.effective_message.reply_text(
            stylize("❌ <b>Bot us group me admin nahi hai (ya group ID galat hai).</b>\n"
            "Pehle bot ko us group me full-permission admin banao, phir dobara try karo."),
            parse_mode=ParseMode.HTML,
        )
        return

    await asyncio.to_thread(grant_group_access, target_chat_id, target_user_id, OWNER_ID)
    newly_approved = not is_group_approved(target_chat_id)
    await asyncio.to_thread(approve_group, target_chat_id, OWNER_ID)
    try:
        group_chat = await context.bot.get_chat(target_chat_id)
        group_name = group_chat.title or str(target_chat_id)
    except TelegramError:
        group_name = str(target_chat_id)

    await update.effective_message.reply_text(
        stylize(f"✅ <b>Access de diya gaya (aur group approve ho gaya)!</b>\nUser <code>{target_user_id}</code> ab "
        f"'<b>{md_escape(group_name)}</b>' (<code>{target_chat_id}</code>) ke liye bot customize kar sakta hai."),
        parse_mode=ParseMode.HTML,
    )
    if newly_approved:
        try:
            await context.bot.send_message(target_chat_id, stylize("✅ <b>Yeh group ab approved hai — bot ab se fully active hai!</b>"), parse_mode=ParseMode.HTML)
        except TelegramError:
            pass
    try:
        await context.bot.send_message(
            target_user_id,
            stylize(f"🎉 <b>Aapko '{md_escape(group_name)}' group ke liye is bot ka access mil gaya hai!</b>\n\n"
            f"Customize karne ke liye mujhe DM me yeh bhejo:\n<code>/mygroup {target_chat_id}</code>"),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass  # user might not have started a DM with the bot yet -- that's fine, /grant still worked


async def approve_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only, DM: /approve <chat_id> -- the bot does NOTHING (no
    moderation, no welcome, nothing) in any group until its chat_id is
    approved here. Existing groups the bot was already active in before
    this system existed were grandfathered in automatically (see db_init)."""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    parts = (update.effective_message.text or "").split()
    if len(parts) != 2:
        await update.effective_message.reply_text(stylize("ℹ️ <b>Use:</b> <code>/approve &lt;group_id&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    try:
        target_chat_id = int(parts[1])
    except ValueError:
        await update.effective_message.reply_text(stylize("❌ <b>group_id ek number hona chahiye.</b>"), parse_mode=ParseMode.HTML)
        return
    try:
        member = await context.bot.get_chat_member(target_chat_id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            raise TelegramError("not admin")
        group_chat = await context.bot.get_chat(target_chat_id)
    except TelegramError:
        await update.effective_message.reply_text(
            stylize("❌ <b>Bot us group me admin nahi hai (ya group ID galat hai).</b>"), parse_mode=ParseMode.HTML,
        )
        return
    await asyncio.to_thread(approve_group, target_chat_id, OWNER_ID)
    await update.effective_message.reply_text(
        stylize(f"✅ <b>'{md_escape(group_chat.title or str(target_chat_id))}' approve ho gaya — ab bot yahan pura kaam karega.</b>"),
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(target_chat_id, stylize("✅ <b>Yeh group ab approved hai — bot ab se fully active hai!</b>"), parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only, DM:
    - /revoke <group_id>              -> fully disapprove the group (bot goes
                                          silent there -- no moderation, no
                                          welcome, nothing, until re-approved)
    - /revoke <user_id> <group_id>    -> revoke just that ONE person's
                                          settings-customization access
                                          (group itself stays approved)"""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    parts = (update.effective_message.text or "").split()

    if len(parts) == 2:
        try:
            target_chat_id = int(parts[1])
        except ValueError:
            await update.effective_message.reply_text(stylize("❌ <b>group_id ek number hona chahiye.</b>"), parse_mode=ParseMode.HTML)
            return
        removed = await asyncio.to_thread(disapprove_group, target_chat_id)
        await update.effective_message.reply_text(
            stylize("✅ <b>Group disapprove kar diya gaya — bot ab wahan kuch nahi karega.</b>" if removed
                    else "ℹ️ <b>Yeh group pehle se approved nahi tha.</b>"),
            parse_mode=ParseMode.HTML,
        )
        try:
            await context.bot.send_message(
                target_chat_id,
                stylize(f"🚫 <b>Is group ke liye approval hata di gayi hai.</b>\nApproval ke liye owner se "
                f"contact karo: @{OWNER_USERNAME}"),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    if len(parts) == 3:
        try:
            target_user_id, target_chat_id = int(parts[1]), int(parts[2])
        except ValueError:
            await update.effective_message.reply_text(stylize("❌ <b>user_id aur group_id dono number hone chahiye.</b>"), parse_mode=ParseMode.HTML)
            return
        await asyncio.to_thread(revoke_group_access, target_chat_id, target_user_id)
        await update.effective_message.reply_text(stylize("✅ <b>Access revoke kar diya gaya.</b>"), parse_mode=ParseMode.HTML)
        return

    await update.effective_message.reply_text(
        stylize("ℹ️ <b>Use:</b>\n<code>/revoke &lt;group_id&gt;</code> — poore group ko disapprove karo\n"
        "<code>/revoke &lt;user_id&gt; &lt;group_id&gt;</code> — sirf uss ek user ka settings-access hatao"),
        parse_mode=ParseMode.HTML,
    )


def group_panel_markup(chat_id):
    buttons = [
        [InlineKeyboardButton(fancy("✏️ Welcome Message"), callback_data=f"gpanel_wtext_{chat_id}", style="primary")],
        [InlineKeyboardButton(fancy("🔘 Button (text + link)"), callback_data=f"gpanel_button_{chat_id}", style="primary")],
        [InlineKeyboardButton(fancy("📢 Channel Link"), callback_data=f"gpanel_channel_{chat_id}", style="success")],
    ]
    return InlineKeyboardMarkup(buttons)


async def mygroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Granted-user, DM: /mygroup <chat_id> -- opens the settings panel scoped
    to just that one group, after re-verifying access + bot's admin status."""
    if update.effective_chat.type != "private":
        return
    parts = (update.effective_message.text or "").split()
    if len(parts) != 2:
        await update.effective_message.reply_text(stylize("ℹ️ <b>Use:</b> <code>/mygroup &lt;group_id&gt;</code>"), parse_mode=ParseMode.HTML)
        return
    try:
        target_chat_id = int(parts[1])
    except ValueError:
        await update.effective_message.reply_text(stylize("❌ <b>group_id ek number hona chahiye.</b>"), parse_mode=ParseMode.HTML)
        return

    user_id = update.effective_user.id
    if user_id != OWNER_ID and not await asyncio.to_thread(has_group_access, target_chat_id, user_id):
        await update.effective_message.reply_text(stylize("🔒 <b>Aapko is group ke liye access nahi diya gaya hai.</b>"), parse_mode=ParseMode.HTML)
        return

    try:
        member = await context.bot.get_chat_member(target_chat_id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            raise TelegramError("not admin")
        group_chat = await context.bot.get_chat(target_chat_id)
    except TelegramError:
        await update.effective_message.reply_text(
            stylize("❌ <b>Verify nahi ho paya — bot ab us group me admin nahi hai, ya group ID galat hai.</b>"),
            parse_mode=ParseMode.HTML,
        )
        return

    context.user_data["active_group"] = target_chat_id
    await update.effective_message.reply_text(
        stylize(f"⚙️ <b>Settings — {md_escape(group_chat.title or str(target_chat_id))}</b>\n\nNeeche se choose karo:"),
        parse_mode=ParseMode.HTML,
        reply_markup=group_panel_markup(target_chat_id),
    )


async def group_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    m = re.match(r"gpanel_(wtext|button|channel)_(-?\d+)", data)
    if not m:
        return
    field, chat_id = m.group(1), int(m.group(2))

    if user_id != OWNER_ID and not await asyncio.to_thread(has_group_access, chat_id, user_id):
        await query.edit_message_text(stylize("🔒 <b>Access nahi hai.</b>"), parse_mode=ParseMode.HTML)
        return

    context.user_data["active_group"] = chat_id
    if field == "wtext":
        context.user_data["panel_state"] = AWAITING_GROUP_WELCOME_TEXT
        gs = await asyncio.to_thread(get_group_settings, chat_id)
        current = gs.get("welcome_text") or DEFAULT_WELCOME_TEMPLATE
        await query.edit_message_text(
            stylize("✏️ <b>Abhi yeh welcome message chal raha hai</b> (copy karke edit karo, phir wapas bhej do):"),
            parse_mode=ParseMode.HTML,
        )
        await context.bot.send_message(query.message.chat_id, f"<pre>{md_escape(current)}</pre>", parse_mode=ParseMode.HTML)
        await context.bot.send_message(
            query.message.chat_id,
            stylize("↩️ <b>Isko copy-edit karke seedha yahan bhej do, set ho jayega.</b>\n\n"
            "Placeholders: <code>{name}</code> <code>{group}</code> <code>{id}</code> "
            "<code>{username}</code> <code>{profile}</code>\n"
            "Profile picture (agar member ki lagi hai) hamesha automatic attach hoga, "
            "isse alag se kuch nahi karna.\n\n"
            "🎨 Premium emoji seedha type/paste karke bhejo — khud-ba-khud save + set ho jayega, "
            "koi placeholder nahi lagana."),
            parse_mode=ParseMode.HTML,
        )
    elif field == "button":
        context.user_data["panel_state"] = AWAITING_GROUP_BUTTON
        await query.edit_message_text(
            stylize("🔘 <b>Button text aur link bhejo, ' | ' se alag karke.</b>\n\n"
            "Example: <code>Contact Owner | https://t.me/yourusername</code>"),
            parse_mode=ParseMode.HTML,
        )
    elif field == "channel":
        context.user_data["panel_state"] = AWAITING_GROUP_CHANNEL
        await query.edit_message_text(
            stylize("📢 <b>Apne channel ka username bhejo</b> (jaise <code>@mychannel</code>)."),
            parse_mode=ParseMode.HTML,
        )


async def trusted_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_all_trusted(update.effective_chat.id)
    if not rows:
        await update.effective_message.reply_text(stylize("😶 <b>Abhi tak koi Trusted Trader nahi hai.</b>"), parse_mode=ParseMode.HTML)
        return
    lines = ["🏆 <b>TRUSTED TRADERS LIST</b> 🏆\n"]
    for r in rows:
        badge = TRUST_LEVELS.get(r["trust_level"], "")
        uname = f"@{md_escape(r['username'])}" if r["username"] else md_escape(r["first_name"])
        lines.append(f"• {badge} — <a href='tg://user?id={r['user_id']}'>{md_escape(r['first_name'])}</a> ({uname})")
    await update.effective_message.reply_text(stylize("\n".join(lines)), parse_mode=ParseMode.HTML)


# =============================================================================
# ADMIN PANEL (bot DM, owner only)
# =============================================================================
def admin_panel_markup():
    buttons = [
        [InlineKeyboardButton(fancy("⚙️ My Groups (Welcome/Buttons)"), callback_data="panel_mygroups", style="primary")],
        [InlineKeyboardButton(fancy("💾 Save Custom Emoji"), callback_data="panel_saveemoji", style="success")],
        [InlineKeyboardButton(fancy("📢 Manage Welcome Channels"), callback_data="panel_channels", style="primary")],
        [InlineKeyboardButton(fancy("📤 Export Database"), callback_data="panel_export", style="success"),
         InlineKeyboardButton(fancy("📥 Import Database"), callback_data="panel_import", style="success")],
        [InlineKeyboardButton(fancy("🏆 Trusted Traders"), callback_data="panel_trusted", style="primary")],
    ]
    return InlineKeyboardMarkup(buttons)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text(stylize("👋 <b>Namaste! Group management ke liye taiyar hoon.</b>"), parse_mode=ParseMode.HTML)
        return
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(stylize("🔒 <b>Yeh admin panel sirf owner ke liye hai.</b>"), parse_mode=ParseMode.HTML)
        return
    await update.effective_message.reply_text(
        stylize("👑 <b>ADMIN PANEL</b> 👑\n\nNeeche se option choose karo:"),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_panel_markup(),
    )


AWAITING_CHANNEL_INPUT = "awaiting_channel_username"
AWAITING_IMPORT_FILE = "awaiting_import_file"
AWAITING_GROUP_WELCOME_TEXT = "awaiting_group_welcome_text"
AWAITING_GROUP_BUTTON = "awaiting_group_button"
AWAITING_GROUP_CHANNEL = "awaiting_group_channel"


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.edit_message_text(stylize("🔒 <b>Sirf owner use kar sakta hai.</b>"), parse_mode=ParseMode.HTML)
        return

    data = query.data

    if data == "panel_saveemoji":
        await query.edit_message_text(
            stylize("💾 <b>Save Custom Emoji</b>\n\nMujhe DM me seedha koi bhi premium/custom emoji "
            "bhejo (naam ke saath ya bina) — automatic save ho jayega, koi command nahi chahiye. "
            "Ek message me multiple emoji bhejoge to sab alag-alag save ho jayenge.\n\n"
            "Dekhne/manage karne ke liye: <code>/emojis</code>, <code>/renameemoji</code>, <code>/delemoji</code>"),
            parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup(),
        )
        return

    if data == "panel_mygroups":
        groups = await asyncio.to_thread(get_known_groups)
        if not groups:
            await query.edit_message_text(
                stylize("😶 <b>Abhi tak koi group track nahi hua.</b>\nGroup me koi bhi message aane ke baad wahan list ho jayega."),
                parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup(),
            )
            return
        buttons = [[InlineKeyboardButton(fancy(g["title"] or str(g["chat_id"]))[:60], callback_data=f"gpick_{g['chat_id']}", style="primary")] for g in groups]
        buttons.append([InlineKeyboardButton(fancy("⬅️ Back"), callback_data="panel_back", style="primary")])
        await query.edit_message_text(
            stylize("⚙️ <b>Kis group ki settings edit karni hai?</b>"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data.startswith("gpick_"):
        chat_id = int(data[len("gpick_"):])
        try:
            member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if member.status not in ("administrator", "creator"):
                raise TelegramError("not admin")
            group_chat = await context.bot.get_chat(chat_id)
        except TelegramError:
            await query.edit_message_text(stylize("❌ <b>Bot ab is group me admin nahi hai.</b>"), parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup())
            return
        context.user_data["active_group"] = chat_id
        await query.edit_message_text(
            stylize(f"⚙️ <b>Settings — {md_escape(group_chat.title or str(chat_id))}</b>\n\nNeeche se choose karo:"),
            parse_mode=ParseMode.HTML, reply_markup=group_panel_markup(chat_id),
        )

    elif data == "panel_channels":
        channels = get_welcome_channels()
        text = "📢 <b>Welcome Message Channels</b>\n\n"
        text += "\n".join(f"• @{md_escape(c)}" for c in channels) if channels else "<i>Koi channel set nahi hai.</i>"
        text += "\n\n➡️ Naya channel add karne ke liye uska <b>username</b> bhejo (jaise @mychannel)."
        context.user_data["panel_state"] = AWAITING_CHANNEL_INPUT
        buttons = [[InlineKeyboardButton(f"{fancy('❌ Remove')} @{c}", callback_data=f"rmchan_{c}", style="danger")] for c in channels]
        buttons.append([InlineKeyboardButton(fancy("⬅️ Back"), callback_data="panel_back", style="primary")])
        await query.edit_message_text(stylize(text), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("rmchan_"):
        uname = data[len("rmchan_"):]
        await asyncio.to_thread(remove_welcome_channel, uname)
        await query.edit_message_text(stylize(f"✅ <b>@{md_escape(uname)} remove kar diya gaya.</b>"), parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup())

    elif data == "panel_export":
        raw = await asyncio.to_thread(db_export_json)
        bio = io.BytesIO(raw.encode("utf-8"))
        bio.name = DB_BACKUP_FILENAME
        await context.bot.send_document(update.effective_chat.id, document=InputFile(bio, filename=DB_BACKUP_FILENAME),
                                         caption="📤 <b>Database Export</b>")

    elif data == "panel_import":
        context.user_data["panel_state"] = AWAITING_IMPORT_FILE
        await query.edit_message_text(
            stylize(f"📥 <b>Import Database</b>\n\nMujhe <code>{DB_BACKUP_FILENAME}</code> file bhejo (exact same format wali)."),
            parse_mode=ParseMode.HTML,
        )

    elif data == "panel_trusted":
        def _fetch_trusted():
            conn = db_connect()
            r = conn.execute("SELECT user_id, username, first_name, trust_level FROM users WHERE trust_level >= 2").fetchall()
            conn.close()
            return r
        rows = await asyncio.to_thread(_fetch_trusted)
        if not rows:
            text = "😶 <b>Koi Trusted Trader nahi hai abhi.</b>"
        else:
            text = "🏆 <b>Trusted Traders (All Groups)</b>\n\n" + "\n".join(
                f"• {TRUST_LEVELS.get(r['trust_level'])} — {md_escape(r['first_name'])} (<code>{r['user_id']}</code>)" for r in rows
            )
        await query.edit_message_text(stylize(text), parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup())

    elif data == "panel_back":
        await query.edit_message_text(stylize("👑 <b>ADMIN PANEL</b> 👑\n\nNeeche se option choose karo:"), parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup())


async def maybe_handle_custom_emoji_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """If this DM (owner only) contains one or more real custom/premium emoji,
    auto-extract each one's custom_emoji_id + auto-derive a name from the word
    right next to it, and save -- NO manual ID entry needed at all. Returns
    True if it handled the message (caller should stop further processing)."""
    msg = update.effective_message
    if update.effective_user.id != OWNER_ID:
        return False
    text = msg.text or msg.caption or ""
    ents = list(msg.entities or msg.caption_entities or [])
    custom_ents = [e for e in ents if e.type == MessageEntity.CUSTOM_EMOJI]
    if not custom_ents:
        return False

    lines = []
    for e in custom_ents:
        already = await asyncio.to_thread(get_custom_emoji_by_id, e.custom_emoji_id)
        if already:
            lines.append(f"ℹ️ Yeh emoji pehle se '<code>{md_escape(already['name'])}</code>' naam se saved hai (duplicate skip).")

    newly_saved = await asyncio.to_thread(auto_save_new_emojis_from_message, text, custom_ents, update.effective_user.id)
    for name in newly_saved:
        row = await asyncio.to_thread(get_custom_emoji_by_name, name)
        lines.append(
            f"✅ <b>Custom Emoji Saved</b>\nName: {row['placeholder_char']}\nLabel: <code>{md_escape(name)}</code>\n"
            f"ID: <code>{row['custom_emoji_id']}</code>\n\nUse: <code>{{{name}}}</code> (ya bas isse seedha copy-paste karke bhi bhej sakte ho)"
        )

    final_text, final_entities = render_with_emojis("\n\n".join(lines))
    await context.bot.send_message(update.effective_chat.id, final_text, entities=final_entities)
    return True


async def dm_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles plain-text replies for both the owner's global panel and a
    granted user's per-group settings panel (DM only)."""
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    state = context.user_data.get("panel_state")

    if state == AWAITING_CHANNEL_INPUT and user_id == OWNER_ID:
        text = (update.effective_message.text or "").strip().lstrip("@")
        if not text:
            return
        await asyncio.to_thread(add_welcome_channel, text)
        context.user_data["panel_state"] = None
        await update.effective_message.reply_text(
            stylize(f"✅ <b>@{text} welcome-channel list me add ho gaya!</b>"),
            parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup(),
        )
        return

    if state in (AWAITING_GROUP_WELCOME_TEXT, AWAITING_GROUP_BUTTON, AWAITING_GROUP_CHANNEL):
        chat_id = context.user_data.get("active_group")
        if chat_id is None:
            return
        if user_id != OWNER_ID and not await asyncio.to_thread(has_group_access, chat_id, user_id):
            context.user_data["panel_state"] = None
            return
        raw_text = update.effective_message.text or ""
        text = raw_text.strip()
        if not text:
            return

        if state == AWAITING_GROUP_WELCOME_TEXT:
            # Real premium emoji pasted directly (no {name} needed) -- auto
            # -save any that aren't already known. stylize() will then
            # auto-wrap this exact glyph in <tg-emoji> every time this
            # welcome text is rendered, from now on.
            newly_saved = await asyncio.to_thread(
                auto_save_new_emojis_from_message, raw_text, update.effective_message.entities, user_id
            )
            await asyncio.to_thread(set_group_setting, chat_id, "welcome_text", text)
            reply = "✅ <b>Welcome message update ho gaya!</b>"
            if newly_saved:
                reply += f"\n💾 <b>{len(newly_saved)} naye premium emoji bhi save ho gaye.</b>"
        elif state == AWAITING_GROUP_BUTTON:
            if "|" not in text:
                await update.effective_message.reply_text(
                    stylize("❌ <b>Format galat hai.</b> Example: <code>Contact Owner | https://t.me/yourusername</code>"),
                    parse_mode=ParseMode.HTML,
                )
                return
            btn_text, btn_url = [p.strip() for p in text.split("|", 1)]
            # Auto-fix a common mistake: URL bina http(s):// ke daala gaya ho
            # (jaise 't.me/xyz' ya 'yoursite.com') -- Telegram is bina yeh
            # poora welcome message hi reject kar deta hai, isliye yahin fix karo.
            if not re.match(r"^https?://", btn_url, re.IGNORECASE) and not btn_url.startswith("tg://"):
                btn_url = "https://" + btn_url
            if not re.match(r"^https?://[^\s]+\.[^\s]+", btn_url, re.IGNORECASE) and not btn_url.startswith("tg://"):
                await update.effective_message.reply_text(
                    stylize(f"❌ <b>Yeh link valid nahi lag raha:</b> <code>{md_escape(btn_url)}</code>\n"
                    "Poora link do, jaise <code>https://t.me/yourusername</code>"),
                    parse_mode=ParseMode.HTML,
                )
                return
            await asyncio.to_thread(set_group_setting, chat_id, "button_text", btn_text)
            await asyncio.to_thread(set_group_setting, chat_id, "button_url", btn_url)
            reply = "✅ <b>Button update ho gaya!</b>"
        else:  # AWAITING_GROUP_CHANNEL
            await asyncio.to_thread(set_group_setting, chat_id, "channel_username", text.lstrip("@"))
            reply = "✅ <b>Channel link update ho gaya!</b>"

        context.user_data["panel_state"] = None
        await update.effective_message.reply_text(stylize(reply), parse_mode=ParseMode.HTML, reply_markup=group_panel_markup(chat_id))
        return

    # No active panel flow -- treat as a standalone "save this emoji" DM.
    await maybe_handle_custom_emoji_save(update, context)


async def dm_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles a database file sent after 'Import Database' is pressed (owner DM only)."""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    state = context.user_data.get("panel_state")
    if state != AWAITING_IMPORT_FILE:
        return
    doc = update.effective_message.document
    if not doc:
        return
    file = await context.bot.get_file(doc.file_id)
    raw_bytes = await file.download_as_bytearray()
    try:
        raw_text = bytes(raw_bytes).decode("utf-8")
    except UnicodeDecodeError:
        await update.effective_message.reply_text(stylize("❌ <b>File read nahi ho payi.</b>"), parse_mode=ParseMode.HTML)
        return
    ok, message_text = await asyncio.to_thread(db_import_json, raw_text)
    context.user_data["panel_state"] = None
    await update.effective_message.reply_text(stylize(message_text), parse_mode=ParseMode.HTML, reply_markup=admin_panel_markup())


# =============================================================================
# SCHEDULED JOBS
# =============================================================================
async def job_backup_to_channel(context: ContextTypes.DEFAULT_TYPE):
    if not BACKUP_CHANNEL_ID:
        return
    try:
        raw = db_export_json()
        bio = io.BytesIO(raw.encode("utf-8"))
        bio.name = DB_BACKUP_FILENAME
        await context.bot.send_document(
            int(BACKUP_CHANNEL_ID), document=InputFile(bio, filename=DB_BACKUP_FILENAME),
            caption=f"🗄️ <b>Auto-backup</b> — {datetime.now(IST).strftime('%d-%b-%Y %I:%M %p')}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning("Backup job failed: %s", e)


async def job_warn_expiry(context: ContextTypes.DEFAULT_TYPE):
    clear_expired_warns()


async def job_ghost_account_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Nightly (1-2 AM): scan known users, remove ones whose account was deleted."""
    conn = db_connect()
    rows = conn.execute("SELECT DISTINCT user_id, chat_id FROM users").fetchall()
    conn.close()
    removed = 0
    for row in rows:
        try:
            chat_member = await context.bot.get_chat(row["user_id"])
            if getattr(chat_member, "first_name", None) is None and getattr(chat_member, "username", None) is None:
                # looks like a deleted account
                try:
                    await context.bot.ban_chat_member(row["chat_id"], row["user_id"])
                    await context.bot.unban_chat_member(row["chat_id"], row["user_id"])
                    removed += 1
                except TelegramError:
                    pass
        except TelegramError:
            continue
        finally:
            # Small delay between each get_chat call so a large user table
            # (hundreds+ of rows) doesn't fire a burst of API calls fast
            # enough to trip Telegram's 429 FloodWait.
            await asyncio.sleep(0.3)
    if removed:
        logger.info("Ghost account cleanup: removed %d deleted accounts", removed)


async def job_raid_watchdog(context: ContextTypes.DEFAULT_TYPE):
    await raid_watchdog(context)


async def job_recheck_impersonators(context: ContextTypes.DEFAULT_TYPE):
    await recheck_impersonators(context)


# =============================================================================
# GLOBAL ERROR HANDLER
# =============================================================================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Catches every unhandled exception from any handler/job so the bot
    never silently stops working, and never crashes the whole process.

    IMPORTANT: this does NOT DM the owner anymore. All errors go to Railway
    logs only (that's where they belong -- visible, but not spamming chat).

    Some errors are expected/self-healing noise, not real problems:
      - telegram.error.Conflict: happens for a few seconds during every
        redeploy while the old container is still shutting down and the new
        one has already started polling. python-telegram-bot automatically
        retries and resolves this on its own within seconds -- it is logged
        as a WARNING (not ERROR) so it doesn't look alarming in the logs.
      - telegram.error.NetworkError / TimedOut: transient network hiccups,
        PTB retries automatically. Logged as WARNING.
    Anything else is a real bug and gets logged as ERROR with the full
    traceback so it's easy to find in Railway's Deploy Logs.
    """
    err = context.error

    if isinstance(err, TelegramConflictError):
        logger.warning(
            "Conflict detected (normal during redeploy -- old container still "
            "stopping while new one starts). Self-resolves automatically, no action needed."
        )
        return

    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning("Transient network error, python-telegram-bot will auto-retry: %s", err)
        return

    logger.error("Unhandled exception while processing an update:", exc_info=err)


# =============================================================================
# MAIN
# =============================================================================
def _has_emoji_candidate(text) -> bool:
    """Cheap pre-check so we don't bother building entities for the vast
    majority of messages that have no emoji token/saved-char at all."""
    if not text or not isinstance(text, str):
        return False
    if "{" in text:
        return True
    return any(c in text for c in _custom_emoji_cache_by_char)


class EmojiAwareBot(ExtBot):
    """Transparently upgrades any parse_mode=HTML text/caption containing a
    saved premium-emoji char (or a {name} token) into a proper entities-
    based send, so real custom/premium emoji work across the WHOLE bot
    without needing every single call site converted by hand.

    Uses inspect.signature to bind against the REAL parent method's
    signature at runtime (rather than assuming a fixed positional
    parameter order), so it stays correct regardless of exact
    python-telegram-bot version/signature details. Any failure at any
    point falls back to calling the original method completely
    unmodified -- this can only ever skip an upgrade, never break a send."""

    async def _call_upgraded(self, parent_method, text_field, entities_field, args, kwargs):
        try:
            sig = inspect.signature(parent_method)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            if bound.arguments.get("parse_mode") == ParseMode.HTML:
                html_text = bound.arguments.get(text_field)
                if _has_emoji_candidate(html_text):
                    final_text, entities = render_with_emojis(html_text)
                    if entities:
                        bound.arguments[text_field] = final_text
                        bound.arguments[entities_field] = entities
                        bound.arguments["parse_mode"] = None
            return await parent_method(*bound.args, **bound.kwargs)
        except Exception:
            logger.exception("EmojiAwareBot upgrade failed for %s -- sending unmodified", text_field)
            return await parent_method(*args, **kwargs)

    async def send_message(self, *args, **kwargs):
        return await self._call_upgraded(super().send_message, "text", "entities", args, kwargs)

    async def send_photo(self, *args, **kwargs):
        return await self._call_upgraded(super().send_photo, "caption", "caption_entities", args, kwargs)

    async def send_animation(self, *args, **kwargs):
        return await self._call_upgraded(super().send_animation, "caption", "caption_entities", args, kwargs)

    async def send_video(self, *args, **kwargs):
        return await self._call_upgraded(super().send_video, "caption", "caption_entities", args, kwargs)

    async def send_document(self, *args, **kwargs):
        return await self._call_upgraded(super().send_document, "caption", "caption_entities", args, kwargs)

    async def edit_message_text(self, *args, **kwargs):
        return await self._call_upgraded(super().edit_message_text, "text", "entities", args, kwargs)

    async def edit_message_caption(self, *args, **kwargs):
        return await self._call_upgraded(super().edit_message_caption, "caption", "caption_entities", args, kwargs)


def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN environment variable is not set!")
    if not GROK_API_KEYS:
        logger.warning("⚠️ No GROK_API_KEYS set -- AI features will not work until you add them.")
    if not BACKUP_CHANNEL_ID:
        logger.warning(
            "⚠️ BACKUP_CHANNEL_ID not set! Database is NOT being backed up. "
            "Railway wipes local storage on every redeploy -- ALL data (warns, "
            "bans, trust levels) will be permanently lost on the next redeploy "
            "unless you set BACKUP_CHANNEL_ID."
        )

    db_init()
    _refresh_custom_emoji_cache()
    _refresh_approved_groups_cache()

    builder = ApplicationBuilder()
    try:
        custom_request = HTTPXRequest(connect_timeout=15, read_timeout=20, write_timeout=20, pool_timeout=15)
        emoji_bot = EmojiAwareBot(token=BOT_TOKEN, request=custom_request)
        builder = builder.bot(emoji_bot)
    except Exception:
        logger.exception("Could not build EmojiAwareBot, falling back to plain bot (premium-emoji auto-upgrade disabled).")
        builder = (
            builder.token(BOT_TOKEN)
            .connect_timeout(15)
            .read_timeout(20)
            .write_timeout(20)
            .pool_timeout(15)
        )

    app = (
        builder
        # concurrent_updates=True: without this, PTB's default is to process
        # updates ONE AT A TIME. If any single handler call ever hangs or is
        # slow (a Telegram API call with no strict timeout, an AI call that
        # takes long), EVERY user in EVERY group gets stuck waiting behind
        # it -- this is the most likely reason the bot "worked for a while
        # then stopped responding to everyone" even though the background
        # jobs kept running fine (jobs run on a separate scheduler, not
        # through the update queue).
        .concurrent_updates(True)
        .build()
    )

    # commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("trusted", trusted_command))
    app.add_handler(CommandHandler("info", user_info_command))
    app.add_handler(CommandHandler("filters", filters_list_command))
    app.add_handler(CommandHandler("grant", grant_command))
    app.add_handler(CommandHandler("approve", approve_group_command))
    app.add_handler(CommandHandler("revoke", revoke_command))
    app.add_handler(CommandHandler("mygroup", mygroup_command))
    app.add_handler(CommandHandler("emojis", emojis_list_command))
    app.add_handler(CommandHandler("renameemoji", rename_emoji_command))
    app.add_handler(CommandHandler("delemoji", delete_emoji_command))

    # group events
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & filters.ChatType.GROUPS & ~filters.COMMAND,
        handle_group_message,
    ))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.ChatType.GROUPS, handle_edited_message))
    # Catches command-style filter triggers (e.g. "/like") that fell through
    # because none of the named CommandHandlers above matched -- MUST be
    # registered after all of them so it never intercepts a real bot command.
    app.add_handler(MessageHandler(filters.COMMAND & filters.ChatType.GROUPS, handle_unknown_group_command))

    # admin panel (DM)
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^(panel_|rmchan_)"))
    app.add_handler(CallbackQueryHandler(group_panel_callback, pattern="^gpanel_"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, dm_text_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, dm_document_handler))

    # GLOBAL ERROR HANDLER -- catches any unhandled exception from any
    # handler above so the bot never silently dies. Logs it fully to
    # Railway's logs (see global_error_handler's own docstring for exactly
    # what is/isn't sent to the owner's DM).
    app.add_error_handler(global_error_handler)

    # scheduled jobs
    job_queue = app.job_queue
    job_queue.run_repeating(job_backup_to_channel, interval=1800, first=60)          # every 30 min
    job_queue.run_repeating(job_warn_expiry, interval=3600, first=30)                # hourly check
    job_queue.run_repeating(job_raid_watchdog, interval=10, first=10)                # every 10s
    job_queue.run_repeating(job_recheck_impersonators, interval=1800, first=120)     # every 30 min
    # tzinfo=IST attached explicitly -- without it, PTB's JobQueue schedules
    # naive times against UTC (Railway's server timezone), so this used to
    # fire at 1:30 AM UTC (= 7:00 AM IST, not the intended low-traffic hour).
    job_queue.run_daily(
        job_ghost_account_cleanup,
        time=datetime.strptime("01:30", "%H:%M").time().replace(tzinfo=IST),
    )  # 1:30 AM IST

    logger.info("🚀 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

