"""Local business messaging — industry detection and tailored pitches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BusinessType:
    """Industry segment with a voice-friendly pitch and product fit."""

    id: str
    label: str
    keywords: tuple[str, ...]
    pitch: str
    recommended_product: str


LOCAL_BUSINESS_INTENT_PHRASES = (
    "local business",
    "small business",
    "my business",
    "our business",
    "for businesses",
    "help my business",
    "help our business",
    "maryland business",
    "maryland company",
    "how can ai help",
    "how can you help my business",
    "what do you do for business",
    "what do you do for businesses",
    "build an app",
    "custom app",
    "ai for business",
    "ai strategy",
    "strategy session",
)

BUSINESS_TYPES: tuple[BusinessType, ...] = (
    BusinessType(
        id="restaurant",
        label="restaurant or food service",
        keywords=("restaurant", "cafe", "coffee shop", "bakery", "catering", "food truck", "bar "),
        pitch=(
            "Restaurants lose catering and reservation calls when the line is busy or after hours. "
            "Our AI phone agent answers twenty-four seven — you're talking to one right now."
        ),
        recommended_product="AI Phone Agent",
    ),
    BusinessType(
        id="church",
        label="church or nonprofit",
        keywords=("church", "nonprofit", "ministry", "mosque", "synagogue", "community center"),
        pitch=(
            "Churches and nonprofits get lots of calls about events, hours, and volunteer signups. "
            "Our AI agent handles those questions and takes messages so your team isn't tied up."
        ),
        recommended_product="AI Phone Agent",
    ),
    BusinessType(
        id="contractor",
        label="contractor or trades",
        keywords=(
            "contractor",
            "plumber",
            "plumbing",
            "electrician",
            "hvac",
            "roofer",
            "landscap",
            "handyman",
            "construction",
            "trades",
        ),
        pitch=(
            "Contractors miss leads when they're on a job site. "
            "Our AI agent captures the job details and books callbacks — even after hours."
        ),
        recommended_product="AI Phone Agent",
    ),
    BusinessType(
        id="salon",
        label="salon or personal services",
        keywords=("salon", "barber", "spa", "nail", "beauty shop", "hair"),
        pitch=(
            "Salons and spas field the same questions about hours, services, and booking all day. "
            "Our AI agent handles that so your front desk can focus on clients in the chair."
        ),
        recommended_product="AI Phone Agent",
    ),
    BusinessType(
        id="medical",
        label="medical or dental office",
        keywords=("dental", "dentist", "doctor", "clinic", "medical office", "chiropract"),
        pitch=(
            "Medical offices need callers to get answers fast without tying up staff. "
            "Our AI agent handles common questions, takes messages, and can book demo appointments."
        ),
        recommended_product="AI Phone Agent",
    ),
    BusinessType(
        id="professional",
        label="professional services",
        keywords=("lawyer", "attorney", "accountant", "consultant", "law firm", "cpa"),
        pitch=(
            "Law firms and consultants can't afford to miss a new client call. "
            "Our AI agent qualifies inquiries and schedules follow-ups while you're with clients."
        ),
        recommended_product="AI Phone Agent",
    ),
    BusinessType(
        id="retail",
        label="retail or shop",
        keywords=("retail", "boutique", "store", "shop", "gift shop"),
        pitch=(
            "Retail shops lose walk-in traffic when customers can't reach you by phone. "
            "Our AI agent answers product and hours questions around the clock."
        ),
        recommended_product="AI Phone Agent",
    ),
)


def detect_local_business_intent(text: str) -> bool:
    """True when the caller is asking how NM2TECH helps local businesses."""
    lowered = text.lower()
    if any(p in lowered for p in LOCAL_BUSINESS_INTENT_PHRASES):
        return True
    if detect_business_type(text):
        return True
    return any(
        p in lowered
        for p in (
            "i run a",
            "i own a",
            "we run a",
            "we own a",
            "i have a",
            "we have a",
        )
    )


def detect_business_type(text: str) -> Optional[BusinessType]:
    """Return the best-matching industry segment, if any."""
    lowered = text.lower()
    best: tuple[int, BusinessType] | None = None
    for biz in BUSINESS_TYPES:
        score = sum(len(kw) for kw in biz.keywords if kw in lowered)
        if score and (best is None or score > best[0]):
            best = (score, biz)
    return best[1] if best else None


def build_local_business_prompt() -> str:
    """System-prompt block for local-business conversations."""
    return """WHEN THEY ASK WHAT NM2TECH DOES FOR LOCAL BUSINESSES:
- NM2TECH is a Maryland-based team that builds practical AI for real businesses — not hype.
- We help local businesses stop missing customer calls, tame back-office clutter, and look professional online.
- You ARE the live demo: this call is our AI Phone Agent answering like a receptionist would.
- Lead with ONE problem we solve, then ONE product — do not list every app unless they ask.
- Ask what type of business they run if you don't know yet.
- Offer ONE next step: schedule a demo, try the free website review, or leave a message.

PRODUCT FIT FOR LOCAL BUSINESSES (pick the best match):
- Missed calls / front desk overload → AI Phone Agent (this call is the demo)
- Contracts, leases, insurance paperwork → Guardian
- Receipt and expense tracking → ReceiptLens
- Website looks outdated or losing leads → Free Website Review
- Want something custom built → NM2TECH builds and hosts AI apps; offer a strategy session

DO NOT pitch hospital ER tools unless they are clearly healthcare operations leadership."""


def build_local_business_context(speech: str) -> str:
    """Extra OpenAI context when the caller is a local business owner."""
    if not detect_local_business_intent(speech):
        return ""

    lines = [
        "CALLER CONTEXT: Local business owner or operator asking how NM2TECH can help.",
        "NM2TECH value prop: practical AI for Maryland and local businesses — "
        "missed calls, paperwork, receipts, and weak websites.",
        "Remind them briefly that they are experiencing the AI Phone Agent on this call.",
    ]

    biz = detect_business_type(speech)
    if biz:
        lines.append(f"\nDETECTED INDUSTRY: {biz.label}")
        lines.append(f"Tailored angle: {biz.pitch}")
        lines.append(f"Best product to mention first: {biz.recommended_product}")
        lines.append("Give a short industry-specific answer, then ask if they'd like to schedule a demo.")
    else:
        lines.append(
            "\nIndustry not clear yet — give a one-sentence NM2TECH pitch and ask what type of business they run."
        )

    return "\n".join(lines)


def try_local_business_faq(
    speech: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> Optional[str]:
    """Fast first-turn answers for local-business questions."""
    if conversation_history:
        return None

    if not detect_local_business_intent(speech):
        return None

    biz = detect_business_type(speech)
    if biz:
        return (
            f"For a {biz.label}, {biz.pitch} "
            f"We'd start with our {biz.recommended_product}. "
            "Want to schedule a quick demo?"
        )

    lowered = speech.lower()
    if any(p in lowered for p in ("build an app", "custom app", "build something")):
        return (
            "NM2TECH designs, builds, and hosts practical AI apps for local businesses — "
            "from phone agents to document tools. "
            "Say schedule a demo and we can set up a free strategy session."
        )

    if any(p in lowered for p in ("website", "online presence", "look outdated")):
        return (
            "We offer a free website review — paste your URL at nm2tech dot com slash apps "
            "and see what might be costing you customers. "
            "Or I can tell you about our AI phone agent — you're on one now."
        )

    return (
        "NM2TECH helps local businesses with practical AI — answering calls twenty-four seven, "
        "organizing documents, tracking receipts, and reviewing websites. "
        "You're talking to our AI phone agent right now. What type of business do you run?"
    )
