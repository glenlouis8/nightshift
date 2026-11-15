"""Tools the agent can call. Each takes (conn, session, args) and returns a dict for the LLM."""

from pathlib import Path

import yaml

from agent.db import normalize_phone, now_iso
from datetime import datetime

CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())


def get_pricing(conn, session, args):
    """Only source of prices. The agent must never quote a number not in here."""
    return {"prices_usd": CONFIG["pricing"]}


def get_open_slots(conn, session, args):
    """Open visit windows. Optional args['day'] = 'YYYY-MM-DD'; default = all upcoming."""
    sql = "SELECT id, day, start_hour FROM slots WHERE visit_id IS NULL"
    params = []
    if args.get("day"):
        sql += " AND day = ?"
        params.append(args["day"])
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    return {
        "open_slots": [
            {
                "slot_id": r["id"],
                "day": r["day"],
                "window": f"{r['start_hour']}:00 to {r['start_hour'] + 2}:00",
            }
            for r in rows
        ]
    }


def _find_customer_id(conn, phone):
    """Return customer id for this phone, or None."""
    row = conn.execute(
        "SELECT id FROM customers WHERE phone = ?", (normalize_phone(phone),)
    ).fetchone()
    return row["id"] if row else None


def lookup_customer(conn, session, args):
    """Find a customer by phone and list their booked visits. Hides name/address on purpose."""
    cust_id = _find_customer_id(conn, args["phone"])
    if cust_id is None:
        return {"found": False}
    session["caller_phone"] = normalize_phone(args["phone"])
    visits = conn.execute(
        "SELECT v.id, v.issue, s.day, s.start_hour FROM visits v "
        "JOIN slots s ON s.id = v.slot_id "
        "WHERE v.customer_id = ? AND v.status = 'booked'",
        (cust_id,),
    ).fetchall()
    return {"found": True, "visits": [dict(v) for v in visits]}


def book_visit(conn, session, args):
    """Write a booking. The gate in core.py has already confirmed read-back + yes."""
    slot = conn.execute(
        "SELECT * FROM slots WHERE id = ?", (args["slot_id"],)
    ).fetchone()
    if not slot or slot["visit_id"] is not None:
        return {
            "ok": False,
            "error": "That slot is not available. Offer another from get_open_slots.",
        }

    phone = normalize_phone(args["phone"])
    cust_id = _find_customer_id(conn, phone)
    if cust_id is None:

        cur = conn.execute(
            "INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)",
            (args["name"], phone, args["address"]),
        )
        cust_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO visits (customer_id, slot_id, issue, address) VALUES (?, ?, ?, ?)",
        (cust_id, slot["id"], args["issue"], args["address"]),
    )
    conn.execute(
        "UPDATE slots SET visit_id = ? WHERE id = ?", (cur.lastrowid, slot["id"])
    )
    conn.commit()
    return {
        "ok": True,
        "visit_id": cur.lastrowid,
        "day": slot["day"],
        "start_hour": slot["start_hour"],
    }


def _find_own_visit(conn, name, phone):
    """Gate #3: return this caller's booked visit only if name AND phone match, else None."""
    return conn.execute(
        "SELECT v.id AS visit_id, v.slot_id FROM visits v "
        "JOIN customers c ON c.id = v.customer_id "
        "WHERE c.phone = ? AND lower(c.name) = lower(?) AND v.status = 'booked'",
        (normalize_phone(phone), name.strip()),
    ).fetchone()


def cancel_visit(conn, session, args):
    """Cancel the caller's own booking. Gate #3 lives in _find_own_visit."""
    visit = _find_own_visit(conn, args["name"], args["phone"])
    if not visit:
        return {"ok": False, "error": "No booking found for that name and phone."}
    conn.execute(
        "UPDATE visits SET status = 'cancelled' WHERE id = ?", (visit["visit_id"],)
    )
    conn.execute("UPDATE slots SET visit_id = NULL WHERE id = ?", (visit["slot_id"],))
    conn.commit()
    return {"ok": True, "cancelled_visit_id": visit["visit_id"]}


