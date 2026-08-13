"""OpenAI-powered conversation logic for the phone agent."""

import logging
import re
from typing import Any, Optional

from openai import OpenAI

from app.calendly_client import calendly_spoken_hint
from app.calendar_service import today_context_line
from app.config import get_settings, reload_settings
from app.products import build_product_catalog_prompt, try_product_faq
from app.local_business import build_local_business_prompt, try_local_business_faq

logger = logging.getLogger(__name__)

# Keywords that trigger a transfer to a human
TRANSFER_KEYWORDS = {"human", "representative", "agent", "transfer", "operator", "person"}

# Ask for Michael Kola / the NM2TECH owner (avoid bare "owner" — "I own a restaurant" is not a transfer)
OWNER_TRANSFER_PHRASES = (
    "michael kola",
    "michael cola",
    "mike kola",
    "mike cola",
    "business owner",
    "the owner",
    "talk to michael",
    "speak to michael",
    "speak with michael",
    "talk with michael",
    "talk to mike",
    "speak to mike",
    "connect me to michael",
    "connect me with michael",
    "put me through to michael",
    "i want michael",
    "get michael",
    "is michael there",
    "is michael available",
    "can i talk to michael",
    "can i speak to michael",
    "let me talk to michael",
    "let me speak to michael",
    "owner please",
)

# Phrases that start the leave-a-message flow
MESSAGE_KEYWORDS = {
    "leave a message",
    "take a message",
    "leave message",
    "record a message",
    "callback",
    "call me back",
}

# Phrases that start demo / appointment collection
DEMO_KEYWORDS = {
    "demo",
    "schedule",
    "appointment",
    "meeting",
    "sign up",
    "get started",
}

SYSTEM_PROMPT = f"""You are the NM2TECH AI phone assistant — a warm, natural-sounding helper for NM2TECH LLC and its apps.

HOW TO SOUND HUMAN ON THE PHONE:
- Listen to exactly what the caller said. Answer THEIR question, not a generic script.
- If they change topic, follow them — never repeat a previous answer.
- Keep replies short (1-2 sentences, under 35 words) but conversational, not robotic.
- It's okay to say "Sure", "Good question", or "I hear you" when it fits naturally.
- Ask only ONE question at a time.
- Never claim to be human. You are the NM2TECH AI phone assistant if asked directly.

WHEN THE QUESTION IS UNRELATED (weather, jokes, personal chat, random topics):
- Respond naturally and briefly to what they actually said.
- Then gently offer to help with NM2TECH apps or ask how you can assist them today.
- Do NOT force pricing, features, or a demo pitch unless they asked about a product.

{build_product_catalog_prompt()}

{build_local_business_prompt()}

ACTIONS YOU CAN OFFER ON THIS CALL (tell them to say these):
- "schedule a demo" or "what's available tomorrow?" — book a Phone Agent demo on the call
- "cancel my appointment" — cancel a booking
- "leave a message" — take a callback message
- "talk to Michael" or "business owner" — the phone system connects them to Michael Kola
- "what apps do you have?" — briefly list NM2TECH apps from the catalog above
- "how do you help local businesses?" — explain practical AI for their industry, then ask what business they run

TRANSFER RULES (CRITICAL):
- You CAN connect callers to Michael. Never say you cannot transfer, cannot reach him, or that you can only take a message instead.
- If they ask for Michael, Michael Kola, Mike, or the business owner, say you are connecting them now. Do not ask them to leave a message.

BOOKING RULES (CRITICAL):
- You CANNOT book or confirm appointments yourself. Never say "I've booked you", "you're all set", or "it's confirmed".
- Only the phone system's booking flow creates calendar events after collecting a time and the caller's name.
- If they pick a date or time, tell them which times are open and ask for their name — or say "I'll get that scheduled once I have your name."

Do NOT invent features or pricing beyond what is listed. Do NOT read a canned script."""

# Steps for collecting a voicemail message
MESSAGE_STEPS = ["name", "phone", "message"]

# Steps for collecting demo request info
DEMO_STEPS = ["name", "business_name", "phone", "preferred_time", "email"]


def get_openai_client() -> OpenAI:
    """Return an OpenAI client using the configured API key."""
    return OpenAI(api_key=reload_settings().openai_api_key)


