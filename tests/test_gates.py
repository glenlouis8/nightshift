from agent.core import new_session, check_gate

from agent.db import init_db
from agent.tools import cancel_visit


def test_safety_lane_blocks_booking():
    s = new_session()
    s["lane"] = "SAFETY"
    s["caller_confirmed"] = True  # even with a yes
    assert "BLOCKED" in check_gate("book_visit", s)


def test_routine_lane_allows_booking():
    s = new_session()
    s["lane"] = "ROUTINE"
    s["caller_confirmed"] = True
    assert check_gate("book_visit", s) is None


def test_write_blocked_without_confirmation():
    s = new_session()
    s["caller_confirmed"] = False
    assert "BLOCKED" in check_gate("page_oncall", s)


def test_write_allowed_after_confirmation():
    s = new_session()
    s["caller_confirmed"] = True
    assert check_gate("page_oncall", s) is None


def test_invented_phone_blocked():
    s = new_session()
    s["caller_confirmed"] = True
    s["transcript"].append({"role": "caller", "text": "my number is 716 555 0002"})
    # model changed the last digit
    assert "BLOCKED" in check_gate("page_oncall", s, {"phone": "716-555-0000"})


def test_real_phone_allowed():
    s = new_session()
    s["caller_confirmed"] = True
    s["transcript"].append({"role": "caller", "text": "my number is 716 555 0002"})
    assert check_gate("page_oncall", s, {"phone": "716-555-0002"}) is None


def test_cannot_cancel_someone_elses_booking():
    conn = init_db(":memory:")
    s = new_session()
    # Sarah's name, but Dave's phone
    r = cancel_visit(conn, s, {"name": "Sarah Chen", "phone": "7165550199"})
    assert r["ok"] is False


def test_can_cancel_own_booking():
    conn = init_db(":memory:")
    s = new_session()
    r = cancel_visit(conn, s, {"name": "Sarah Chen", "phone": "7165550142"})
    assert r["ok"] is True