def reschedule_visit(conn, session, args):
    """Move the caller's own booking to a new open slot."""
    visit = _find_own_visit(conn, args["name"], args["phone"])
    if not visit:
        return {"ok": False, "error": "No booking found for that name and phone."}
    new = conn.execute(
        "SELECT * FROM slots WHERE id = ?", (args["new_slot_id"],)
    ).fetchone()
    if not new or new["visit_id"] is not None:
        return {
            "ok": False,
            "error": "That slot is not available. Offer another from get_open_slots.",
        }
    conn.execute("UPDATE slots SET visit_id = NULL WHERE id = ?", (visit["slot_id"],))
    conn.execute(
        "UPDATE slots SET visit_id = ? WHERE id = ?", (visit["visit_id"], new["id"])
    )
    conn.execute(
        "UPDATE visits SET slot_id = ? WHERE id = ?", (new["id"], visit["visit_id"])
    )
    conn.commit()
    return {
        "ok": True,
        "visit_id": visit["visit_id"],
        "day": new["day"],
        "start_hour": new["start_hour"],
    }


def page_oncall(conn, session, args):
    """Simulated page: a row in `pages` + console line. No real SMS.
    If this number was already paged in the last 60 min, still page but mark it REPEAT.
    """
    callback = normalize_phone(args["callback"])  # clean phone so formats match

    # Find the most recent emergency page for this same phone number (if any)
    last = conn.execute(
        "SELECT created_at FROM pages WHERE callback = ? AND urgency = 'emergency' ORDER BY id DESC LIMIT 1",
        (callback,),
    ).fetchone()

    # Was it within the last 60 minutes?
    repeat = False
    if last:
        minutes_ago = (
            datetime.now() - datetime.fromisoformat(last["created_at"])
        ).total_seconds() / 60
        repeat = minutes_ago < 60

    summary = ("REPEAT CALL: " if repeat else "") + args[
        "summary"
    ]  # flag it so Mike knows
    conn.execute(
        "INSERT INTO pages (urgency, summary, address, callback, created_at) VALUES (?, ?, ?, ?, ?)",
        (args["urgency"], summary, args["address"], callback, now_iso()),
    )
    conn.commit()

    tech = CONFIG["oncall"]
    print(
        f"[PAGE -> {tech['tech_name']}] {args['urgency']}: {summary} @ {args['address']}"
    )

    result = {
        "ok": True,
        "tech": tech["tech_name"],
        "callback_within_minutes": tech["callback_window_minutes"],
    }
    if repeat:
        # tell the agent what to say instead of pretending it's a fresh page
        result["repeat"] = True
        result["first_paged_at"] = last["created_at"]
        result["say"] = (
            "Tell the caller the tech was already paged earlier and you sent a reminder that they called again."
        )
    return result


def log_safety_call(conn, session, args):
    """SAFETY lane: log hazard + FYI page to on-call. Never books."""
    address, callback = args.get("address", ""), normalize_phone(
        args.get("callback", "")
    )
    conn.execute(
        "INSERT INTO safety_calls (hazard, address, callback, created_at) VALUES (?, ?, ?, ?)",
        (args["hazard"], address, callback, now_iso()),
    )
    conn.execute(
        "INSERT INTO pages (urgency, summary, address, callback, created_at) VALUES ('safety_fyi', ?, ?, ?, ?)",
        (args["hazard"], address, callback, now_iso()),
    )
    session["lane"] = (
        "SAFETY"  # model flagged a hazard → lock lane so gate 2 blocks book_visit
    )
    conn.commit()
    return {"ok": True}


def transfer_to_human(conn, session, args):
    """Simulated transfer: log the reason."""
    conn.execute(
        "INSERT INTO transfers (reason, created_at) VALUES (?, ?)",
        (args["reason"], now_iso()),
    )
    conn.commit()
    return {"ok": True, "message": "Transferring now."}


def read_back(conn, session, args):
    """Agent declares it's reading details back. Next caller 'yes' unlocks ONE write."""
    session["readback_done"] = True
    session["caller_confirmed"] = False
    return {
        "ok": True,
        "next": "Read the details to the caller now, ask 'Is that correct?', then wait.",
    }