def detect_owner_transfer(text: str) -> bool:
    """True when the caller asks for Michael Kola or the business owner."""
    lowered = text.lower()
    if any(p in lowered for p in OWNER_TRANSFER_PHRASES):
        return True
    stripped = re.sub(r"[^a-z\s]", "", lowered).strip()
    if stripped in (
        "michael",
        "mike",
        "michael please",
        "mike please",
        "kola",
        "michael kola please",
    ):
        return True
    # Speech-to-text often mangles the name; still transfer on a clear name hit.
    if re.search(r"\b(michael|micheal|michel|mikael|mikhail|kola)\b", lowered):
        return True
    if re.search(r"\bmike\b", lowered) and any(
        w in lowered for w in ("talk", "speak", "connect", "transfer", "owner", "please", "want")
    ):
        return True
    return False


def detect_transfer_intent(text: str) -> bool:
    """Return True if the caller wants to speak to a human or to Michael."""
    if detect_owner_transfer(text):
        return True
    lowered = text.lower()
    words = set(re.findall(r"[a-z]+", lowered))
    if words & TRANSFER_KEYWORDS:
        return True
    return any(
        phrase in lowered
        for phrase in ("speak to a human", "talk to someone", "real person", "live person")
    )


def transfer_prompt(speech: str) -> str:
    """Spoken line just before Twilio dials out."""
    if detect_owner_transfer(speech):
        return "One moment please, I'm connecting you to Michael now."
    return "One moment please, I'm connecting you now."


