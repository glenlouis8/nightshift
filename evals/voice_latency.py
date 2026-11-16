"""Voice latency p50/p90 from real voice calls. Reads logs/*.jsonl rows with role=voice_latency.

Usage: uv run python -m evals.voice_latency
Latency = caller stops speaking -> bot starts speaking (includes STT, agent, TTS, turn detection).
Turns where the bot first said "One moment." (filler=True) measure time to the filler, not to the
real answer, so they are reported separately.
"""

import json
import statistics
from pathlib import Path


def show(label, ms):
    if len(ms) < 2:
        print(f"{label}: {len(ms)} turns, not enough")
        return
    p90 = statistics.quantiles(ms, n=10, method="inclusive")[8]
    print(f"{label}: {len(ms)} turns | p50 {statistics.median(ms):.0f} ms | p90 {p90:.0f} ms | max {max(ms)} ms")


def main():
    calls, rows = 0, []
    for path in sorted(Path("logs").glob("*.jsonl")):
        got = [r for r in map(json.loads, path.read_text().splitlines()) if r["role"] == "voice_latency"]
        if got:
            calls += 1
            rows += got
    if not rows:
        print("no voice latency rows yet")
        return
    print(f"{calls} voice calls")
    show("all turns", [r["latency_ms"] for r in rows])
    show("no filler (real answer)", [r["latency_ms"] for r in rows if not r.get("filler")])
    show("filler turns (time to 'One moment')", [r["latency_ms"] for r in rows if r.get("filler")])


if __name__ == "__main__":
    main()
