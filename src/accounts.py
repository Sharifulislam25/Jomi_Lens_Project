"""Accounts and sign-in for JomiLens Verify (no Streamlit here, so it is testable).

Two separate doors: citizens sign in through Citizen Login (and may create an account with a username and a password only:
no phone, NID or e-mail is ever asked for); administrators sign in through the Admin Portal. Admin accounts cannot be
self-registered: they come from the seed or are created by another admin.

Passwords are hashed with scrypt (Python standard library) and a random salt per user. After 5 failed attempts for one
username within 15 minutes, that username is locked for 15 minutes. Failed and successful sign-ins are written to the audit log."""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from src.privacy import personal_data_reason

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,29}$")
MIN_PASSWORD = 8
MIN_ADMIN_PASSWORD = 10
LOCK_AFTER, LOCK_MINUTES = 5, 15
SESSION_HOURS = {"user": 8, "admin": 2}
DEMO_ACCOUNTS = [("admin", "JomiAdmin#2026", "admin", "Demo administrator"), ("citizen", "JomiCitizen#2026", "user", "Demo citizen")]
_N, _R, _P = 2 ** 14, 8, 1


class AuthError(Exception):
    """A sign-in or account problem described in plain language (safe to show)."""


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(dk)))
        return hmac.compare_digest(got, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("not-a-real-password")      # keeps "no such user" as slow as "wrong password"


def clean_username(username) -> str:
    return str(username or "").strip().lower()[:60]


def validate_new_username(username: str) -> str:
    u = clean_username(username)
    if not USERNAME_RE.match(u):
        raise AuthError("Username: 3-30 characters, start with a letter; letters, digits, dot, dash or underscore.")
    why = personal_data_reason(u)
    if why:
        raise AuthError(f"That username {why}. Please do not use personal data; choose a nickname instead.")
    return u


def validate_new_password(password: str, minimum: int = MIN_PASSWORD):
    if len(password or "") < minimum:
        raise AuthError(f"Password must be at least {minimum} characters.")
    if len(password) > 200:
        raise AuthError("Password is too long.")


def get_user(con, username):
    r = con.execute("SELECT * FROM users WHERE username = ?", (clean_username(username),)).fetchone()
    return dict(r) if r else None


def get_user_by_id(con, user_id):
    r = con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(r) if r else None


def public(u: dict) -> dict:
    return {"user_id": u["user_id"], "username": u["username"], "role": u["role"], "display_name": u.get("display_name") or ""}


def create_user(con, username, password, role="user", display_name="", created_by="self"):
    from src import vdb
    u = validate_new_username(username)
    if role not in ("user", "admin"):
        raise AuthError("Unknown role.")
    validate_new_password(password, MIN_ADMIN_PASSWORD if (role == "admin" or created_by != "self") else MIN_PASSWORD)
    dn = (display_name or "").strip()[:40]
    if personal_data_reason(dn):
        raise AuthError("The display name looks like personal data. Use a nickname.")
    if get_user(con, u):
        raise AuthError("That username is taken. Please choose another.")
    con.execute("INSERT INTO users(username,role,password_hash,display_name,active,created_at,created_by) VALUES (?,?,?,?,1,?,?)",
                (u, role, hash_password(password), dn, _iso(_now()), created_by))
    con.commit()
    vdb.audit(con, created_by, "admin" if created_by != "self" else role, "register" if created_by == "self" else "user_create", u, {"role": role})
    return public(get_user(con, u))


def locked_until(con, username):
    """When the username is locked after too many failed attempts, return the unlock time; else None."""
    since = _iso(_now() - timedelta(minutes=LOCK_MINUTES))
    rows = con.execute("SELECT ok, ts FROM login_attempts WHERE username = ? AND ts >= ? ORDER BY ts", (clean_username(username), since)).fetchall()
    fails = []
    for ok, ts in rows:
        fails = [] if ok else fails + [ts]
    if len(fails) >= LOCK_AFTER:
        first = datetime.strptime(fails[-LOCK_AFTER], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return first + timedelta(minutes=LOCK_MINUTES)
    return None


def authenticate(con, username, password, door) -> dict:
    """door = 'citizen' or 'admin'. Returns the public user dict or raises AuthError (with a message safe to show)."""
    from src import vdb
    u = clean_username(username)
    if not u or not password:
        raise AuthError("Enter a username and a password.")
    until = locked_until(con, u)
    if until:
        vdb.audit(con, u, "none", f"login_locked_{door}", u)
        raise AuthError(f"Too many failed attempts. This account is locked until {until.strftime('%H:%M')} UTC. Please try again later.")
    user = get_user(con, u)
    ok = verify_password(password, user["password_hash"] if user else _DUMMY) and bool(user) and bool(user["active"])
    con.execute("INSERT INTO login_attempts(username,door,ok,ts) VALUES (?,?,?,?)", (u, door, int(ok), _iso(_now())))
    con.commit()
    if not ok:
        vdb.audit(con, u, "none", f"login_failed_{door}", u)
        raise AuthError("Wrong username or password.")
    if door == "citizen" and user["role"] != "user":
        raise AuthError("Administrator accounts sign in through the Admin Portal.")
    if door == "admin" and user["role"] != "admin":
        raise AuthError("This is not an administrator account. Please use Citizen Login.")
    con.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (_iso(_now()), user["user_id"]))
    con.commit()
    vdb.audit(con, u, user["role"], f"login_{door}", u)
    out = public(user)
    out["must_change_password"] = bool(user["must_change_password"])
    return out


def change_password(con, user_id, current, new):
    from src import vdb
    user = get_user_by_id(con, user_id)
    if not user or not verify_password(current, user["password_hash"]):
        raise AuthError("The current password is wrong.")
    validate_new_password(new, MIN_ADMIN_PASSWORD if user["role"] == "admin" else MIN_PASSWORD)
    if new == current:
        raise AuthError("The new password must be different.")
    con.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE user_id = ?", (hash_password(new), user_id))
    con.commit()
    vdb.audit(con, user["username"], user["role"], "password_change", user["username"])


def set_active(con, admin, user_id, active: bool):
    from src import vdb
    if user_id == admin["user_id"] and not active:
        raise AuthError("You cannot disable your own account.")
    target = get_user_by_id(con, user_id)
    if not target:
        raise AuthError("No such user.")
    con.execute("UPDATE users SET active = ? WHERE user_id = ?", (int(active), user_id))
    con.commit()
    vdb.audit(con, admin["username"], "admin", "user_enable" if active else "user_disable", target["username"])


def reset_password(con, admin, user_id) -> str:
    """Admin sets a random temporary password (shown once); the user must change it at next sign-in."""
    from src import vdb
    target = get_user_by_id(con, user_id)
    if not target:
        raise AuthError("No such user.")
    temp = "Tmp-" + secrets.token_urlsafe(9)
    con.execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE user_id = ?", (hash_password(temp), user_id))
    con.commit()
    vdb.audit(con, admin["username"], "admin", "password_reset", target["username"])
    return temp


def list_users(con):
    return [dict(r) for r in con.execute("SELECT user_id, username, role, display_name, active, must_change_password, created_at, created_by, last_login_at "
                                         "FROM users ORDER BY role, username")]


def session_expired(auth: dict) -> bool:
    try:
        t = datetime.strptime(auth["login_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return True
    return _now() - t > timedelta(hours=SESSION_HOURS.get(auth.get("role"), 2))


def new_session(user: dict) -> dict:
    return {**user, "login_at": _iso(_now()), "session_id": secrets.token_hex(8)}


def seed_demo_accounts(con):
    """Demo accounts (same as the MERN version). Set JOMILENS_ADMIN_PASSWORD before the first run to choose your own admin password."""
    for username, password, role, label in DEMO_ACCOUNTS:
        if get_user(con, username):
            continue
        if role == "admin" and os.environ.get("JOMILENS_ADMIN_PASSWORD"):
            password = os.environ["JOMILENS_ADMIN_PASSWORD"]
        con.execute("INSERT INTO users(username,role,password_hash,display_name,active,created_at,created_by) VALUES (?,?,?,?,1,?,?)",
                    (username, role, hash_password(password), label, _iso(_now()), "seed"))
    con.commit()
