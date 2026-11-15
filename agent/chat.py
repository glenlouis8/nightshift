"""Talk to the agent in the terminal. Run: uv run python -m agent.chat"""

from agent.core import handle_turn, new_session, save_log  # the brain we built
from agent.db import init_db  # the database setup


def main():
    # ---- START OF CALL ----
    conn = init_db()  # wipe + refill the fake shop database
    session = new_session()  # blank memory for this one phone call
    print("NightShift (type 'bye' to hang up)\n")
    print("AGENT: Lakeside Plumbing and Heating, after-hours line. What's going on?")

    # ---- THE CONVERSATION: repeats until you type bye ----
    while True:
        caller = input("YOU:   ").strip()  # wait for you to type a message
        if caller.lower() in {"bye", "quit", "exit"}:
            break  # hang up -> leave the loop

        seen = len(
            session["transcript"]
        )  # remember how long the transcript was BEFORE this turn
        reply = handle_turn(
            conn, session, caller
        )  # the agent loop: Gemini + tools + gates -> reply text

        # print only the tools used in THIS turn (everything added after 'seen')
        for row in session["transcript"][seen:]:
            if row["role"] == "tool":
                print(f"   [tool] {row['name']} {row['args']} -> {row['result']}")

        latency = session["transcript"][-1][
            "latency_ms"
        ]  # last row = agent reply, holds the timing
        print(f"AGENT: {reply}   ({latency} ms)")

    # ---- END OF CALL ----
    print(
        f"\nLog saved: {save_log(session)}"
    )  # write the whole call to logs/<id>.jsonl


# Run main() only when started with "python -m agent.chat", not when another file imports this
if __name__ == "__main__":
    main()
