"""Accounts and the two sign-in doors, problem reports, messages, notifications, smart search and the admin outline editor."""
import json

import pytest

from src import accounts, parcel_admin, search, support, vdb
from src.accounts import AuthError


# ---------------------------------------------------------------- accounts
def test_demo_accounts_exist_and_passwords_are_hashed(fresh):
    rows = {r["username"]: r for r in accounts.list_users(fresh)}
    assert rows["admin"]["role"] == "admin" and rows["citizen"]["role"] == "user"
    for h in fresh.execute("SELECT password_hash FROM users"):
        assert h[0].startswith("scrypt$") and "Jomi" not in h[0]


def test_each_door_only_admits_its_own_role(fresh):
    assert accounts.authenticate(fresh, "citizen", "JomiCitizen#2026", "citizen")["role"] == "user"
    assert accounts.authenticate(fresh, "admin", "JomiAdmin#2026", "admin")["role"] == "admin"
    with pytest.raises(AuthError, match="Admin Portal"):
        accounts.authenticate(fresh, "admin", "JomiAdmin#2026", "citizen")
    with pytest.raises(AuthError, match="not an administrator"):
        accounts.authenticate(fresh, "citizen", "JomiCitizen#2026", "admin")


def test_wrong_password_and_unknown_user_give_the_same_message(fresh):
    with pytest.raises(AuthError) as a:
        accounts.authenticate(fresh, "citizen", "nope-nope", "citizen")
    with pytest.raises(AuthError) as b:
        accounts.authenticate(fresh, "ghost", "nope-nope", "citizen")
    assert str(a.value) == str(b.value) == "Wrong username or password."


def test_lockout_after_five_failures_even_with_the_right_password(fresh):
    for _ in range(accounts.LOCK_AFTER):
        with pytest.raises(AuthError):
            accounts.authenticate(fresh, "citizen", "bad-password", "citizen")
    with pytest.raises(AuthError, match="locked"):
        accounts.authenticate(fresh, "citizen", "JomiCitizen#2026", "citizen")
    acts = [r[0] for r in fresh.execute("SELECT action FROM audit_log")]
    assert acts.count("login_failed_citizen") == 5 and "login_locked_citizen" in acts


def test_registration_rules(fresh):
    u = accounts.create_user(fresh, "Rahim_demo", "longenough1")
    assert u["username"] == "rahim_demo" and u["role"] == "user"
    for bad in ("01712345678", "ab", "x@y.com", "9abc"):
        with pytest.raises(AuthError):
            accounts.create_user(fresh, bad, "longenough1")
    with pytest.raises(AuthError, match="taken"):
        accounts.create_user(fresh, "rahim_demo", "longenough1")
    with pytest.raises(AuthError, match="at least 8"):
        accounts.create_user(fresh, "short_pw", "abc")


def test_disabled_account_cannot_sign_in_and_admin_cannot_disable_self(fresh):
    admin = accounts.authenticate(fresh, "admin", "JomiAdmin#2026", "admin")
    cit = accounts.get_user(fresh, "citizen")
    accounts.set_active(fresh, admin, cit["user_id"], False)
    with pytest.raises(AuthError, match="Wrong username"):
        accounts.authenticate(fresh, "citizen", "JomiCitizen#2026", "citizen")
    with pytest.raises(AuthError, match="own account"):
        accounts.set_active(fresh, admin, admin["user_id"], False)


def test_password_reset_forces_change(fresh):
    admin = accounts.authenticate(fresh, "admin", "JomiAdmin#2026", "admin")
    cit = accounts.get_user(fresh, "citizen")
    temp = accounts.reset_password(fresh, admin, cit["user_id"])
    u = accounts.authenticate(fresh, "citizen", temp, "citizen")
    assert u["must_change_password"]
    accounts.change_password(fresh, u["user_id"], temp, "BrandNew#2026")
    assert not accounts.authenticate(fresh, "citizen", "BrandNew#2026", "citizen")["must_change_password"]
    assert "password" not in json.dumps([dict(r) for r in fresh.execute("SELECT detail_json FROM audit_log")]).replace("password_", "")


def test_session_expiry():
    s = accounts.new_session({"user_id": 1, "username": "a", "role": "admin"})
    assert not accounts.session_expired(s)
    s["login_at"] = "2020-01-01T00:00:00Z"
    assert accounts.session_expired(s) and accounts.session_expired({})


# ---------------------------------------------------------------- reports, messages, notifications
def _users(con):
    return (accounts.authenticate(con, "admin", "JomiAdmin#2026", "admin"), accounts.authenticate(con, "citizen", "JomiCitizen#2026", "citizen"))


def test_report_flow_and_messages(fresh):
    admin, cit = _users(fresh)
    rid = support.create_report(fresh, cit, "boundary", "The east side looks 3 m too wide on the map.", parcel_id="DV-011", lat=23.993, lon=90.4231)
    assert support.list_reports(fresh, user_id=cit["user_id"])[0]["report_id"] == rid
    assert support.unread_messages(fresh, admin) == 1
    support.set_report_status(fresh, admin, rid, "in_review", "We are checking the survey map.")
    assert support.list_reports(fresh, status="in_review")[0]["report_id"] == rid
    assert support.unread_messages(fresh, cit) == 1
    msgs = support.thread(fresh, cit["user_id"], reader_role="user")
    assert [m["sender_role"] for m in msgs] == ["user", "admin"] and support.unread_messages(fresh, cit) == 0
    support.send_message(fresh, cit, cit["user_id"], "Thank you")
    assert support.threads_for_admin(fresh)[0]["unread"] == 2


