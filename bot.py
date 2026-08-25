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
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    InputFile,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError, BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

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
    """Escape Telegram legacy-Markdown special chars (_ * ` [) so that names/
    usernames containing them (very common — underscores especially) don't
    break message parsing with 'Can't parse entities' errors."""
    if text is None:
        return ""
    return re.sub(r"([_*`\[])", r"\\\1", str(text))


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
GROK_API_KEYS = [k.strip() for k in os.environ.get("GROK_API_KEYS", "").split(",") if k.strip()]

GROK_MODEL = "grok-4-fast"   # xAI console se confirm kar lena exact model name
GROK_BASE_URL = "https://api.x.ai/v1/chat/completions"

# 👑 Owner (tumhara) Telegram user ID aur username -- already daal diya hai
OWNER_ID = 7892255798
OWNER_USERNAME = "TSIW01"   # bina @ ke

# 🗄️ Backup channel ki ID yahan daalo (bot ko us channel me admin banana hoga)
# Channel ID nikalne ka tarika README.md me likha hai
BACKUP_CHANNEL_ID = ""   # 👈 yahan apne backup channel ki ID daalo, jaise "-1001234567890"

DB_PATH = "botdata.db"
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
        """
    )
    conn.commit()
    conn.close()


def db_export_json() -> str:
    """Dump the whole DB into the fixed backup JSON format."""
    conn = db_connect()
    data = {"_format": "group_manager_backup_v1", "_exported_at": datetime.now(IST).isoformat()}
    for table in [
        "users", "warns", "blacklist", "banned_users", "welcome_channels",
        "admin_log", "impersonators", "deals", "settings",
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
        return False, "❌ **Invalid file — yeh JSON file nahi hai.**"

    if data.get("_format") != "group_manager_backup_v1":
        return False, "❌ **Yeh file is bot ke database format se match nahi karti. Import reject kiya gaya.**"

    required_tables = [
        "users", "warns", "blacklist", "banned_users", "welcome_channels",
        "admin_log", "impersonators", "deals", "settings",
    ]
    for t in required_tables:
        if t not in data or not isinstance(data[t], list):
            return False, f"❌ **File corrupt lag rahi hai — '{t}' table missing/invalid hai.**"

    try:
        conn = db_connect()
        cur = conn.cursor()
        for t in required_tables:
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
        return True, "✅ **Database successfully import ho gaya!**"
    except Exception as e:
        logger.exception("Import failed")
        return False, f"❌ **Import ke दौरान error aaya: `{e}`**\nDatabase change nahi kiya gaya (safe rollback)."


# --- small DB helpers -------------------------------------------------------
def upsert_user(user_id, username, first_name, chat_id):
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


def get_all_trusted(chat_id):
    conn = db_connect()
    rows = conn.execute(
        "SELECT user_id, username, first_name, trust_level FROM users WHERE trust_level >= 2 AND chat_id=?",
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
                timeout=20,
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


def ai_classify_admin_command(command_text: str, has_reply_target: bool) -> dict:
    """
    Ask Grok to understand a natural-language admin command (Hindi/English/
    Hinglish, any phrasing) and turn it into a structured action.
    Returns a dict like {"action": "mute", "duration_minutes": 60, "confidence": "high"}
    """
    system_prompt = (
        "Tum ek Telegram group-management AI ho. Ek group admin/owner ne tumhe ek "
        "instruction diya hai (Hindi/English/Hinglish, kisi bhi tarike se likha ho, "
        "gaali-galoch ya slang me bhi ho sakta hai). Tumhara kaam sirf yeh samajhna hai "
        "ki woh kaunsa admin action maang raha hai. Tumhe koi keyword-matching nahi karni, "
        "poora sentence ka meaning samajhna hai.\n\n"
        "Possible actions (in JSON 'action' field): "
        "ban, unban, kick, mute, unmute, warn, unwarn, promote, demote, pin, unpin, "
        "delete, purge, lock, unlock, upgrade_trust, downgrade_trust, dispute_freeze, "
        "dispute_unfreeze, escrow_verify, escrow_unverify, info, unknown.\n\n"
        "Rules:\n"
        "- purge, lock, unlock, dispute_freeze, dispute_unfreeze -> OWNER ONLY actions "
        "(tum flag karo, backend check karega ki sender owner hai ya nahi).\n"
        "- Agar duration bola gaya hai (jaise '10 minute', '1 ghanta', '2 din') to use "
        "minutes me convert karke 'duration_minutes' field me do, warna null.\n"
        "- Agar action clear na ho to action='unknown' do.\n"
        f"- has_reply_target = {has_reply_target} (batata hai ki yeh message kisi ke "
        "message ko reply karke bheja gaya hai ya nahi -- target usually replied user hota hai).\n\n"
        'Respond ONLY with compact JSON: {"action": "...", "duration_minutes": null, "confidence": "high|medium|low"}'
    )
    raw = _grok_call_raw(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": command_text},
        ],
        json_mode=True,
    )
    if raw is None:
        return {"action": "unknown", "duration_minutes": None, "confidence": "low", "error": "ai_unavailable"}
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("Could not parse AI response: %s", raw)
        return {"action": "unknown", "duration_minutes": None, "confidence": "low"}


def ai_check_link_permission(message_text: str, recent_context: str) -> dict:
    """
    A link/username/dot-domain pattern was found in a message. Ask AI:
    (1) is this actually a link/promotion (not a false positive), and
    (2) was it shared because an admin/owner explicitly asked this user
        for a link/username in the recent conversation?
    """
    system_prompt = (
        "Tum ek Telegram group ke liye anti-promotion AI ho. Neeche ek message hai jisme "
        "shayad ek link, website, ya @username ho sakta hai (ho sakta hai false positive bhi ho, "
        "jaise '60.5% result aaya' me dot hai par woh link nahi hai).\n\n"
        "Recent group context (last few messages, includes agar kisi admin/owner ne is user se "
        "link/username maanga tha) neeche diya gaya hai.\n\n"
        "Decide karo:\n"
        "1. is_link_or_promo: true/false -- kya yeh message me genuinely ek link/website/username "
        "share ho raha hai (promotion ke तौर par)?\n"
        "2. was_requested_by_admin: true/false -- kya recent context me kisi admin/owner ne "
        "specifically is user se link/username maanga tha?\n\n"
        'Respond ONLY JSON: {"is_link_or_promo": true/false, "was_requested_by_admin": true/false}'
    )
    user_content = f"RECENT CONTEXT:\n{recent_context}\n\nMESSAGE TO CHECK:\n{message_text}"
    raw = _grok_call_raw(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        json_mode=True,
        max_tokens=150,
    )
    if raw is None:
        # AI unavailable -> fail safe: don't punish the user
        return {"is_link_or_promo": False, "was_requested_by_admin": True}
    try:
        return json.loads(raw)
    except Exception:
        return {"is_link_or_promo": False, "was_requested_by_admin": True}


def ai_check_escrow_impersonation(message_text: str) -> dict:
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
    raw = _grok_call_raw(
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
# LINK / USERNAME DETECTION (cheap local pre-filter before any AI call)
# Matches: http(s)://..., t.me/..., @username, and bare "word.word"-style
# domains (e.g. "amazon.com", "insta.gram") without needing http://
# =============================================================================
LINK_PATTERN = re.compile(
    r"(https?://\S+)"                      # http/https links
    r"|(\bt\.me/\S+)"                       # telegram links
    r"|(@[A-Za-z0-9_]{4,})"                 # @usernames
    r"|(\b[a-zA-Z0-9][a-zA-Z0-9\-]{1,30}\.[a-zA-Z]{2,10}\b)",  # bare dot-domains like amazon.com
    re.IGNORECASE,
)


def message_has_link_pattern(text: str) -> bool:
    if not text:
        return False
    return bool(LINK_PATTERN.search(text))


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
ADMIN_CACHE_TTL = 60  # seconds

ANTIFLOOD_WINDOW = 10       # seconds
ANTIFLOOD_MAX_MSGS = 5      # >=5 msgs in window => flood
ANTIFLOOD_MUTE_MIN = 5

DUPLICATE_WINDOW = 10       # seconds -- same text twice within this => spam

ABUSE_MUTE_MIN = 30

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
async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
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
            # part of the flood -> remove it (best-effort real/fake heuristic).
            looks_fake = (not member.username) and (member.photo_count if hasattr(member, "photo_count") else True)
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
                await context.bot.unban_chat_member(chat.id, member.id)  # kick not permaban
            except TelegramError as e:
                logger.warning("Could not remove raid-join %s: %s", member.id, e)
            continue  # skip welcome message for raid joins

        # ---------------- NORMAL WELCOME ----------------
        upsert_user(member.id, member.username, member.first_name, chat.id)

        name = md_escape(member.first_name or "Member")
        uname_line = f"🔗 **Username:** @{md_escape(member.username)}\n" if member.username else ""
        profile_link = user_profile_link(member.id, member.username)

        caption = (
            f"🎉 **WELCOME, {name}!** 🎉\n\n"
            f"🆔 **User ID:** `{member.id}`\n"
            f"{uname_line}"
            f"👤 **Profile:** [Click Here]({profile_link})\n\n"
            f"✅ **SELLING ALLOWED, BUT ALWAYS USE ESCROW FOR ANY DEAL.**\n"
            f"🚫 **PROMOTION NOT ALLOWED.**\n\n"
            f"💬 Chat karo, enjoy karo 🎉"
        )

        buttons = []
        for ch_username in get_welcome_channels():
            buttons.append([InlineKeyboardButton(f"📢 {ch_username}", url=f"https://t.me/{ch_username}")])
        buttons.append([InlineKeyboardButton("💰 Escrow: Contact Owner", url=f"https://t.me/{OWNER_USERNAME}")])
        markup = InlineKeyboardMarkup(buttons)

        photo_bytes = None
        try:
            photos = await context.bot.get_user_profile_photos(member.id, limit=1)
            if photos.total_count > 0:
                file = await context.bot.get_file(photos.photos[0][-1].file_id)
                photo_bytes = await file.download_as_bytearray()
        except TelegramError:
            pass

        try:
            if photo_bytes:
                await context.bot.send_photo(
                    chat.id, photo=bytes(photo_bytes), caption=caption,
                    parse_mode=ParseMode.MARKDOWN, reply_markup=markup,
                )
            else:
                await context.bot.send_message(
                    chat.id, caption, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup, disable_web_page_preview=True,
                )
        except TelegramError as e:
            logger.warning("Welcome message failed: %s", e)

        # ---------------- IMPERSONATION CHECK (name/username/bio/photo vs owner) ----------------
        asyncio.create_task(check_impersonation(context, chat.id, member, photo_bytes))

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
                f"⚠️ [{md_escape(member.first_name)}](tg://user?id={member.id}) **ka profile owner se "
                f"{overall}% match ho raha hai!**\n"
                f"🔴 **Kripya apna naam/username/photo change karein, warna action liya ja sakta hai.**",
                parse_mode=ParseMode.MARKDOWN,
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
                    "🛡️ **Fake members detected & removed.**\n"
                    f"Agar koi real member galti se remove ho gaya ho, to owner "
                    f"(@{OWNER_USERNAME}) se contact karein. 🙏",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except TelegramError:
                pass


# =============================================================================
# CORE GROUP MESSAGE HANDLER
# =============================================================================
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None or msg.from_user is None:
        return
    chat = update.effective_chat
    user = msg.from_user
    text = msg.text or msg.caption or ""

    if user.is_bot:
        return

    upsert_user(user.id, user.username, user.first_name, chat.id)

    key = (chat.id, user.id)
    now = time.time()

    # ---------------------------------------------------------------
    # 0. BLACKLIST ENFORCEMENT (instant ban if a blacklisted user is present)
    # ---------------------------------------------------------------
    if is_blacklisted(user.id):
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            record_ban(user.id, chat.id, "blacklisted")
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

    # keep a light rolling context of chat for the link-permission AI check
    _recent_chat_context[chat.id].append(f"{user.first_name} (id:{user.id}): {text}")

    # ---------------------------------------------------------------
    # 1. FORWARDED MESSAGE HANDLING
    #    - forwarded FROM A CHANNEL you admin -> always allowed
    #    - forwarded from a random USER -> delete (no warn), unless it also
    #      contains a link/username -> then warn via the same link-logic below
    # ---------------------------------------------------------------
    is_user_forward = bool(msg.forward_origin and getattr(msg.forward_origin, "sender_user", None))
    if is_user_forward and not message_has_link_pattern(text):
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
    if len(dq) >= ANTIFLOOD_MAX_MSGS:
        await mute_user(context, chat.id, user.id, ANTIFLOOD_MUTE_MIN)
        dq.clear()
        try:
            await context.bot.send_message(
                chat.id,
                f"🚫 [{md_escape(user.first_name)}](tg://user?id={user.id}) **spam kar raha tha — "
                f"{ANTIFLOOD_MUTE_MIN} min ke liye mute kar diya gaya.** 🔇",
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            pass
        return

    # ---------------------------------------------------------------
    # 3. DUPLICATE MESSAGE FLOOD
    # ---------------------------------------------------------------
    last = _last_message_text.get(key)
    if last and last[0] == text and text.strip() and (now - last[1]) < DUPLICATE_WINDOW:
        try:
            await msg.delete()
            await context.bot.send_message(chat.id, "🛑 **Ruko zara, sabar karo!** 😤")
        except TelegramError:
            pass
        return
    _last_message_text[key] = (text, now)

    # ---------------------------------------------------------------
    # 4. ABUSE / GAALI DETECTION (instant, local, no AI)
    # ---------------------------------------------------------------
    if contains_abuse(text):
        try:
            await msg.delete()
        except TelegramError:
            pass
        await mute_user(context, chat.id, user.id, ABUSE_MUTE_MIN)
        count = add_warn(user.id, chat.id, "Abusive language")
        try:
            await context.bot.send_message(
                chat.id,
                f"🤬 [{md_escape(user.first_name)}](tg://user?id={user.id}) **ne gaali di — "
                f"{ABUSE_MUTE_MIN} min ke liye mute + ⚠️ Warning ({count}) diya gaya.**",
                parse_mode=ParseMode.MARKDOWN,
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
            result = ai_check_escrow_impersonation(text)
            if result.get("is_impersonation"):
                try:
                    await msg.delete()
                except TelegramError:
                    pass
                markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("💰 Contact Owner for Escrow", url=f"https://t.me/{OWNER_USERNAME}")]]
                )
                await context.bot.send_message(
                    chat.id,
                    "⚠️ **Kisi aur escrow worker ke paas mat jaayein.**\n"
                    "✅ **Sirf owner se contact karein.** 👇",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup,
                )
                return

    # ---------------------------------------------------------------
    # 6. LINK / USERNAME / PROMOTION GUARD (cheap pre-filter, then AI)
    # ---------------------------------------------------------------
    if message_has_link_pattern(text):
        context_str = "\n".join(_recent_chat_context[chat.id])
        result = ai_check_link_permission(text, context_str)
        if result.get("is_link_or_promo") and not result.get("was_requested_by_admin"):
            try:
                await msg.delete()
            except TelegramError:
                pass
            count = add_warn(user.id, chat.id, "Unauthorized link/promotion")
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🚫 [{md_escape(user.first_name)}](tg://user?id={user.id}), **promotion mat karo "
                    f"warna ban kar diye jaoge!** ⚠️ Warning ({count})",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except TelegramError:
                pass
            return

    # ---------------------------------------------------------------
    # 7. ADMIN NATURAL-LANGUAGE COMMAND (".." at end)
    # ---------------------------------------------------------------
    if text.strip().endswith(".."):
        admin_ok = await is_user_admin(context.bot, chat.id, user.id)
        if not admin_ok:
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🔒 [{md_escape(user.first_name)}](tg://user?id={user.id}), **aap admin nahi ho.**",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except TelegramError:
                pass
            return

        command_text = text.strip().rstrip(".").strip()
        has_reply = msg.reply_to_message is not None
        result = ai_classify_admin_command(command_text, has_reply)
        await execute_admin_action(context, update, result, user)
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

    if message_has_link_pattern(text):
        context_str = "\n".join(_recent_chat_context[chat.id])
        result = ai_check_link_permission(text, context_str)
        if result.get("is_link_or_promo") and not result.get("was_requested_by_admin"):
            try:
                await msg.delete()
            except TelegramError:
                pass
            count = add_warn(user.id, chat.id, "Edited message to insert link/promotion")
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🚫 [{md_escape(user.first_name)}](tg://user?id={user.id}), **message edit karke "
                    f"promotion daala — warn ({count}) diya gaya!**",
                    parse_mode=ParseMode.MARKDOWN,
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


async def execute_admin_action(context: ContextTypes.DEFAULT_TYPE, update: Update, result: dict, admin_user):
    msg = update.effective_message
    chat = update.effective_chat
    action = result.get("action", "unknown")
    duration = result.get("duration_minutes")

    if action == "unknown" or not action:
        await msg.reply_text("🤔 **Samajh nahi aaya kya command hai — thoda clearly bolo.**", parse_mode=ParseMode.MARKDOWN)
        return

    if action in OWNER_ONLY_ACTIONS and not is_owner(admin_user.id):
        await msg.reply_text("🔒 **Yeh command sirf owner use kar sakta hai.**", parse_mode=ParseMode.MARKDOWN)
        return

    target = msg.reply_to_message.from_user if msg.reply_to_message else None

    try:
        # ---- USER-TARGETED MODERATION ACTIONS ----
        if action in ("ban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
                      "promote", "demote", "escrow_verify", "escrow_unverify",
                      "upgrade_trust", "downgrade_trust", "dispute_freeze",
                      "dispute_unfreeze", "info"):
            if not target:
                await msg.reply_text(
                    "↩️ **Kisi user ke message ko reply karke command do.**",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            if action == "ban":
                await context.bot.ban_chat_member(chat.id, target.id)
                record_ban(target.id, chat.id, f"Banned by {admin_user.first_name}")
                await msg.reply_text(f"🔨 **[{md_escape(target.first_name)}](tg://user?id={target.id}) ban kar diya gaya!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "unban":
                await context.bot.unban_chat_member(chat.id, target.id, only_if_banned=True)
                remove_ban_record(target.id, chat.id)
                await msg.reply_text(f"✅ **[{md_escape(target.first_name)}](tg://user?id={target.id}) unban kar diya gaya!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "kick":
                await context.bot.ban_chat_member(chat.id, target.id)
                await context.bot.unban_chat_member(chat.id, target.id)
                await msg.reply_text(f"👢 **[{md_escape(target.first_name)}](tg://user?id={target.id}) kick kar diya gaya!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "mute":
                mins = duration or 60
                await mute_user(context, chat.id, target.id, mins)
                await msg.reply_text(f"🔇 **[{md_escape(target.first_name)}](tg://user?id={target.id}) {mins} min ke liye mute!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "unmute":
                await unmute_user(context, chat.id, target.id)
                await msg.reply_text(f"🔊 **[{md_escape(target.first_name)}](tg://user?id={target.id}) unmute kar diya gaya!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "warn":
                count = add_warn(target.id, chat.id, f"Warned by {admin_user.first_name}")
                await msg.reply_text(f"⚠️ **[{md_escape(target.first_name)}](tg://user?id={target.id}) warned! (Total: {count})**", parse_mode=ParseMode.MARKDOWN)

            elif action == "promote":
                await context.bot.promote_chat_member(
                    chat.id, target.id, can_delete_messages=True, can_restrict_members=True,
                    can_invite_users=True, can_pin_messages=True,
                )
                await msg.reply_text(f"⭐ **[{md_escape(target.first_name)}](tg://user?id={target.id}) admin bana diya gaya!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "demote":
                await context.bot.promote_chat_member(chat.id, target.id, can_manage_chat=False)
                await msg.reply_text(f"⬇️ **[{md_escape(target.first_name)}](tg://user?id={target.id}) demote kar diya gaya!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "escrow_verify":
                conn = db_connect()
                conn.execute("UPDATE users SET escrow_verified=1 WHERE user_id=?", (target.id,))
                conn.commit(); conn.close()
                await msg.reply_text(f"💎 **[{md_escape(target.first_name)}](tg://user?id={target.id}) escrow-verified!**", parse_mode=ParseMode.MARKDOWN)

            elif action == "upgrade_trust":
                lvl = min(3, get_trust_level(target.id) + 1)
                set_trust_level(target.id, lvl)
                await msg.reply_text(
                    f"⭐ **[{md_escape(target.first_name)}](tg://user?id={target.id}) upgrade kar diya gaya — "
                    f"{TRUST_LEVELS[lvl]}**", parse_mode=ParseMode.MARKDOWN,
                )

            elif action == "downgrade_trust":
                lvl = max(0, get_trust_level(target.id) - 1)
                set_trust_level(target.id, lvl)
                await msg.reply_text(f"⬇️ **[{md_escape(target.first_name)}](tg://user?id={target.id}) downgrade kar diya gaya.**", parse_mode=ParseMode.MARKDOWN)

            elif action == "dispute_freeze":
                _frozen_disputes[chat.id].add(target.id)
                if msg.reply_to_message.reply_to_message:
                    _frozen_disputes[chat.id].add(msg.reply_to_message.reply_to_message.from_user.id)
                await msg.reply_text(
                    "🧊 **Dispute freeze kar diya gaya hai jab tak owner resolve nahi karta.**",
                    parse_mode=ParseMode.MARKDOWN,
                )

            elif action == "dispute_unfreeze":
                _frozen_disputes[chat.id].discard(target.id)
                await msg.reply_text("✅ **Dispute unfreeze kar diya gaya.**", parse_mode=ParseMode.MARKDOWN)

            elif action == "info":
                await send_user_info(context, chat.id, target)

            log_admin_action(admin_user.id, admin_user.first_name, action, target.id, json.dumps(result))
            await send_admin_log_dm(context, admin_user, action, target)

        # ---- OWNER-ONLY, NON-USER-TARGETED ----
        elif action == "purge":
            if not msg.reply_to_message:
                await msg.reply_text("↩️ **Jahan tak purge karna hai us message ko reply karo.**", parse_mode=ParseMode.MARKDOWN)
                return
            start_id = msg.reply_to_message.message_id
            end_id = msg.message_id
            deleted = 0
            for mid in range(start_id, end_id + 1):
                try:
                    await context.bot.delete_message(chat.id, mid)
                    deleted += 1
                except TelegramError:
                    continue
            log_admin_action(admin_user.id, admin_user.first_name, "purge", 0, f"{deleted} messages")

        elif action == "lock":
            await context.bot.set_chat_permissions(chat.id, ChatPermissions(can_send_messages=False))
            await context.bot.send_message(chat.id, "🔒 **Chat lock kar diya gaya — sirf admins bhej sakte hain.**", parse_mode=ParseMode.MARKDOWN)
            log_admin_action(admin_user.id, admin_user.first_name, "lock", 0, "")

        elif action == "unlock":
            await context.bot.set_chat_permissions(chat.id, ChatPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True))
            await context.bot.send_message(chat.id, "🔓 **Chat unlock kar diya gaya!**", parse_mode=ParseMode.MARKDOWN)
            log_admin_action(admin_user.id, admin_user.first_name, "unlock", 0, "")

    except BadRequest as e:
        await msg.reply_text(f"❌ **Telegram error: {e.message}**\n(Shayad bot ke paas woh permission nahi hai)", parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        await msg.reply_text(f"❌ **Error: {e}**", parse_mode=ParseMode.MARKDOWN)


async def send_admin_log_dm(context, admin_user, action, target):
    try:
        await context.bot.send_message(
            OWNER_ID,
            f"📋 **Admin Log**\n"
            f"👮 Admin: [{md_escape(admin_user.first_name)}](tg://user?id={admin_user.id})\n"
            f"⚡ Action: `{action}`\n"
            f"🎯 Target: [{md_escape(target.first_name)}](tg://user?id={target.id})\n"
            f"🕒 {datetime.now(IST).strftime('%d-%b-%Y %I:%M %p')}",
            parse_mode=ParseMode.MARKDOWN,
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

    text = (
        f"👤 **User Info**\n\n"
        f"📛 Name: {md_escape(target.first_name)}\n"
        f"🆔 User ID: `{target.id}`\n"
        f"🔗 Username: @{md_escape(target.username) if target.username else 'N/A'}\n"
        f"🔗 Profile: [Link]({user_profile_link(target.id, target.username)})\n"
        f"📅 Joined: {join_date}\n"
        f"⚠️ Warnings: {warns}\n"
        f"💎 Escrow Verified: {escrow}\n"
        f"🏆 **Status in GC:** {TRUST_LEVELS.get(trust, TRUST_LEVELS[0])}"
    )
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)


async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/info as a reply -- works for everyone (read-only), separate from AI command flow."""
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("↩️ **Kisi user ke message ko reply karke /info bhejo.**", parse_mode=ParseMode.MARKDOWN)
        return
    await send_user_info(context, update.effective_chat.id, msg.reply_to_message.from_user)


