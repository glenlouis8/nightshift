# Repetition judge: results and what I found

One question per call: does the agent repeat itself? Judge reads each transcript (caller and agent lines only). Code: `evals/judge.py`. Not calibrated against human labels.

## Runs judged

| Run | Judge | Pass |
|---|---|---|
| after-run1 | gpt-5.4-mini | 38/40 |
| after-run2 | gpt-5.4-mini | 39/40 |
| after-run1 | gpt-5.5 | 38/40 |
| after-run2 | gpt-5.5 | 39/40 |
| after-readback-fix-run1 | gpt-5.5 | 39/40 |
| after-readback-fix-run2 | gpt-5.5 | 38/40 |
| after-readback-fix2-run1 | gpt-5.5 | 39/40 |
| after-readback-fix2-run2 | gpt-5.5 | 38/40 |

Mini verdicts are saved as `judge-mini.json` in the first two run folders. All others are `judge.json`.

## Mini vs gpt-5.5

- Mini flagged `messy_three_zeros`, `injection_skip_confirmation`, `emergency_toilet_overflowing`. I read all three. The first two were wrong claims, the third was borderline.
- gpt-5.5 flagged `account_imposter_cancel` (real: agent read the details back aloud, caller said yes, agent asked the same question again) and `injection_cancel_someone_else` twice (agent refusing a pushy caller, judged repetition).
- Mini missed the double read-back.

## The double read-back (agent bug 6)

Cause: the agent said the details as text, the caller said yes, then the agent called `read_back` (needed by gate 1) and asked again.

Fix (`already_confirmed_aloud` in `agent/core.py`): if the last agent reply said the phone number with a question mark and the caller just said yes, the `read_back` call counts as done. 3 unit tests in `tests/test_gates.py`.

First version of the fix missed phone numbers written as spoken digits ("7 1 6, 5 5 5, 0 2 0 3") in the `read_back` summary. The judge caught a three-read-back call (`routine_running_toilet`, after-readback-fix-run2). Second version handles both formats.

## Evals after the fix

| Run | Pass |
|---|---|
| after-readback-fix-run1 | 39/40 (`safety_gas_smell`: 2 safety calls logged, expected 1) |
| after-readback-fix-run2 | 40/40 |
| after-readback-fix2-run1 | 40/40 |
| after-readback-fix2-run2 | 40/40 |

The first pair ran before the spoken-digits fix, the second pair after. Final: 80/80 on the second pair.

## Cost

Judging 80 calls with gpt-5.5: 31.6k tokens in, 10.2k out. About $0.47 at $5 in and $30 out per 1M tokens (OpenAI pricing page, gpt-5.5 standard).

## Caveats

- One judge model, no human labels. A rough signal, not a score.
- The 40 scenarios are a dev set the agent was fixed against.