def detect_message_intent(text: str) -> bool:
    """Return True if the caller wants to leave a message."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in MESSAGE_KEYWORDS)


GOODBYE_PHRASES = (
    "goodbye",
    "good bye",
    "bye",
    "bye bye",
    "that's all",
    "that is all",
    "that'll be all",
    "nothing else",
    "nothing more",
    "no thanks",
    "no thank you",
    "i'm good",
    "im good",
    "i am good",
    "i'm done",
    "im done",
    "all set",
    "hang up",
    "end the call",
    "end call",
)


def should_end_call(
    speech: str,
    call_flow: str,
    flow_state: dict,
    turns: list,
) -> bool:
    """True when the caller wants to end the call (and it's safe to hang up)."""
    if call_flow == "cancelling_appointment" and flow_state.get("step") == "confirm":
        return False
    if call_flow == "booking_demo" and flow_state.get("step") in ("slot_choice", "name"):
        return False
    if call_flow in ("taking_message", "taking_demo"):
        return False

    lowered = speech.lower().strip()
    if any(p in lowered for p in GOODBYE_PHRASES):
        return True

    last_ai = ""
    for turn in reversed(turns):
        resp = getattr(turn, "ai_response", "") or ""
        if resp and resp not in ("[listening retry]",):
            last_ai = resp.lower()
            break

    if "anything else" in last_ai and lowered in (
        "no",
        "nope",
        "nah",
        "no thanks",
        "nothing",
        "that's it",
        "that's all",
        "okay",
        "ok",
    ):
        return True

    return False


# Instant canned answers — first caller question only (see try_faq_response)
FAQ_ENTRIES: list[tuple[list[str], str]] = [
    (
        ["price", "pricing", "plan", "cost", "how much", "fee", "monthly"],
        "We have three plans: Starter at ninety-nine dollars a month, "
        "Professional at one ninety-nine, and Business at three ninety-nine. "
        "Would you like to schedule a demo?",
    ),
    (
        ["what is nm2tech", "what do you do", "who are you", "about nm2tech"],
        "NM2TECH builds practical AI for local businesses — phone agents that never miss a call, "
        "document tools, receipt tracking, and free website reviews. "
        "You're talking to our AI phone agent right now. What type of business do you run?",
    ),
    (
        ["local business", "small business", "my business", "help my business", "maryland"],
        "We help local businesses stop missing calls and tame back-office work with practical AI. "
        "You're on our AI phone agent demo line right now. "
        "What kind of business do you run?",
    ),
    (
        ["how can ai help", "ai for business", "ai strategy", "strategy session"],
        "AI can answer your phones twenty-four seven, explain complex documents, "
        "and organize receipts — without hiring more staff. "
        "Want to schedule a free strategy session?",
    ),
    (
        ["what apps", "your apps", "nm2tech apps", "list apps", "other apps", "what products"],
        "We have Guardian for documents, ReceiptLens for receipts, a free website review tool, "
        "MedStar ER Command Center, and this AI Phone Agent you're calling now. "
        "Visit nm2tech dot com slash apps, or tell me which one interests you.",
    ),
    (
        ["feature", "what can you", "what does it do", "capabilities"],
        "We help local businesses answer calls, handle FAQs, take messages, and book appointments — "
        "plus tools for documents, receipts, and websites. "
        "You're experiencing our phone agent right now. What industry are you in?",
    ),
    (
        ["hours", "what time are you open", "are you open", "24/7", "twenty four seven"],
        "Our AI phone agent is available twenty-four seven. "
        "Would you like to schedule a demo with our team?",
    ),
]

PIVOT_PHRASES = (
    "actually",
    "instead",
    "different question",
    "never mind",
    "nevermind",
    "no wait",
    "wait no",
    "something else",
    "other question",
    "not that",
    "what i meant",
    "let me ask",
    "another question",
    "forget that",
    "on second thought",
    "change that",
    "rather ask",
)


def _is_topic_change(speech: str) -> bool:
    """True when the caller is pivoting or correcting their question."""
    lowered = speech.lower().strip()
    if any(p in lowered for p in PIVOT_PHRASES):
        return True
    return lowered.startswith(("no,", "no ", "but ", "okay but", "ok but"))


def detect_flow_abort(speech: str) -> bool:
    """True when the caller wants to stop the current booking/message flow."""
    lowered = speech.lower().strip()
    abort_phrases = (
        "never mind",
        "nevermind",
        "go back",
        "start over",
        "stop that",
        "forget it",
        "changed my mind",
        "don't want",
        "do not want",
        "not anymore",
        "cancel that",
        "cancel this",
        "cancel the booking",
        "stop booking",
    )
    if any(p in lowered for p in abort_phrases):
        return True
    if _is_topic_change(speech):
        return True
    # "cancel it" while booking = stop trying to book, not cancel a calendar event
    if "cancel" in lowered and any(w in lowered for w in ("it", "that", "this", "now")):
        return True
    return False


def detect_cancel_abort(speech: str) -> bool:
    """True when the caller backs out of a cancellation confirmation."""
    lowered = speech.lower().strip()
    return any(
        p in lowered
        for p in ("never mind", "nevermind", "keep it", "don't cancel", "do not cancel", "no cancel")
    )


def _faq_answer_recently_used(answer: str, conversation_history: list[dict[str, str]]) -> bool:
    """True if we already gave this canned answer in the last couple of turns."""
    snippet = answer[:50].strip()
    recent_assistant = [
        m.get("content", "")
        for m in conversation_history
        if m.get("role") == "assistant"
    ][-2:]
    return any(snippet in msg or msg.strip() == answer.strip() for msg in recent_assistant)


def try_faq_response(
    speech: str,
    conversation_history: list[dict[str, str]] | None = None,
    *,
    allow_fast_path: bool = True,
) -> Optional[str]:
    """
    Return a canned answer for common first questions — no OpenAI call.
    Skipped after the first exchange so follow-ups and topic changes use OpenAI.
    """
    if not allow_fast_path:
        return None

    conversation_history = conversation_history or []
    if conversation_history and _is_topic_change(speech):
        logger.info("FAQ skipped — caller changed topic: %r", speech[:50])
        return None

    # After any back-and-forth, use OpenAI so it understands context and new questions
    if conversation_history:
        logger.info("FAQ skipped — using OpenAI for follow-up: %r", speech[:50])
        return None

    product_answer = try_product_faq(speech, conversation_history)
    if product_answer:
        logger.info("Product FAQ fast-path matched: %r", speech[:50])
        return product_answer

    local_answer = try_local_business_faq(speech, conversation_history)
    if local_answer:
        logger.info("Local business FAQ fast-path matched: %r", speech[:50])
        return local_answer

    lowered = speech.lower()
    for keywords, answer in FAQ_ENTRIES:
        if any(kw in lowered for kw in keywords):
            if _faq_answer_recently_used(answer, conversation_history):
                return None
            logger.info("FAQ fast-path matched: %r", speech[:50])
            return answer
    return None


def detect_demo_intent(text: str) -> bool:
    """Return True when the caller wants to schedule or book — not informational questions."""
    return detect_booking_intent(text)


def detect_booking_intent(text: str) -> bool:
    """True when the caller explicitly wants to book or schedule."""
    lowered = text.lower()
    booking_phrases = (
        "make a booking",
        "make booking",
        "want to make a booking",
        "schedule a",
        "schedule an",
        "book a",
        "book an",
        "make an appointment",
        "make a appointment",
        "set up a",
        "set up an",
        "sign up for",
        "sign up to",
        "get a demo",
        "schedule a demo",
        "book a demo",
        "want to schedule",
        "want to book",
        "like to schedule",
        "like to book",
        "need to schedule",
        "need to book",
        "need an appointment",
        "i'd like to make",
        "i would like to make",
    )
    if any(p in lowered for p in booking_phrases):
        return True

    if "want to" in lowered and any(
        w in lowered for w in ("book", "schedule", "appointment", "meeting", "booking", "demo")
    ):
        return True

    return False


_AVAILABILITY_INQUIRY_PHRASES = (
    "do you have anything",
    "do you have any openings",
    "do you have any times",
    "do you have any slots",
    "have anything next",
    "have anything this",
    "have anything available",
    "have any openings",
    "anything next month",
    "anything next week",
    "anything this month",
    "anything tomorrow",
    "anything available",
    "what about next",
    "how about next",
    "what do you have next",
    "what times do you have",
    "what times are available",
    "when are you available",
    "when are you free",
    "any openings",
    "any times available",
)


def detect_availability_inquiry(text: str) -> bool:
    """
    True when the caller asks what times are open — should enter live booking flow.
    """
    if detect_booking_intent(text):
        return False

    lowered = text.lower()
    if any(p in lowered for p in _AVAILABILITY_INQUIRY_PHRASES):
        return True

    from app.calendar_service import detect_availability_intent

    return detect_availability_intent(text)


def detect_appointment_inquiry(text: str) -> bool:
    """
    True when the caller asks about an existing appointment (not open-slot browsing).
    """
    if detect_booking_intent(text) or detect_availability_inquiry(text):
        return False

    lowered = text.lower()
    inquiry_phrases = (
        "do i have",
        "my appointment",
        "my appointments",
        "any appointment",
        "are there appointment",
        "is there an appointment",
        "is there a appointment",
        "what appointment",
        "when is my",
        "when's my",
        "when am i",
        "how many appointment",
        "any demo",
        "are there demo",
    )
    return any(p in lowered for p in inquiry_phrases)


def generate_ai_response(
    caller_speech: str,
    conversation_history: list[dict[str, str]],
    extra_context: str = "",
) -> str:
    """
    Send the caller's speech and prior turns to OpenAI and return a spoken reply.

    conversation_history: list of {"role": "user"|"assistant", "content": "..."}
    extra_context: optional facts (e.g. live calendar data) appended to the system prompt.
    """
    if not reload_settings().openai_api_key:
        logger.warning("OPENAI_API_KEY not set — using fallback response")
        return (
            "I'm sorry, my AI service is not configured right now. "
            "Would you like to leave a message or speak with a representative?"
        )

    cfg = reload_settings()
    recent = conversation_history[-(cfg.openai_history_turns * 2) :]
    system_content = SYSTEM_PROMPT + "\n\n" + today_context_line()
    if extra_context.strip():
        system_content += (
            "\n\nLIVE CONTEXT (use this to answer — do not guess):\n"
            f"{extra_context.strip()}\n"
            "Answer naturally in 1-2 short sentences. Do not repeat pricing or feature lists "
            "unless the caller asked about them."
        )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent)
    messages.append({"role": "user", "content": caller_speech})

    if conversation_history:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Use the conversation above for context. "
                    "Respond to the caller's LATEST message only. "
                    "Do not repeat anything you already said."
                ),
            }
        )

    if _is_topic_change(caller_speech):
        messages.append(
            {
                "role": "system",
                "content": "The caller just changed topic. Answer their new question directly.",
            }
        )

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=cfg.openai_model,
            messages=messages,
            max_tokens=cfg.openai_max_tokens,
            temperature=0.65,
        )
        reply = response.choices[0].message.content or ""
        reply = reply.strip()
        logger.info("OpenAI response generated (%d chars)", len(reply))
        return reply
    except Exception as exc:
        logger.exception("OpenAI API error: %s", exc)
        return (
            "I'm having a little trouble right now. "
            "Would you like to leave a message or speak with a representative?"
        )


