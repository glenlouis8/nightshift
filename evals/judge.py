"""LLM judge for one thing: does the agent repeat itself? Different model family (OpenAI) than the agent (Gemini).

NOT calibrated against human labels. Treat it as a rough smoke detector, not a measurement of quality.

Usage: uv run python -m evals.judge evals/reports/<run-folder> [more run folders]
Writes judge.json in each run folder and prints token usage so cost is measured.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

JUDGE_MODEL = "gpt-5.5"

RUBRIC = """You are grading an after-hours phone call between a plumbing shop's AI agent and a caller.
Judge ONLY this: does the agent repeat itself?

FAIL if the agent either:
- asks for information the caller already gave earlier in the call, or
- says the same sentence, or the same details, twice in a row with nothing new between.

These are NOT repetition, so do not fail for them:
- Reading the booking or page details back ONCE to get a confirmation.
- Reading the details back again after the caller corrected something.
- Repeating safety instructions when the caller has not yet followed them.

Otherwise PASS. Ignore tone, correctness, and whether the booking or page worked.
Reply with JSON only: {"verdict": "pass" or "fail", "reason": "one short sentence"}"""


def transcript_text(path):
    """Turn a transcript .jsonl into plain 'Caller: / Agent:' lines. Tool rows are skipped."""
    lines = []
    for row in map(json.loads, path.read_text().splitlines()):
        if row["role"] == "caller":
            lines.append(f"Caller: {row['text']}")
        elif row["role"] == "agent":
            lines.append(f"Agent: {row['text']}")
    return "\n".join(lines)


def judge_one(client, text):
    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )
    out = json.loads(resp.choices[0].message.content)
    return out["verdict"], out["reason"], resp.usage


def judge_run(client, run_dir):
    run_dir = Path(run_dir)
    results, tok_in, tok_out = {}, 0, 0
    for path in sorted((run_dir / "transcripts").glob("*.jsonl")):
        verdict, reason, usage = judge_one(client, transcript_text(path))
        results[path.stem] = {"verdict": verdict, "reason": reason}
        tok_in += usage.prompt_tokens
        tok_out += usage.completion_tokens
        if verdict == "fail":
            print(f"  FAIL {path.stem}: {reason}")
    (run_dir / "judge.json").write_text(json.dumps(results, indent=2))
    n_pass = sum(r["verdict"] == "pass" for r in results.values())
    print(f"{run_dir.name}: {n_pass}/{len(results)} pass | tokens in={tok_in} out={tok_out}")
    return n_pass, len(results), tok_in, tok_out


if __name__ == "__main__":
    client = OpenAI()
    totals = [0, 0, 0, 0]
    for folder in sys.argv[1:]:
        for i, v in enumerate(judge_run(client, folder)):
            totals[i] += v
    print(f"\nTOTAL {totals[0]}/{totals[1]} pass | judge={JUDGE_MODEL} | tokens in={totals[2]} out={totals[3]}")
