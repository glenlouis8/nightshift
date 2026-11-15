"""The tool menu shown to the LLM. Names must match functions in tools.py exactly.
The LLM only reads this. It can't run anything; our code does that."""


def _tool(name, description, properties=None, required=None):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }


S = {"type": "string"}

TOOL_SCHEMAS = [
    _tool(
        "read_back",
        "Call this right before you read the details back to the caller, before ANY booking, reschedule, cancel or page. Then ask them to confirm and wait for their answer. Write actions are blocked until you do this and the caller says yes.",
        {"summary": {"type": "string", "description": "the exact details you are about to read back"}},
        ["summary"],
    ),
    _tool(
        "lookup_customer",
        "Find an existing customer by callback phone number. Use when a caller wants to reschedule or cancel.",
        {"phone": S},
        ["phone"],
    ),
    _tool(
        "get_open_slots",
        "List open 2-hour visit windows for tomorrow or the next business day. Optionally filter by day.",
        {"day": {"type": "string", "description": "YYYY-MM-DD, optional"}},
    ),
    _tool(
        "book_visit",
        "Book a ROUTINE visit into an open slot. Only after reading details back and the caller saying yes. Never for SAFETY or EMERGENCY calls.",
        {"slot_id": S, "name": S, "phone": S, "address": S, "issue": S},
        ["slot_id", "name", "phone", "address", "issue"],
    ),
    _tool(
        "reschedule_visit",
        "Move the caller's existing booking to a new open slot. Needs the caller's own name and phone.",
        {"name": S, "phone": S, "new_slot_id": S},
        ["name", "phone", "new_slot_id"],
    ),
    _tool(
        "cancel_visit",
        "Cancel the caller's existing booking. Needs the caller's own name and phone.",
        {"name": S, "phone": S},
        ["name", "phone"],
    ),
    _tool(
        "page_oncall",
        "Page the on-call technician. Use for a real EMERGENCY (active leak or flooding, no heat in freezing weather, no water, sewage backup). Only after reading details back and the caller saying yes.",
        {"urgency": {"type": "string", "enum": ["emergency"]}, "summary": S, "address": S, "callback": S},
        ["urgency", "summary", "address", "callback"],
    ),
    _tool(
        "log_safety_call",
        "Log a SAFETY call (gas smell, CO alarm, sparking, burning smell). Use after giving the caller the safety instructions. Never book these.",
        {"hazard": S, "address": S, "callback": S},
        ["hazard"],
    ),
    _tool(
        "transfer_to_human",
        "Transfer the caller to a human when they ask for one or you cannot help.",
        {"reason": S},
        ["reason"],
    ),
    _tool(
        "get_pricing",
        "Get the shop's price list. Call this before telling the caller ANY price. Never quote a price from memory.",
    ),
]