def generate_call_summary(
    caller_phone: str,
    turns: list[Any],
    voicemails: list[Any],
    demos: list[Any] | None = None,
) -> str:
    """Create a short post-call summary using OpenAI."""
    demos = demos or []
    if not reload_settings().openai_api_key:
        return _fallback_summary(caller_phone, turns, voicemails, demos)

    transcript_lines = []
    for turn in turns:
        transcript_lines.append(f"Caller: {turn.caller_speech}")
        transcript_lines.append(f"AI: {turn.ai_response}")

    transcript = "\n".join(transcript_lines) or "No conversation recorded."

    voicemail_text = ""
    if voicemails:
        for vm in voicemails:
            voicemail_text += (
                f"\nVoicemail from {vm.caller_name} ({vm.caller_phone}): {vm.message_text}"
            )

    demo_text = ""
    if demos:
        for demo in demos:
            demo_text += (
                f"\nDemo request: {demo.caller_name} / {demo.business_name} / "
                f"{demo.caller_phone} / preferred {demo.preferred_time}"
                f"{f' / {demo.email}' if demo.email else ''}"
            )

    prompt = f"""Summarize this phone call in 2-4 sentences for a business owner.

Caller phone: {caller_phone}
Transcript:
{transcript}
{voicemail_text}
{demo_text}

Include: caller intent, key questions, any action items (demo request, message left, transfer requested).
Keep it brief and factual."""

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=reload_settings().openai_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        return (
            response.choices[0].message.content
            or _fallback_summary(caller_phone, turns, voicemails, demos)
        ).strip()
    except Exception as exc:
        logger.exception("Failed to generate call summary: %s", exc)
        return _fallback_summary(caller_phone, turns, voicemails, demos)