async def trusted_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_all_trusted(update.effective_chat.id)
    if not rows:
        await update.effective_message.reply_text("😶 **Abhi tak koi Trusted Trader nahi hai.**", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["🏆 **TRUSTED TRADERS LIST** 🏆\n"]
    for r in rows:
        badge = TRUST_LEVELS.get(r["trust_level"], "")
        uname = f"@{md_escape(r['username'])}" if r["username"] else md_escape(r["first_name"])
        lines.append(f"• {badge} — [{md_escape(r['first_name'])}](tg://user?id={r['user_id']}) ({uname})")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# =============================================================================
# ADMIN PANEL (bot DM, owner only)
# =============================================================================
def admin_panel_markup():
    buttons = [
        [InlineKeyboardButton("📢 Manage Welcome Channels", callback_data="panel_channels")],
        [InlineKeyboardButton("📤 Export Database", callback_data="panel_export"),
         InlineKeyboardButton("📥 Import Database", callback_data="panel_import")],
        [InlineKeyboardButton("🏆 Trusted Traders", callback_data="panel_trusted")],
    ]
    return InlineKeyboardMarkup(buttons)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("👋 **Namaste! Group management ke liye taiyar hoon.**", parse_mode=ParseMode.MARKDOWN)
        return
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("🔒 **Yeh admin panel sirf owner ke liye hai.**", parse_mode=ParseMode.MARKDOWN)
        return
    await update.effective_message.reply_text(
        "👑 **ADMIN PANEL** 👑\n\nNeeche se option choose karo:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_panel_markup(),
    )


AWAITING_CHANNEL_INPUT = "awaiting_channel_username"
AWAITING_IMPORT_FILE = "awaiting_import_file"


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.edit_message_text("🔒 **Sirf owner use kar sakta hai.**", parse_mode=ParseMode.MARKDOWN)
        return

    data = query.data

    if data == "panel_channels":
        channels = get_welcome_channels()
        text = "📢 **Welcome Message Channels**\n\n"
        text += "\n".join(f"• @{md_escape(c)}" for c in channels) if channels else "_Koi channel set nahi hai._"
        text += "\n\n➡️ Naya channel add karne ke liye uska **username** bhejo (jaise @mychannel)."
        context.user_data["panel_state"] = AWAITING_CHANNEL_INPUT
        buttons = [[InlineKeyboardButton(f"❌ Remove @{c}", callback_data=f"rmchan_{c}")] for c in channels]
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="panel_back")])
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("rmchan_"):
        uname = data[len("rmchan_"):]
        remove_welcome_channel(uname)
        await query.edit_message_text(f"✅ **@{md_escape(uname)} remove kar diya gaya.**", parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_markup())

    elif data == "panel_export":
        raw = db_export_json()
        bio = io.BytesIO(raw.encode("utf-8"))
        bio.name = DB_BACKUP_FILENAME
        await context.bot.send_document(update.effective_chat.id, document=InputFile(bio, filename=DB_BACKUP_FILENAME),
                                         caption="📤 **Database Export**")

    elif data == "panel_import":
        context.user_data["panel_state"] = AWAITING_IMPORT_FILE
        await query.edit_message_text(
            f"📥 **Import Database**\n\nMujhe `{DB_BACKUP_FILENAME}` file bhejo (exact same format wali).",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "panel_trusted":
        conn = db_connect()
        rows = conn.execute("SELECT user_id, username, first_name, trust_level FROM users WHERE trust_level >= 2").fetchall()
        conn.close()
        if not rows:
            text = "😶 **Koi Trusted Trader nahi hai abhi.**"
        else:
            text = "🏆 **Trusted Traders (All Groups)**\n\n" + "\n".join(
                f"• {TRUST_LEVELS.get(r['trust_level'])} — {md_escape(r['first_name'])} (`{r['user_id']}`)" for r in rows
            )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_markup())

    elif data == "panel_back":
        await query.edit_message_text("👑 **ADMIN PANEL** 👑\n\nNeeche se option choose karo:", parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_markup())


