<div align="center">

# NightShift

**An after-hours voice dispatcher for plumbing and heating shops, with its safety rules enforced in code and checked by a 40-scenario eval harness.**

<img src="https://img.shields.io/badge/Python-3.12%2B-3776ab?logo=python&logoColor=white" alt="Python"> <img src="https://img.shields.io/badge/Gemini-3.5_Flash-4285f4?logo=googlegemini&logoColor=white" alt="Gemini"> <img src="https://img.shields.io/badge/Pipecat-voice-6e56cf" alt="Pipecat"> <img src="https://img.shields.io/badge/SQLite-state-003b57?logo=sqlite&logoColor=white" alt="SQLite"> <img src="https://img.shields.io/badge/evals-80%2F80-2a78d6" alt="Evals 80/80">

[What it does](#what-it-does) · [Rules in code](#why-the-rules-live-in-code) · [Eval results](#eval-results) · [Architecture](#architecture) · [Run it](#run-it)

<img src="docs/images/hero.jpg" alt="An eval transcript: the caller reports a burst pipe, the agent reads back the address and number, the caller confirms, and only then is page_oncall called" width="860">

<sub>A transcript from an eval run (the caller is a simulated LLM): read-back, a clear yes, then the page.</sub>

<br>

<table>
<tr>
<td align="center" width="25%"><b>80/80</b><br><sub>simulated calls passed after fixes (baseline 76/80)</sub></td>
<td align="center" width="25%"><b>40</b><br><sub>scenarios in 6 categories</sub></td>
<td align="center" width="25%"><b>6</b><br><sub>rules enforced in code</sub></td>
<td align="center" width="25%"><b>6</b><br><sub>agent bugs found by the evals</sub></td>
</tr>
</table>

</div>

---

## What it does

A pipe bursts at 2 AM and the shop's phone goes to voicemail. NightShift answers, works out how serious it is, and acts. It also answers price questions (from the shop's price list only), reschedules or cancels bookings, and transfers to a human on request.

<table>
<tr>
<td width="52%" valign="top">

- **Safety** (gas smell, CO alarm, sparking): fixed safety instructions, logs the call. Never books, even when the caller insists.
- **Emergency** (burst pipe, flooding, no heat): gets the address and callback number, reads them back, pages the on-call tech after the caller confirms.
- **Routine** (drips, maintenance, quotes): offers open slots and books a visit.

Paging, transfers and the calendar are simulated with SQLite. No real SMS is sent.

</td>
<td width="48%" valign="top">

<img src="docs/images/safety.jpg" alt="An eval transcript: a caller smells gas and asks to book a visit; the agent refuses to book, gives safety instructions, and logs the safety call" width="100%">

</td>
</tr>
</table>

## Why the rules live in code

An agent that books jobs and wakes people up can't rely on "the prompt told it to." These rules are enforced in the backend, so the model can't skip them:

1. **Confirm before acting.** No booking, reschedule, cancel or page unless the agent read the details back and the caller said yes.
2. **No booking on a safety call.** A gas smell or sparking locks the call into the safety lane.
3. **Callers only touch their own bookings.** Needs a matching name and phone.
4. **Prices only from the price list.** Set in the prompt and checked by the evals, not hard-blocked in code.
5. **Phone numbers must come from the caller.** If the model changes or invents a digit, the action is blocked.
6. **Short phone numbers are not read back.** 7 to 9 digits means ask for the full number.

Two reply guards also run before the caller hears anything: one makes sure the phone and house number are actually spoken in a read-back, and one replaces "I've paged the technician" if the page was blocked.

## Eval results

<div align="center">
<img src="docs/images/results.jpg" alt="Grouped bar chart of pass rate by category. Baseline: routine, emergency and injection 100%, safety and account 91.7%, messy 75%. After fixes: 100% in every category." width="760">
</div>

| | run 1 | run 2 | total |
|---|---|---|---|
| Baseline | 38/40 | 38/40 | 76/80 (95%) |
| After fixes | 40/40 | 39/40 | 79/80 (98.75%) |
| After read-back fix | 40/40 | 40/40 | 80/80 (100%) |

**Caveat:** the 40 scenarios are a dev set. I wrote them and fixed the agent against the failures, so 80/80 is not a held-out score. Each version ran twice because the model is not deterministic.

A simulated caller (`gemini-3.5-flash-lite`) plays a role card against the real agent (`gemini-3.5-flash`) through the same `handle_turn()` as text and voice mode. A grader then checks the final SQLite state against the expected result, with no LLM involved. Adherence checks run on the tool-call trace: a `read_back` before every write, no booking on a safety call, every dollar amount on the price list.

<details>
<summary><b>The 6 bugs the evals found</b></summary>

<br>