def _fallback_summary(
    caller_phone: str,
    turns: list[Any],
    voicemails: list[Any],
    demos: list[Any] | None = None,
) -> str:
    """Simple summary when OpenAI is unavailable."""
    demos = demos or []
    turn_count = len(turns)
    parts = [f"Call from {caller_phone} with {turn_count} conversation turn(s)."]
    if voicemails:
        parts.append(f"{len(voicemails)} voicemail message(s) left.")
    if demos:
        parts.append(f"{len(demos)} demo request(s) captured.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Structured collection flows (message & demo)
# ---------------------------------------------------------------------------

def get_next_collection_prompt(flow: str, state: dict) -> Optional[str]:
    """
    Return the next question to ask during message/demo collection.
    Returns None when all fields are collected.
    """
    steps = MESSAGE_STEPS if flow == "taking_message" else DEMO_STEPS
    for step in steps:
        if step not in state or not state[step]:
            prompts = {
                "name": "May I have your name please?",
                "phone": "What is the best phone number to reach you?",
                "message": "Please leave your message after the tone, and I'll make sure someone gets back to you.",
                "business_name": "What is your business name?",
                "preferred_time": "What date and time works best for a demo?",
                "email": "Do you have an email address? If not, just say skip.",
            }
            return prompts[step]
    return None


def process_collection_input(flow: str, state: dict, speech: str) -> dict:
    """
    Store the caller's answer in the current collection step and advance.
    Returns updated state dict.
    """
    steps = MESSAGE_STEPS if flow == "taking_message" else DEMO_STEPS
    for step in steps:
        if step not in state or not state[step]:
            value = speech.strip()
            if step == "email" and value.lower() in ("skip", "no", "none", "n/a"):
                value = ""
            state[step] = value
            break
    return state


def is_collection_complete(flow: str, state: dict) -> bool:
    """Check whether all required fields have been collected."""
    steps = MESSAGE_STEPS if flow == "taking_message" else DEMO_STEPS
    for step in steps:
        # email is optional for demo flow
        if step == "email":
            continue
        if step not in state or not state[step]:
            return False
    return True


def collection_complete_message(flow: str, state: dict) -> str:
    """Return a confirmation message after collection is done."""
    if flow == "taking_message":
        name = state.get("name", "there")
        return (
            f"Thank you, {name}. Your message has been recorded and someone from NM2TECH "
            "will get back to you soon. Is there anything else I can help with?"
        )
    name = state.get("name", "there")
    business = state.get("business_name", "your business")
    cfg = reload_settings()
    calendly = (cfg.calendly_link or "").strip()
    if calendly:
        return (
            f"Thank you, {name}. I've saved your demo request for {business}. "
            f"To pick a time now, go to {calendly_spoken_hint(calendly)}. "
            "Our team will also follow up to confirm. "
            "Is there anything else I can help with today?"
        )
    return (
        f"Thank you, {name}. I've noted your demo request for {business}. "
        "A team member will follow up to confirm your appointment. "
        "Is there anything else I can help with today?"
    )
