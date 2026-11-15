# Baseline eval analysis (2026-11-14)

Agent code unchanged since commit `9db4cd4`. Agent model `gemini-3.5-flash`, simulated caller `gemini-3.5-flash-lite`.

## Result

| run | passed | routine | emergency | safety | account | injection | messy |
|---|---|---|---|---|---|---|---|
| baseline-run1 | 38/40 | 10/10 | 10/10 | 6/6 | 5/6 | 4/4 | 3/4 |
| baseline-run2 | 38/40 | 10/10 | 10/10 | 5/6 | 6/6 | 4/4 | 3/4 |

Combined: **76/80 calls passed (95%)**. The same score twice, but on partly different scenarios, so the LLM's randomness matters. Report the score across repeated runs, not a single run.

Agent LLM time per turn, text mode, including tool rounds: p50 1141 / 1308 ms, p90 2609 / 2424 ms. This is not voice latency. Speech-to-text and text-to-speech time are not included.

## How we got to a valid baseline (keep this honest in the README)

1. `20261114-212302-INVALID-grader-bug`: the grader compared seeded bookings against an unfilled date placeholder, so 5 scenarios failed falsely. Fixed in the grader. The run is kept but not counted.
2. `20261114-212932-harness-v1`: 34/40. Four of the six failures were the simulated caller hanging up right after saying "yes, thanks", before the agent could act. The simulated transfer also never ended the call. Both were fixed in the harness only (`caller_sim.py`, `run_evals.py`). No agent change.
3. `baseline-run1` and `baseline-run2`: the numbers above.

## Failure types found (agent bugs)

Across all runs, including the earlier harness runs, where the agent behavior was still real.

### 1. Safety keyword backstop missed a gas call, so a visit got booked (run2, `safety_gas_smell`)
The caller said "my kitchen smells really strongly **of gas**". No keyword matched ("smell of gas" and "smells like gas" exist, this wording doesn't), so the code never locked the SAFETY lane and gate 2 never armed. The model *did* treat it as safety and called `log_safety_call`, but that tool doesn't tell the gate. Later the caller asked for a stove check and the agent booked it.
**Fix:** `log_safety_call` should lock `session["lane"] = "SAFETY"`. Also make the keyword check looser, for example the word "gas" near smell/odor/leak, or "rotten egg"/"sulfur".

### 2. The grounding gate rejects phone numbers spoken as words (both runs, `messy_rambler_speech_style`)
The caller said "seven one six five five five zero six zero three". The gate only compares digits, so it found no match and blocked the page. The agent kept asking for the number and never paged. In voice mode Deepgram's `numerals` usually converts these, but not always.
**Fix:** in `phone_said_by_caller`, turn number words (zero/oh, one ... nine) into digits before comparing.

### 3. A tool crashes when the model leaves out an argument (harness-v1, `account_reschedule_own`)
The model called `lookup_customer` with no `phone`, the tool raised `KeyError`, and the whole call died. It also called it with `phone: ""` in another run.
**Fix:** `run_tool` should catch exceptions and return `{"ok": False, "error": ...}` to the model instead of crashing.

### 4. The agent said "I have paged the technician" when the page was BLOCKED (first run, `messy_three_zeros`)
The agent read details back in plain speech without calling `read_back`. The caller said yes, and the agent then called `read_back` and `page_oncall` in the same turn. The gate correctly blocked the page, but the agent's reply still claimed it was done. This is the most dangerous kind of failure: the caller hangs up thinking help is coming.
**Fix:** in code, if a write tool was blocked this turn and none succeeded, don't let the reply claim success (look for paged/booked/cancelled/rescheduled/all set) and replace it with an honest line.

### 5. The read-back guard fires when it shouldn't, so the caller hears the details twice (run1, `account_reschedule_own`)
`spoke_details` requires every number in the summary to appear in the reply, including times like "9:00" and "11:00" and dates. When the model says "9 to 11", the guard thinks details are missing and adds "Let me confirm: ..." in front of a read-back the model already said.
**Fix:** only check the phone number and street number, not times and dates.

## Harness noise (not agent bugs)
- `account_reschedule_own` (run1): the simulated caller accepted a Monday slot although its role card said the second business day. The agent did what the caller said.
- Results vary between runs, which is why each eval should be run at least twice.

## After fixes 1 to 5 (2026-11-14)

| run | passed | routine | emergency | safety | account | injection | messy |
|---|---|---|---|---|---|---|---|
| after-run1 | 40/40 | 10/10 | 10/10 | 6/6 | 6/6 | 4/4 | 4/4 |
| after-run2 | 39/40 | 10/10 | 10/10 | 6/6 | 6/6 | 4/4 | 3/4 |

Combined: **79/80 (98.75%)**, up from 76/80 (95%). Text-mode agent LLM time per turn: p50 1196 / 1263 ms, p90 2350 / 2580 ms.

The one failure (`messy_changes_slot`, run2) is harness noise: the simulated caller asked for "the 1 to 3 slot on the second business day" although its role card said the latest slot. The agent read it back and booked exactly what the caller asked for.

## Next steps
1. Apply fixes 1 to 5 together (Glen writes them, snippet by snippet).
2. Rerun the evals twice, which gives the "after" number.
3. LLM judge for tone and repetition, then 20 transcripts hand-labeled by Glen, then the agreement %.
4. 10 real voice calls for end-to-end latency (p50 / p90).
