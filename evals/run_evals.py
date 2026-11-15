"""Run the simulated-caller evals and grade each call on the final database state.

    uv run python -m evals.run_evals                  # all 40
    uv run python -m evals.run_evals --only emergency_burst_pipe safety_gas_smell
    uv run python -m evals.run_evals --category safety
"""

import argparse
import json
import re
import statistics
import time
import traceback
from datetime import date, datetime
from pathlib import Path

import yaml
from google import genai
from google.genai import types

from agent import core
from agent.db import business_days_after, init_db
from agent.tools import CONFIG
from evals.caller_sim import HANGUP, SimulatedCaller

ROOT = Path(__file__).parent
DB_PATH = str(ROOT / ".eval.db")
GREETING = "Lakeside Plumbing and Heating, after-hours line. What's going on?"
MAX_TURNS = 14
SEED_VISITS = {1: "{D1}-11", 2: "{D1}-15"}   # original slots of the seeded bookings

# Retry on rate limits / transient errors so one 429 doesn't fail a scenario.
core.client = genai.Client(http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(
    attempts=8, initial_delay=2.0, max_delay=60.0, http_status_codes=[429, 500, 503])))


def fill_dates(value, days):
    """Replace {D1}/{D2} placeholders with real dates."""
    if isinstance(value, str):
        return value.replace("{D1}", days[0]).replace("{D2}", days[1])
    if isinstance(value, list):
        return [fill_dates(v, days) for v in value]
    if isinstance(value, dict):
        return {k: fill_dates(v, days) for k, v in value.items()}
    return value


# ---------------- one simulated call ----------------
def run_call(scn):
    conn = init_db(DB_PATH)
    if scn.get("setup_sql"):
        conn.executescript(scn["setup_sql"])
        conn.commit()
    max_page_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM pages").fetchone()[0]

    session = core.new_session()
    caller = SimulatedCaller(scn["persona"])
    agent_text = GREETING
    for _ in range(MAX_TURNS):
        caller_text = caller.reply(agent_text)
        hung_up = HANGUP in caller_text
        caller_text = caller_text.replace(HANGUP, "").strip()
        if caller_text:
            agent_text = core.handle_turn(conn, session, caller_text)
        if hung_up:
            break
        # A real transfer hands the call to a person, so the AI's part of the call ends here.
        if any(r.get("name") == "transfer_to_human" and r["result"].get("ok") for r in session["transcript"]):
            break
    return conn, session, max_page_id


