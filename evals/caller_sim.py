"""Simulated caller: a second LLM that plays the customer from a persona (role card)."""

from google.genai import types

from agent import core

CALLER_MODEL = "gemini-3.5-flash-lite"   # different (cheaper) model than the agent
HANGUP = "[HANGUP]"

CALLER_RULES = """You are role-playing a CUSTOMER phoning a plumbing and heating company's after-hours line.
You are NOT the assistant. Stay in character the whole time.

Your role card:
{persona}

How to talk:
- Speak like a real person on the phone: 1 or 2 short sentences per turn.
- Only give details when the agent asks for them, unless your role card says otherwise.
- If the agent reads details back, check them against your role card. Say yes only if they are right; otherwise correct them.
- Do NOT hang up just because you said yes or picked a time. Wait until the agent clearly tells you it is done
  (booked, paged, cancelled, moved, logged, or transferring you), or says goodbye, or your role card tells you to hang up.
  Then say a short goodbye and end that message with {hangup}.
- Never write stage directions, never explain yourself, never mention you are simulated."""


class SimulatedCaller:
    def __init__(self, persona):
        self.cfg = types.GenerateContentConfig(
            system_instruction=CALLER_RULES.format(persona=persona.strip(), hangup=HANGUP),
            temperature=0.7,
        )
        self.history = []   # from the caller's point of view: agent = "user", caller = "model"

    def reply(self, agent_text):
        """Agent said agent_text; return what the caller says next."""
        self.history.append(types.Content(role="user", parts=[types.Part.from_text(text=agent_text)]))
        resp = core.client.models.generate_content(model=CALLER_MODEL, contents=self.history, config=self.cfg)
        text = (resp.text or "").strip() or "Hello?"
        self.history.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
        return text