1. "Smells really strongly of gas" matched no safety keyword, so the agent later booked a visit. Now `log_safety_call` locks the lane, and a pattern catches "gas" near smell, odor or leak.
2. A phone number spoken as words was blocked by gate 5. Number words are now converted to digits first.
3. A tool call with a missing argument crashed the call. Tool errors now go back to the model.
4. A page was blocked, but the agent still told the caller it had paged. Now caught by the reply guard.
5. The read-back guard fired on times and dates, so callers heard details twice. It now checks only phone and house number.
6. The agent said the details aloud, the caller said yes, then the agent asked again via `read_back`. Now a spoken read-back plus a yes counts. Found by the repetition judge.

</details>

<details>
<summary><b>Fixing the harness before trusting it</b></summary>

<br>

The first run scored 30/40, but 5 failures were a grader bug. The next scored 34/40, and 4 failures were the simulated caller hanging up right after "yes". Both were harness fixes with no agent changes, before the baseline was recorded. See [`evals/reports/baseline-analysis.md`](evals/reports/baseline-analysis.md).

</details>

### Repetition judge

An LLM judge reads each transcript and answers one question: does the agent repeat itself? It uses `gpt-5.5` (a different family than the Gemini agent). `gpt-5.4-mini` flagged 3 calls and I read all three: two were wrong claims, one borderline. `gpt-5.5` caught the double read-back above. Judging 80 calls cost about $0.47.

It is **not calibrated** against human labels, so treat it as a rough signal, not a score. Verdicts are in `judge.json` next to each run, and the write-up is in [`evals/reports/judge-analysis.md`](evals/reports/judge-analysis.md).

## Architecture

```mermaid
flowchart LR
    mic["Browser mic<br/>(WebRTC)"] --> stt["Deepgram STT<br/>+ turn detection"]
    term["Terminal<br/>(text mode)"] --> core
    sim["Simulated caller<br/>(evals)"] --> core
    stt --> core["handle_turn()<br/>agent/core.py"]
    core <--> llm["Gemini<br/>decides"]
    core --> gate{"check_gate()"}
    gate -- allowed --> tools["tools.py"] --> db[("SQLite")]
    gate -- BLOCKED --> llm
    core --> guards["reply guards"]
    guards --> tts["ElevenLabs TTS"] --> spk["Caller speaker"]
```

Text mode, voice mode and the eval harness all call the same `handle_turn()`, so every rule behaves the same everywhere. The agent loop is hand-written (about 20 lines), which is what lets a gate sit between "the model wants to book" and "the booking happens." Pipecat runs the browser audio pipeline over WebRTC, with its built-in LLM step swapped for `handle_turn()`.

| Where | What |
|---|---|
| `agent/core.py` | gates, system prompt, agent loop, reply guards |
| `agent/tools.py` | the tools the agent can call |
| `agent/config.yaml` | shop info, price list, on-call tech, safety keywords |
| `voice/bot.py` | Pipecat voice pipeline around `handle_turn()` |
| `evals/` | scenarios, simulated caller, runner, judge, reports |

## Voice

Measured on 16 real browser calls (73 turns), by me talking to the agent: **p50 2.4 s, p90 5.8 s, max 8.1 s** from the caller finishing a sentence to the bot speaking. That is slow for a phone call. The agent (Gemini plus tool rounds) is about 70% of it, and everything else is roughly 0.5 s. If the agent takes over 1.5 s the bot says "One moment." first, and after 8 s of silence it asks "Are you still there?" (at most twice).

<details>
<summary><b>What voice testing caught that text testing missed</b></summary>

<br>

- **Turn cut off mid-sentence.** A short pause was treated as the end of the turn, and the agent replied to half a sentence. This is the usual voice activity detection trade-off.
- **Read-back never spoken.** The agent recorded the details but only said "Is that correct?". Fixed with the read-back guard.
- **A digit filled in by the model.** A number ending in three zeros was "corrected" to four. Fixed with gate 5: Deepgram writes spoken numbers as digits and the code blocks any phone number the caller never said.

</details>

## Run it

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env    # then add your keys
```

Keys: `GEMINI_API_KEY`, plus `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY` for voice, and `OPENAI_API_KEY` for the judge.

```bash
uv run python -m agent.chat                       # text mode, tool calls printed
uv run python -m voice.bot                        # voice, then open http://localhost:7860/client
uv run python -m evals.run_evals                  # all 40 scenarios (--category safety for one)
uv run python -m evals.judge evals/reports/<run>  # repetition judge, writes judge.json
uv run python -m evals.voice_latency              # p50/p90 from logs/ voice calls
uv run pytest                                     # unit tests for the gates
```

Every run starts from a fresh fake shop (3 customers, 2 bookings, open slots for two business days). Eval reports go to `evals/reports/<time>-<label>/`, and each call is saved to `logs/<call_id>.jsonl`.
