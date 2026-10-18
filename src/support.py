"""Problem reports, citizen <-> admin messages and admin notifications (no Streamlit here, so it is testable).

- A citizen can report a problem with a land (boundary or area mismatch, record mismatch, encroachment, other).
- Every citizen has ONE message thread with the support team; admins reply in it. Messages can be linked to a report.
- Admins send notifications to one user or to everyone (broadcast). Read state is kept per user.
Every text field is checked for personal data (phone, NID, e-mail) and refused if it looks like it."""
import secrets

from src import vdb
from src.privacy import personal_data_reason

REPORT_CATEGORIES = {
    "boundary": "Boundary or area does not match",
    "record": "Record (dag / khatian / deed) does not match",
    "encroachment": "Encroachment or someone else is using the land",
    "location": "Map location (pin or outline) is wrong",
    "other": "Something else",
}
REPORT_STATUSES = ("open", "in_review", "resolved", "rejected")
LEVELS = ("info", "warning", "important")
MAX_TEXT = 2000


class SupportError(Exception):
    pass


def _clean(text, field, max_len=MAX_TEXT, min_len=1) -> str:
    t = str(text or "").strip()
    if len(t) < min_len:
        raise SupportError(f"{field} is empty." if min_len == 1 else f"{field} must be at least {min_len} characters.")
    if len(t) > max_len:
        raise SupportError(f"{field} is too long (max {max_len} characters).")
    why = personal_data_reason(t)
    if why:
        raise SupportError(f"{field} {why}. Please remove personal data (phone, NID, e-mail) and try again.")
    return t


