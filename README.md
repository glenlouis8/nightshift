# NightShift

An after-hours voice dispatcher for plumbing and heating shops.

A shop closes at 6 PM. A pipe bursts at 2 AM. The call goes to voicemail, and the customer calls the next shop on Google. NightShift answers that call, figures out how serious it is, and does the right thing:

- **Safety** (gas smell, CO alarm, sparking): gives fixed safety instructions and logs the call. Never books, never troubleshoots.
- **Emergency** (burst pipe, flooding, no heat, sewage backup): collects the address and callback number, reads them back, and pages the on-call tech once the caller confirms.
- **Routine** (dripping faucet, maintenance, quotes): offers open slots and books a visit for the next business day.

It also answers price questions (only from the shop's price list), reschedules or cancels existing bookings, and transfers to a human on request.

## Why the rules live in code

An agent that books jobs and wakes people up at 2 AM can't rely on "the prompt told it to." The important rules are enforced in the backend, so the model can't skip them even if it gets confused or a caller tries to trick it:

1. **Confirm before acting.** No booking, reschedule, cancel, or page runs unless the agent read the details back and the caller then said yes. A "yes, but the address is wrong" does not count.
2. **No booking on a safety call.** If the caller mentions a gas smell, sparking, and so on, the call is locked into the safety lane and booking is blocked.
3. **Callers only touch their own bookings.** Reschedule and cancel need a name and phone number that match the same customer.
4. **Prices only from the price list.** The agent quotes numbers from `get_pricing()` and nowhere else.
5. **Phone numbers must come from the caller.** Before any booking or page, the code checks that the phone number the model passed actually appears in what the caller said. If the model changed or invented a digit, the action is blocked and the agent asks the caller to repeat the number.

There is also a read-back guard: if the agent calls `read_back` but forgets to actually say the details out loud, the code says them for it. This was found during voice testing (see below).

## How it works

```
                 voice mode only                          voice mode only
              ┌──────────────────┐                     ┌────────────────────┐
 caller mic ─►│ Deepgram (STT)   │─► VAD: turn over ─► │                    │
              └──────────────────┘                     │                    │
                                                       │   handle_turn()    │
 terminal  ──────────── text mode ───────────────────► │   agent/core.py    │
                                                       │                    │
                                                       └─────────┬──────────┘
                                                                 │
                             Gemini decides ─► check_gate() ─► tool runs ─► SQLite
                                   ▲                                          │
                                   └──────────── result goes back ────────────┘

 reply text ─► ElevenLabs (TTS) ─► caller speaker        (voice mode)
 reply text ─► printed in terminal                        (text mode)
```

- **One brain, two front ends.** Text mode and voice mode call the same `handle_turn()`, so every rule and tool behaves the same in both. The eval harness will use text mode.
- **A hand-written agent loop.** About 20 lines: send the conversation to the model, run any tool it asks for, send back the result, repeat until it answers. Writing it by hand is what lets a gate sit between "the model wants to book" and "the booking happens."
- **Voice pipeline with Pipecat.** Pipecat runs the audio pipeline in the browser over WebRTC, so no phone number is needed for the demo. Pipecat's built-in LLM step is swapped out for `handle_turn()`.
- **Paging is simulated.** A page is a row in the `pages` table plus a console line. No real SMS is sent.

## Run it

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env    # then add your keys
```

Keys: `GEMINI_API_KEY` (text and voice), plus `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY` for voice.

**Text mode**

```bash
uv run python -m agent.chat
```

Tool calls are printed as they happen, so you can watch the gates work.

**Voice mode**

```bash
uv run python -m voice.bot
```

Open http://localhost:7860/client, click Connect, allow the microphone, and talk.

Every run starts from a fresh fake shop (3 customers, 2 existing bookings, open slots for the next two business days). Each call is saved to `logs/<call_id>.jsonl`.

## Project layout

```
agent/
  config.yaml   shop info, price list, on-call tech, safety keywords
  db.py         SQLite schema and seed data
  tools.py      the tools the agent can call
  schemas.py    tool descriptions shown to the model
  core.py       gates, system prompt, agent loop, call logging
  chat.py       text mode
voice/
  bot.py        Pipecat voice pipeline around handle_turn()
```

## What voice testing caught that text testing missed

- **Turn cut off mid-sentence.** A short pause after "My..." was treated as the end of the turn, and the agent replied to half a sentence. This is the usual trade-off in voice activity detection: wait longer and the bot feels slow, wait less and it interrupts.
- **Read-back never spoken.** The agent recorded the details for confirmation but only said "Is that correct?", so the caller confirmed details they never heard. Fixed with the read-back guard in code.
- **A digit filled in by the model.** The caller said a phone number ending in three zeros. The model "corrected" it to four and tried to page with the wrong number. In a later call it even read the number back correctly and still sent four zeros to the tool. Fixed with gate 5: Deepgram now writes spoken numbers as digits, and the code blocks any phone number the caller never said. Re-tested by voice: the page was blocked and the agent asked for the number again.

## Status

- [x] Text mode: routine booking and emergency page, end to end
- [x] Voice mode in the browser: full emergency call
- [x] Code-enforced gates and read-back guard
- [x] Repeat-caller detection (a second page within 60 minutes is flagged as a repeat)
- [ ] Unit tests for each gate
- [ ] Eval harness: 40 simulated-caller scenarios scored on final database state
- [ ] LLM judge for tone and repetition, checked against hand labels
- [ ] Voice latency measurements (p50 / p90)

Results will be added here only once they are measured.

## Known limits

- English only.
- Paging, transfers, and the calendar are simulated with SQLite.
- Runs locally. There is no phone number; voice mode uses the browser.
- Safety detection uses a keyword list as a backstop, so unusual phrasing relies on the model.