# ---------------- grading ----------------
def grade(conn, session, expect, max_page_id, days):
    checks = []
    seed = fill_dates(SEED_VISITS, days)

    def check(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    pages = conn.execute(
        "SELECT * FROM pages WHERE urgency = 'emergency' AND id > ? ORDER BY id", (max_page_id,)
    ).fetchall()
    new_visits = conn.execute("SELECT * FROM visits WHERE id > 2 AND status = 'booked' ORDER BY id").fetchall()
    agent_text = " ".join(r["text"] for r in session["transcript"] if r["role"] == "agent").lower()

    # ---- outcome: final database state ----
    if "emergency_pages" in expect:
        check("emergency_pages", len(pages) == expect["emergency_pages"], f"got {len(pages)}")
    if "page_address_contains" in expect:
        addr = pages[-1]["address"] if pages else ""
        check("page_address", expect["page_address_contains"].lower() in addr.lower(), f"got '{addr}'")
    if "page_callback" in expect:
        cb = pages[-1]["callback"] if pages else ""
        check("page_callback", cb == expect["page_callback"], f"got '{cb}'")
    if "no_page_callback" in expect:
        bad = [p["callback"] for p in pages if p["callback"] == expect["no_page_callback"]]
        check("no_wrong_callback", not bad, f"paged {bad}" if bad else "")
    if "safety_calls" in expect:
        n = conn.execute("SELECT COUNT(*) FROM safety_calls").fetchone()[0]
        check("safety_calls", n == expect["safety_calls"], f"got {n}")
    if "new_visits" in expect:
        check("new_visits", len(new_visits) == expect["new_visits"], f"got {len(new_visits)}")
    if new_visits:
        v = new_visits[-1]
        phone = conn.execute("SELECT phone FROM customers WHERE id = ?", (v["customer_id"],)).fetchone()["phone"]
        if "visit_phone" in expect:
            check("visit_phone", phone == expect["visit_phone"], f"got '{phone}'")
        if "visit_address_contains" in expect:
            check("visit_address", expect["visit_address_contains"].lower() in v["address"].lower(), f"got '{v['address']}'")
        if "visit_slot_in" in expect:
            check("visit_slot", v["slot_id"] in expect["visit_slot_in"], f"got '{v['slot_id']}'")
    for vid in expect.get("cancelled", []):
        row = conn.execute("SELECT status FROM visits WHERE id = ?", (vid,)).fetchone()
        check(f"cancelled_{vid}", row and row["status"] == "cancelled", f"status '{row['status'] if row else None}'")
    for vid in expect.get("untouched", []):
        row = conn.execute("SELECT status, slot_id FROM visits WHERE id = ?", (vid,)).fetchone()
        ok = row and row["status"] == "booked" and row["slot_id"] == seed[vid]
        check(f"untouched_{vid}", ok, f"{dict(row) if row else None}")
    for vid, allowed in expect.get("moved", {}).items():
        row = conn.execute("SELECT status, slot_id FROM visits WHERE id = ?", (int(vid),)).fetchone()
        ok = row and row["status"] == "booked" and row["slot_id"] in allowed
        check(f"moved_{vid}", ok, f"{dict(row) if row else None}")
    if "transfers" in expect:
        n = conn.execute("SELECT COUNT(*) FROM transfers").fetchone()[0]
        check("transfers", n == expect["transfers"], f"got {n}")
    if "agent_said_any" in expect:
        check("agent_said", any(s.lower() in agent_text for s in expect["agent_said_any"]), str(expect["agent_said_any"]))
    for s in expect.get("agent_never_said", []):
        check(f"never_said_{s}", s.lower() not in agent_text)

    # ---- adherence: checked on the tool-call trace, same for every scenario ----
    tools = [r for r in session["transcript"] if r["role"] == "tool"]
    writes_ok = [t for t in tools if t["name"] in core.WRITE_TOOLS and t["result"].get("ok")]
    for w in writes_ok:   # every successful write must have a read_back before it
        idx = session["transcript"].index(w)
        check("readback_before_write", any(r.get("name") == "read_back" for r in session["transcript"][:idx]), w["name"])
    if session["lane"] == "SAFETY":
        check("no_booking_on_safety", not any(t["name"] == "book_visit" for t in writes_ok))
    prices = {str(v) for v in CONFIG["pricing"].values()}
    quoted = set(re.findall(r"\$\s?(\d+)", agent_text)) | set(re.findall(r"(\d+)\s*dollars", agent_text))
    check("prices_from_list", quoted <= prices, f"quoted {sorted(quoted)}" if quoted - prices else "")

    return checks


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[k]


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--category")
    ap.add_argument("--label", default="baseline")
    args = ap.parse_args()

    days = [d.isoformat() for d in business_days_after(date.today())]
    scenarios = yaml.safe_load((ROOT / "scenarios.yaml").read_text())
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
    if args.category:
        scenarios = [s for s in scenarios if s["category"] == args.category]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = ROOT / "reports" / f"{stamp}-{args.label}"
    (run_dir / "transcripts").mkdir(parents=True, exist_ok=True)

    results, latencies = [], []
    for i, scn in enumerate(scenarios, 1):
        expect = fill_dates(scn.get("expect", {}), days)
        t0 = time.time()
        try:
            conn, session, max_page_id = run_call(scn)
            checks = grade(conn, session, expect, max_page_id, days)
            error = None
        except Exception as e:
            session, checks, error = {"transcript": []}, [], f"{type(e).__name__}: {e}"
            traceback.print_exc()
        passed = error is None and all(c["pass"] for c in checks)
        turn_ms = [r["latency_ms"] for r in session["transcript"] if r["role"] == "agent"]
        latencies += turn_ms
        res = {
            "id": scn["id"], "category": scn["category"], "pass": passed, "error": error,
            "failed": [c for c in checks if not c["pass"]], "checks": checks,
            "turns": len(turn_ms), "seconds": round(time.time() - t0, 1),
        }
        results.append(res)
        with (run_dir / "transcripts" / f"{scn['id']}.jsonl").open("w") as f:
            for row in session["transcript"]:
                f.write(json.dumps(row, default=str) + "\n")
        mark = "PASS" if passed else "FAIL"
        why = error or "; ".join(f"{c['check']} ({c['detail']})" for c in res["failed"])
        print(f"[{i:2}/{len(scenarios)}] {mark} {scn['id']}  {why}", flush=True)

    # ---- summary ----
    by_cat = {}
    for r in results:
        c = by_cat.setdefault(r["category"], [0, 0])
        c[0] += r["pass"]
        c[1] += 1
    summary = {
        "label": args.label, "run": stamp, "model": CONFIG["llm"]["model"],
        "passed": sum(r["pass"] for r in results), "total": len(results),
        "by_category": {k: f"{p}/{t}" for k, (p, t) in by_cat.items()},
        "llm_turn_ms_p50": pct(latencies, 50), "llm_turn_ms_p90": pct(latencies, 90),
        "avg_turns": round(statistics.mean(r["turns"] for r in results), 1) if results else None,
        "results": results,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    lines = [f"# Eval run {stamp} ({args.label})", "",
             f"**{summary['passed']}/{summary['total']} passed**  ",
             "By category: " + ", ".join(f"{k} {v}" for k, v in summary["by_category"].items()) + "  ",
             f"Agent LLM time per turn (text mode, includes tool rounds): p50 {summary['llm_turn_ms_p50']} ms, "
             f"p90 {summary['llm_turn_ms_p90']} ms. Average turns per call: {summary['avg_turns']}.", "",
             "| scenario | category | result | failed checks |", "|---|---|---|---|"]
    for r in results:
        why = r["error"] or "; ".join(f"{c['check']}: {c['detail']}" for c in r["failed"])
        lines.append(f"| {r['id']} | {r['category']} | {'PASS' if r['pass'] else 'FAIL'} | {why} |")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"\n{summary['passed']}/{summary['total']} passed  ->  {run_dir}/summary.md")


if __name__ == "__main__":
    main()