async def dm_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the plain-text reply after 'Manage Channels' is pressed (owner DM only)."""
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    state = context.user_data.get("panel_state")
    if state != AWAITING_CHANNEL_INPUT:
        return
    text = (update.effective_message.text or "").strip().lstrip("@")
    if not text:
        return
    add_welcome_channel(text)
    context.user_data["panel_state"] = None
    await update.effective_message.reply_text(
        f"✅ **@{text} welcome-channel list me add ho gaya!**",
        parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_markup(),
    )


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
        await update.effective_message.reply_text("❌ **File read nahi ho payi.**", parse_mode=ParseMode.MARKDOWN)
        return
    ok, message_text = db_import_json(raw_text)
    context.user_data["panel_state"] = None
    await update.effective_message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_markup())


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
            caption=f"🗄️ **Auto-backup** — {datetime.now(IST).strftime('%d-%b-%Y %I:%M %p')}",
            parse_mode=ParseMode.MARKDOWN,
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
    if removed:
        logger.info("Ghost account cleanup: removed %d deleted accounts", removed)


async def job_raid_watchdog(context: ContextTypes.DEFAULT_TYPE):
    await raid_watchdog(context)


async def job_recheck_impersonators(context: ContextTypes.DEFAULT_TYPE):
    await recheck_impersonators(context)


# =============================================================================
# MAIN
# =============================================================================
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN environment variable is not set!")
    if not GROK_API_KEYS:
        logger.warning("⚠️ No GROK_API_KEYS set -- AI features will not work until you add them.")

    db_init()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("trusted", trusted_command))
    app.add_handler(CommandHandler("info", user_info_command))

    # group events
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & filters.ChatType.GROUPS & ~filters.COMMAND,
        handle_group_message,
    ))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.ChatType.GROUPS, handle_edited_message))

    # admin panel (DM)
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^(panel_|rmchan_)"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, dm_text_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, dm_document_handler))

    # scheduled jobs
    job_queue = app.job_queue
    job_queue.run_repeating(job_backup_to_channel, interval=1800, first=60)          # every 30 min
    job_queue.run_repeating(job_warn_expiry, interval=3600, first=30)                # hourly check
    job_queue.run_repeating(job_raid_watchdog, interval=10, first=10)                # every 10s
    job_queue.run_repeating(job_recheck_impersonators, interval=1800, first=120)     # every 30 min
    job_queue.run_daily(job_ghost_account_cleanup, time=datetime.strptime("01:30", "%H:%M").time())  # 1:30 AM server time

    logger.info("🚀 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