def test_support_refuses_personal_data_and_foreign_threads(fresh):
    admin, cit = _users(fresh)
    with pytest.raises(support.SupportError, match="phone"):
        support.send_message(fresh, cit, cit["user_id"], "call me on 01712345678")
    with pytest.raises(support.SupportError, match="own conversation"):
        support.send_message(fresh, cit, admin["user_id"], "hello")
    with pytest.raises(support.SupportError):
        support.create_report(fresh, cit, "nonsense", "long enough description")


def test_notifications_direct_and_broadcast(fresh):
    admin, cit = _users(fresh)
    other = accounts.create_user(fresh, "second_user", "longenough1")
    support.notify(fresh, admin, "Maintenance", "The map will be down on Friday night.")
    support.notify(fresh, admin, "Your report", "We fixed DV-011.", recipient_id=cit["user_id"], level="important")
    assert support.unread_notifications(fresh, cit["user_id"]) == 2
    assert support.unread_notifications(fresh, other["user_id"]) == 1
    support.mark_notifications_read(fresh, cit["user_id"])
    assert support.unread_notifications(fresh, cit["user_id"]) == 0 and support.unread_notifications(fresh, other["user_id"]) == 1


# ---------------------------------------------------------------- search
def test_partial_and_fuzzy_search(con):
    assert search.search(con, "DV-011")[0]["parcel_id"] == "DV-011"
    assert {h["parcel_id"] for h in search.search(con, "dv-01")} >= {"DV-010", "DV-011", "DV-019"}
    assert all(h.get("mouza") == "Demo Mouza 3" for h in search.search(con, "demo mouza 3") if h["field"] == "mouza")
    lms = [{"name": "Sadar Hospital Road", "lat": 23.993742, "lon": 90.42485, "kind": "road"}]
    hit = [h for h in search.search(con, "hospitl", landmarks=lms) if h["type"] == "landmark"]
    assert hit and hit[0]["kind"] == "fuzzy" and any(n["parcel_id"] == "DV-011" for n in hit[0]["near"])
    assert search.search(con, "x") == []


def test_dag_number_search_ignores_labels_but_not_digits(con):
    dag = con.execute("SELECT dag_ref, parcel_id FROM land_records WHERE dag_ref IS NOT NULL LIMIT 1").fetchone()
    digits = "".join(ch for ch in dag["dag_ref"] if ch.isdigit())
    hits = search.search(con, f"Dag No. 0{digits}")
    assert any(h["parcel_id"] == dag["parcel_id"] and h["kind"] == "number" for h in hits)
    assert search.match_score("125", "126", numeric=True) == (0, None)


# ---------------------------------------------------------------- admin outline editor
def test_outline_edit_is_validated_and_audited(fresh):
    admin, _ = _users(fresh)
    p = vdb.get_parcel(fresh, "DV-001")
    pts = vdb.parcel_points(p)
    moved = parcel_admin.shift_points(pts, 2.0, 0.0)
    parcel_admin.update_outline(fresh, admin, "DV-001", moved, "Corrected after field visit")
    assert vdb.parcel_points(vdb.get_parcel(fresh, "DV-001"))[0] == pytest.approx(moved[0])
    h = parcel_admin.outline_history(fresh, "DV-001")
    assert h[0]["action"] == "parcel_outline_edit" and json.loads(h[0]["detail_json"])["old"][0] == pytest.approx(list(pts[0]))
    with pytest.raises(parcel_admin.EditError, match="reason"):
        parcel_admin.update_outline(fresh, admin, "DV-001", pts, "")
    with pytest.raises(parcel_admin.EditError, match="Gazipur Sadar"):
        parcel_admin.update_outline(fresh, admin, "DV-001", [(90.41, 23.79), (90.411, 23.79), (90.411, 23.791)], "move to Dhaka")


def test_outline_edit_cannot_create_new_overlap(fresh):
    admin, _ = _users(fresh)
    a, b = vdb.get_parcel(fresh, "DV-001"), vdb.get_parcel(fresh, "DV-002")
    with pytest.raises(parcel_admin.EditError, match="overlap"):
        parcel_admin.update_outline(fresh, admin, "DV-001", vdb.parcel_points(b), "copy neighbour outline")
    assert vdb.parcel_points(vdb.get_parcel(fresh, "DV-001")) == vdb.parcel_points(a)


def test_existing_scenario_overlap_is_kept_but_not_grown(fresh):
    admin, _ = _users(fresh)
    pts = vdb.parcel_points(vdb.get_parcel(fresh, "DV-023"))
    parcel_admin.update_outline(fresh, admin, "DV-023", pts, "re-save unchanged")      # same overlap as before: allowed


def test_digitise_new_parcel(fresh):
    admin, _ = _users(fresh)
    lon, lat = 90.4400, 24.0200
    d = 0.0002
    pid = parcel_admin.create_parcel(fresh, admin, [(lon, lat), (lon + d, lat), (lon + d, lat + d), (lon, lat + d)], "Admin test plot", "Demo Mouza 9", 1_500_000)
    assert pid == "JL-0001" and vdb.get_parcel(fresh, pid)["boundary_type"] == "user_drawn"
    assert parcel_admin.next_parcel_id(fresh) == "JL-0002"
    parcel_admin.set_parcel_status(fresh, admin, pid, "retired", "test parcel removed")
    assert pid not in {p["parcel_id"] for p in vdb.list_parcels(fresh)}