# ---------------------------------------------------------------- problem reports
def create_report(con, user, category, description, parcel_id=None, lat=None, lon=None) -> str:
    if category not in REPORT_CATEGORIES:
        raise SupportError("Choose a problem category.")
    desc = _clean(description, "Description", min_len=10)
    if parcel_id and not vdb.get_parcel(con, parcel_id):
        raise SupportError("Unknown parcel.")
    for v, lo, hi in ((lat, -90, 90), (lon, -180, 180)):
        if v is not None and not (lo <= float(v) <= hi):
            raise SupportError("The location is not valid.")
    rid = "RPT-" + secrets.token_hex(3).upper()
    now = vdb.utcnow()
    con.execute("INSERT INTO problem_reports(report_id,user_id,parcel_id,category,description,lat,lon,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, user["user_id"], parcel_id, category, desc, lat, lon, "open", now, now))
    con.execute("INSERT INTO messages(thread_user_id,sender_id,sender_role,report_id,body,created_at,read_by_user,read_by_admin) VALUES (?,?,?,?,?,?,1,0)",
                (user["user_id"], user["user_id"], "user", rid, f"[Problem report {rid}: {REPORT_CATEGORIES[category]}] {desc}", now))
    con.commit()
    vdb.audit(con, user["username"], user["role"], "report_create", rid, {"category": category, "parcel_id": parcel_id})
    return rid


def list_reports(con, user_id=None, status=None):
    q = ("SELECT r.*, u.username FROM problem_reports r JOIN users u ON u.user_id = r.user_id WHERE 1=1"
         + (" AND r.user_id = ?" if user_id is not None else "") + (" AND r.status = ?" if status else "") + " ORDER BY r.created_at DESC")
    args = [a for a in (user_id, status) if a is not None]
    return [dict(r) for r in con.execute(q, args)]


def set_report_status(con, admin, report_id, status, note=""):
    if status not in REPORT_STATUSES:
        raise SupportError("Unknown status.")
    r = con.execute("SELECT * FROM problem_reports WHERE report_id = ?", (report_id,)).fetchone()
    if not r:
        raise SupportError("No such report.")
    old = r["status"]
    con.execute("UPDATE problem_reports SET status = ?, updated_at = ? WHERE report_id = ?", (status, vdb.utcnow(), report_id))
    con.commit()
    text = f"Your problem report {report_id} is now: {status.replace('_', ' ')}."
    if note.strip():
        text += " " + _clean(note, "Note", max_len=500)
    send_message(con, admin, r["user_id"], text, report_id=report_id)
    vdb.audit(con, admin["username"], "admin", "report_status", report_id, {"from": old, "to": status})


# ---------------------------------------------------------------- messages
def send_message(con, sender, thread_user_id, body, report_id=None) -> int:
    """sender is the signed-in user dict. A citizen can only write in their own thread."""
    text = _clean(body, "Message")
    if sender["role"] == "user" and sender["user_id"] != thread_user_id:
        raise SupportError("You can only write in your own conversation.")
    if not con.execute("SELECT 1 FROM users WHERE user_id = ? AND role = 'user'", (thread_user_id,)).fetchone():
        raise SupportError("No such citizen account.")
    is_admin = sender["role"] == "admin"
    cur = con.execute("INSERT INTO messages(thread_user_id,sender_id,sender_role,report_id,body,created_at,read_by_user,read_by_admin) VALUES (?,?,?,?,?,?,?,?)",
                      (thread_user_id, sender["user_id"], sender["role"], report_id, text, vdb.utcnow(), int(not is_admin), int(is_admin)))
    con.commit()
    if is_admin:
        vdb.audit(con, sender["username"], "admin", "message_reply", str(thread_user_id), {"report_id": report_id})
    return cur.lastrowid


def thread(con, thread_user_id, reader_role=None):
    """All messages of one citizen's thread (oldest first). If reader_role is given, they are marked read for that side."""
    rows = [dict(r) for r in con.execute("SELECT m.*, u.username AS sender_name FROM messages m JOIN users u ON u.user_id = m.sender_id "
                                         "WHERE m.thread_user_id = ? ORDER BY m.message_id", (thread_user_id,))]
    if reader_role == "user":
        con.execute("UPDATE messages SET read_by_user = 1 WHERE thread_user_id = ?", (thread_user_id,))
        con.commit()
    elif reader_role == "admin":
        con.execute("UPDATE messages SET read_by_admin = 1 WHERE thread_user_id = ?", (thread_user_id,))
        con.commit()
    return rows


def threads_for_admin(con):
    """One row per citizen with messages: username, last message time, number unread by admins."""
    return [dict(r) for r in con.execute(
        "SELECT m.thread_user_id, u.username, MAX(m.created_at) AS last_at, COUNT(*) AS n, SUM(CASE WHEN m.read_by_admin = 0 THEN 1 ELSE 0 END) AS unread "
        "FROM messages m JOIN users u ON u.user_id = m.thread_user_id GROUP BY m.thread_user_id ORDER BY unread DESC, last_at DESC")]


def unread_messages(con, user):
    if user["role"] == "admin":
        return con.execute("SELECT COUNT(*) FROM messages WHERE read_by_admin = 0").fetchone()[0]
    return con.execute("SELECT COUNT(*) FROM messages WHERE thread_user_id = ? AND read_by_user = 0", (user["user_id"],)).fetchone()[0]


# ---------------------------------------------------------------- notifications
def notify(con, admin, title, body, recipient_id=None, level="info") -> int:
    """recipient_id None = every user (system-wide)."""
    if level not in LEVELS:
        raise SupportError("Unknown level.")
    t, b = _clean(title, "Title", max_len=120), _clean(body, "Message")
    if recipient_id is not None and not con.execute("SELECT 1 FROM users WHERE user_id = ?", (recipient_id,)).fetchone():
        raise SupportError("No such user.")
    cur = con.execute("INSERT INTO notifications(recipient_id,title,body,level,sender,created_at) VALUES (?,?,?,?,?,?)",
                      (recipient_id, t, b, level, admin["username"], vdb.utcnow()))
    con.commit()
    vdb.audit(con, admin["username"], "admin", "notify_broadcast" if recipient_id is None else "notify_user",
              "all" if recipient_id is None else str(recipient_id), {"title": t, "level": level})
    return cur.lastrowid


def notifications_for(con, user_id):
    return [dict(r) for r in con.execute(
        "SELECT n.*, CASE WHEN r.user_id IS NULL THEN 0 ELSE 1 END AS is_read FROM notifications n "
        "LEFT JOIN notification_reads r ON r.notification_id = n.notification_id AND r.user_id = ? "
        "WHERE n.recipient_id IS NULL OR n.recipient_id = ? ORDER BY n.notification_id DESC", (user_id, user_id))]


def mark_notifications_read(con, user_id):
    con.execute("INSERT OR IGNORE INTO notification_reads(notification_id,user_id,read_at) SELECT notification_id, ?, ? FROM notifications "
                "WHERE recipient_id IS NULL OR recipient_id = ?", (user_id, vdb.utcnow(), user_id))
    con.commit()


def unread_notifications(con, user_id) -> int:
    return sum(1 for n in notifications_for(con, user_id) if not n["is_read"])


def sent_notifications(con, limit=200):
    return [dict(r) for r in con.execute("SELECT n.*, u.username AS recipient FROM notifications n LEFT JOIN users u ON u.user_id = n.recipient_id "
                                         "ORDER BY n.notification_id DESC LIMIT ?", (limit,))]
