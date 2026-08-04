"""NM2TECH product catalog for the multi-app phone assistant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import reload_settings


@dataclass(frozen=True)
class Product:
    """One NM2TECH app or service the phone agent can discuss."""

    id: str
    name: str
    status: str  # live | coming_soon
    tagline: str
    summary: str
    features: tuple[str, ...]
    access: str
    keywords: tuple[str, ...]
    url_key: str = ""
    pricing: str = ""


PRODUCTS: tuple[Product, ...] = (
    Product(
        id="phone_agent",
        name="AI Phone Agent",
        status="live",
        tagline="24/7 AI receptionist for your business",
        summary=(
            "Answers calls, handles FAQs, takes messages, transfers to your team, "
            "and sends call summaries."
        ),
        features=(
            "Answers incoming calls with a branded greeting",
            "Multi-turn voice conversation",
            "Transfer to a human on request",
            "Leave-a-message and demo scheduling flows",
            "Post-call AI summaries",
        ),
        access="Call this demo line or visit nm2tech dot com slash apps",
        keywords=(
            "phone agent",
            "phone assistant",
            "receptionist",
            "ai phone",
            "answer calls",
            "nm2tech phone",
        ),
        pricing="Starter ninety-nine dollars a month, Professional one ninety-nine, Business three ninety-nine",
    ),
    Product(
        id="guardian",
        name="Guardian",
        status="live",
        tagline="Keep important documents safe and understood",
        summary=(
            "A private document vault with plain-language explanations, deadline tracking, "
            "and share links you control."
        ),
        features=(
            "Secure document storage",
            "Plain-language explanations of complex documents",
            "Deadline and renewal tracking",
            "Controlled share links",
            "Works in the browser — add to your phone home screen",
        ),
        access="Open in your mobile browser and add to Home Screen — no app store required",
        keywords=(
            "guardian",
            "document vault",
            "documents",
            "deadline",
            "deadlines",
            "share link",
            "vault",
            "insurance policy",
            "lease",
            "contract",
        ),
        url_key="guardian_url",
    ),
    Product(
        id="receiptlens",
        name="ReceiptLens AI",
        status="live",
        tagline="Turn receipts into clear, searchable records",
        summary=(
            "Capture and organize receipt details with AI so expenses stay tidy "
            "without spreadsheet work."
        ),
        features=(
            "Receipt capture from your phone",
            "AI extraction of amounts, vendors, and dates",
            "Searchable expense records",
            "Browser-based — add to Home Screen",
        ),
        access="Open in your mobile browser from nm2tech dot com slash apps",
        keywords=(
            "receipt",
            "receipts",
            "receipt lens",
            "receiptlens",
            "expense",
            "expenses",
            "receipt scanner",
        ),
        url_key="receiptlens_url",
    ),
    Product(
        id="medstar_er",
        name="MedStar Montgomery ER Command Center",
        status="live",
        tagline="Live ER operations visibility for hospital leadership",
        summary=(
            "A command-center view of ER flow, wait pressure, and operational signals "
            "for MedStar Montgomery."
        ),
        features=(
            "ER flow visibility",
            "Wait-time and pressure indicators",
            "Operational signals at a glance",
        ),
        access="Web dashboard — scan the QR on nm2tech dot com slash apps",
        keywords=(
            "medstar",
            "er command",
            "command center",
            "emergency room",
            "hospital dashboard",
            "wait time",
        ),
        url_key="medstar_er_url",
    ),
    Product(
        id="website_review",
        name="Free Website Review",
        status="live",
        tagline="See if your website is costing you customers",
        summary=(
            "Paste your URL for a free expert review — what's outdated, what it may be costing you, "
            "and a homepage redesign preview. No signup required."
        ),
        features=(
            "Free thirty-second website review",
            "Outdated element detection",
            "Homepage redesign preview",
            "No signup required",
        ),
        access="Visit nm2tech dot com slash apps and open Free Website Review",
        keywords=(
            "website review",
            "free website",
            "website audit",
            "homepage",
            "my website",
            "site review",
        ),
        url_key="website_review_url",
    ),
    Product(
        id="world_cup",
        name="World Cup 2026 Knockout Map",
        status="live",
        tagline="Live FIFA World Cup knockout tracker",
        summary=(
            "Interactive World Cup twenty twenty-six map with live scores, "
            "still-in versus eliminated teams, and MAIchael — an NM2TECH LeadBot demo."
        ),
        features=(
            "Live knockout bracket map",
            "Team elimination status",
            "MAIchael tournament assistant demo",
        ),
        access="Open from nm2tech dot com slash apps",
        keywords=("world cup", "fifa", "knockout", "soccer", "football tournament"),
        url_key="world_cup_url",
    ),
    Product(
        id="turtle_dash",
        name="Turtle Dash",
        status="live",
        tagline="Arcade game for National Night Out events",
        summary=(
            "A fun arcade game — enter your name, compete on the event leaderboard, "
            "and help the turtle jump the software bugs."
        ),
        features=("Event arcade game", "Leaderboard", "Built for community events"),
        access="Play from nm2tech dot com slash apps",
        keywords=("turtle dash", "turtle", "arcade game", "national night out"),
        url_key="turtle_dash_url",
    ),
    Product(
        id="localai_pro",
        name="LocalAI Pro",
        status="coming_soon",
        tagline="Practical AI tools for local businesses",
        summary=(
            "A growing toolkit of AI experiences tailored for Maryland businesses "
            "and community organizations. Coming soon."
        ),
        features=("Local business AI toolkit", "Maryland-focused experiences"),
        access="Coming soon — check nm2tech dot com slash apps for updates",
        keywords=("local ai", "localai", "local ai pro", "maryland ai"),
        url_key="localai_pro_url",
    ),
)


def _product_url(product: Product) -> str:
    """Return configured URL for a product, or the apps catalog fallback."""
    cfg = reload_settings()
    if product.url_key:
        url = getattr(cfg, product.url_key, "") or ""
        if url.strip():
            return url.strip()
    return (cfg.nm2tech_apps_url or "https://nm2tech.com/apps").strip()


def detect_products(text: str) -> list[Product]:
    """Return products mentioned in caller speech, best match first."""
    lowered = text.lower()
    matched: list[tuple[int, Product]] = []
    for product in PRODUCTS:
        score = 0
        for kw in product.keywords:
            if kw in lowered:
                score += len(kw)
        if score:
            matched.append((score, product))
    matched.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in matched]


def build_product_catalog_prompt() -> str:
    """Compact catalog block for the system prompt."""
    lines = [
        "NM2TECH builds practical AI apps for businesses and everyday life.",
        "Full catalog: nm2tech dot com slash apps",
        "",
        "PRODUCTS YOU CAN HELP WITH:",
    ]
    for product in PRODUCTS:
        status = "live now" if product.status == "live" else "coming soon"
        lines.append(f"- {product.name} ({status}): {product.tagline}. {product.summary}")
        if product.pricing:
            lines.append(f"  Pricing: {product.pricing}")
    lines.extend(
        [
            "",
            "WHEN THEY ASK ABOUT A SPECIFIC APP:",
            "- Explain what it does in plain language (1-2 sentences).",
            "- Tell them how to open it (browser / add to Home Screen / call this line for Phone Agent).",
            "- For Guardian: you cannot access their vault on this call — direct them to open Guardian in the browser.",
            "- For apps you cannot act on yet: offer to schedule a demo or leave a message for the team.",
            "",
            "WHEN THEY ASK ABOUT NM2TECH AI PHONE AGENT PRICING:",
            "Starter ninety-nine dollars a month, Professional one ninety-nine, Business three ninety-nine.",
        ]
    )
    return "\n".join(lines)


def build_product_context(speech: str) -> str:
    """Return extra context when the caller mentions a specific product."""
    products = detect_products(speech)
    if not products:
        return ""

    lines = ["CALLER IS ASKING ABOUT THESE NM2TECH PRODUCTS (use this — do not guess):"]
    for product in products[:2]:
        url = _product_url(product)
        lines.append(f"\n{product.name} ({product.status.replace('_', ' ')})")
        lines.append(f"Tagline: {product.tagline}")
        lines.append(f"Summary: {product.summary}")
        lines.append("Features: " + "; ".join(product.features))
        lines.append(f"How to access: {product.access}")
        if url:
            lines.append(f"URL to mention if helpful: {url}")
        if product.pricing:
            lines.append(f"Pricing: {product.pricing}")
        if product.id == "guardian":
            lines.append(
                "IMPORTANT: You cannot view, upload, or change their Guardian documents on this phone call. "
                "Help them understand the app and how to open it. For account-specific help, "
                "offer to leave a message or transfer to a person."
            )

    return "\n".join(lines)


def try_product_faq(
    speech: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> Optional[str]:
    """Fast canned answers for common product questions on the first turn."""
    if conversation_history:
        return None

    lowered = speech.lower()
    products = detect_products(speech)
    if not products:
        return None

    product = products[0]

    if product.id == "guardian":
        url = _product_url(product)
        url_hint = (
            f" Open it at {url}."
            if url and "nm2tech.com/apps" not in url
            else " Visit nm2tech dot com slash apps and tap Guardian."
        )
        return (
            "Guardian is NM2TECH's private document vault. It stores your important papers, "
            "explains them in plain language, and tracks deadlines and share links you control."
            f"{url_hint} I can't access your vault on this call — want help with something else?"
        )

    if product.id == "phone_agent" and any(w in lowered for w in ("price", "pricing", "cost", "plan")):
        return (
            "Our AI Phone Agent has three plans: Starter at ninety-nine dollars a month, "
            "Professional at one ninety-nine, and Business at three ninety-nine. "
            "Would you like to schedule a demo?"
        )

    if product.id == "receiptlens":
        return (
            "ReceiptLens AI turns phone photos of receipts into searchable expense records. "
            "Open it from nm2tech dot com slash apps and add it to your home screen. "
            "Anything else you'd like to know?"
        )

    if product.id == "website_review":
        return (
            "Our free website review checks if your site looks outdated and what it might be costing you. "
            "No signup — just paste your URL at nm2tech dot com slash apps. "
            "Want me to tell you about another NM2TECH app?"
        )

    if product.id == "localai_pro":
        return (
            "LocalAI Pro is coming soon — practical AI tools for Maryland businesses. "
            "Check nm2tech dot com slash apps for updates, or I can take a message for the team."
        )

    url = _product_url(product)
    url_part = (
        f" You can open it at {url}."
        if url and "nm2tech.com/apps" not in url
        else " Find it at nm2tech dot com slash apps."
    )
    return (
        f"{product.name} is {product.tagline.lower()}. {product.summary}"
        f"{url_part} What else can I help with?"
    )
