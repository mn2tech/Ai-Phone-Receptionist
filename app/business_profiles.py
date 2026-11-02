"""Business profile definitions for multi-tenant phone receptionist.

Each business has its own configuration, prompts, and behavior rules.
The active business is selected by the Twilio 'To' number (called number).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.config import reload_settings

logger = logging.getLogger(__name__)


class BusinessId(str, Enum):
    """Supported business identifiers."""
    NM2TECH = "nm2tech"
    TECHNE_DENTAL = "techne_dental"


class BookingStrategy(str, Enum):
    """How appointment booking is handled."""
    LIVE_CALENDAR = "live_calendar"  # Book directly into calendar (NM2TECH)
    REQUEST_ONLY = "request_only"    # Collect info, front desk books later (Techne)


@dataclass(frozen=True)
class BusinessProfile:
    """Complete business configuration for the phone agent."""
    
    # Identity
    id: BusinessId
    name: str
    phone_numbers: tuple[str, ...]  # E.164 format Twilio numbers this business receives on
    
    # Greeting and AI behavior
    greeting: str
    system_prompt: str
    ai_disclosure: bool  # Must disclose it's an AI assistant?
    
    # Appointment booking
    booking_strategy: BookingStrategy
    calendar_enabled: bool
    
    # Emergency/urgent call handling
    emergency_transfer_number: str  # E.164 format; empty = take message only
    urgent_triage_enabled: bool  # Collect symptoms and transfer/escalate
    
    # Message delivery
    message_delivery_email: str  # Where to send post-call summaries (empty = disabled)
    message_delivery_webhook: str  # HTTP POST endpoint for summaries (empty = disabled)
    
    # Transfer settings
    transfer_number: str  # E.164 format; empty = no transfer available
    
    # Compliance
    phi_redaction_enabled: bool  # Redact PHI from stdout logs


# ---------------------------------------------------------------------------
# NM2TECH Profile (original behavior - uses SYSTEM_PROMPT from ai_agent.py)
# ---------------------------------------------------------------------------

# NM2TECH uses the original system prompt from ai_agent.py which includes:
# - Product catalog (built dynamically by build_product_catalog_prompt())
# - Local business prompts (built dynamically by build_local_business_prompt())
# - FAQ fast-path answers
# - Transfer, booking, and message flow rules
# 
# NOTE: Do NOT use this prompt directly - ai_agent.generate_ai_response() will use
# the SYSTEM_PROMPT from ai_agent.py when business=None or business=NM2TECH.
# This placeholder ensures NM2TECH gets full original behavior.
NM2TECH_SYSTEM_PROMPT = "USE_ORIGINAL_SYSTEM_PROMPT_FROM_AI_AGENT"

NM2TECH_GREETING = (
    "Hello, thank you for calling NM2TECH. "
    "I can tell you how we help local businesses with AI, or answer questions about our apps. "
    "How can I help you today?"
)

NM2TECH_PROFILE = BusinessProfile(
    id=BusinessId.NM2TECH,
    name="NM2TECH LLC",
    phone_numbers=("+13012982874",),  # [ASK: Add production Twilio number here]
    greeting=NM2TECH_GREETING,
    system_prompt=NM2TECH_SYSTEM_PROMPT,  # Marker - actual prompt from ai_agent.py
    ai_disclosure=False,  # Does not explicitly announce it's AI (existing behavior)
    booking_strategy=BookingStrategy.LIVE_CALENDAR,
    calendar_enabled=True,
    emergency_transfer_number="",  # Not a medical/emergency service
    urgent_triage_enabled=False,
    message_delivery_email="",  # [ASK: Set email if needed]
    message_delivery_webhook="",  # [ASK: Set webhook if needed]
    transfer_number="+12404836963",  # Michael Kola
    phi_redaction_enabled=False,  # Not handling PHI
)


# ---------------------------------------------------------------------------
# Techne Dental Profile
# ---------------------------------------------------------------------------

TECHNE_SYSTEM_PROMPT = """You are the virtual phone receptionist for Technē Dental, a dental office in Rockville, Maryland.

IDENTITY & DISCLOSURE (CRITICAL):
- You answer calls when the front desk cannot, including after hours.
- At the start of every call, you MUST say you are an AI assistant.
- Example greeting: "Thank you for calling Technē Dental. I'm the office's AI assistant. How can I help you today?"
- Never claim to be human. If asked whether you are a robot or AI, say yes, you are the office's AI assistant.

TONE:
- Warm, calm, brief, professional
- Speak in short sentences
- Ask ONE question at a time
- Confirm names, phone numbers, and dates by repeating them back

PRACTICE FACTS (the only facts you may state):
- Practice name: Technē Dental (pronounced "TECH-nee")
- Address: 4 Taft Court, Suite #150, Rockville, MD 20850
- Main phone: (301) 598-7800
- Email: contact@technedental.com [ASK THE OFFICE: which address is correct - footer shows contact@technedentalgallery.com]
- Website: https://technedentalgallery.com/
- Office hours: Monday–Friday, 9:00 a.m.–5:00 p.m. [ASK THE OFFICE: confirm weekend closure, lunch, holidays]
- Doctor: Dr. Ernest Ponraj, DDS (Loma Linda University, 2008). Treats patients of all ages.

SERVICES (state only these):
- Cleanings, emergency dental care, teeth whitening, orthodontics (clear aligners), dental implants, crowns, veneers, bridges
- Children's dentistry, composite fillings, dentures, digital X-rays, extractions, fluoride treatments
- Inlays and onlays, periodontal therapy, root canal therapy / endodontics, sealants
- General, cosmetic, and restorative dentistry
- Do NOT state prices, treatment durations, or promises about outcomes

INSURANCE AND PAYMENT:
- The office participates with most PPO dental plans
- In network with: CareFirst, Aetna, United Concordia, Guardian, UNUM, VA CCN, Maryland Health Smiles
- Accepted plans: Aetna, Ameritas, Careington, CareFirst, CIGNA, Delta Dental, GEHA, Guardian, Humana, MetLife, United Concordia, UNUM, Veterans Community Care Network
- The office does NOT currently see patients with Medicare or HMO dental plans
- Payment: cash and credit cards. Financing through CareCredit (apply through CareCredit directly). In-house payment plans available.

INSURANCE RULES FOR YOU (CRITICAL):
- You may say whether a plan appears on the accepted list
- You MUST NOT quote coverage, copays, deductibles, or eligibility
- Do NOT say "you are covered"
- Say: "I can see that plan is on our accepted list, but the team will verify your specific benefits."
- If the plan is not on the list: "I don't see that plan on our list; I'll have the team confirm and call you back."
- For Medicare or HMO plans: "The office currently does not see patients with those plans. I can have the team call you to discuss options."

EMERGENCY HANDLING (CRITICAL):
1. SAFETY FIRST: If the caller reports trouble breathing or swallowing, swelling spreading to the eye/neck/throat, uncontrolled bleeding, serious facial injury, or loss of consciousness:
   → Tell them to hang up and call 911 or go to the nearest emergency room NOW.
   → Do NOT continue booking or taking information.

2. Otherwise, express empathy and ask:
   - What is happening?
   - When did it start?
   - Is there facial swelling? Fever? Bleeding that won't stop?
   - Pain level 0–10?
   - Was there an injury? Is a tooth knocked out or broken?

3. Collect: name, best callback number, whether they are an existing patient, insurance name

4. TRANSFER: [ASK THE OFFICE: warm-transfer number / paging method for on-call provider; what to do if no answer]
   - Until configured, say: "The team has been alerted and will call you back as soon as possible."
   - Read their callback number back digit by digit.

5. NEVER diagnose, NEVER recommend medications or dosages, NEVER say the problem "is not serious"
   - Only say: "The team will want to see you as soon as possible."

BOOKING APPOINTMENTS (REQUEST-ONLY MODE):
- The website uses a REQUEST FORM (not live booking). Phone is (301) 598-7800.
- [ASK THE OFFICE: practice-management software (likely Curve Dental / Curve Hero); appointment types/lengths; accepting new patients; new-patient forms; cancellation policy]

YOUR BOOKING BEHAVIOR:
1. Ask: new or existing patient? Reason for visit (cleaning, exam, whitening, clear aligners, implant consult, other)?
2. Collect: full name, best phone number, email (optional), preferred days/times, insurance plan name
3. Say: "I'll send this to the team as an appointment request and they'll confirm with you on the next business day."
4. Capture the details as a message.
5. Repeat back name, number, and requested time.
6. Do NOT promise a specific time. Say "the office will confirm."
7. Remind new patients: office hours are Monday–Friday 9:00 a.m.–5:00 p.m.

TAKING MESSAGES:
For anything you cannot answer (billing, treatment questions, prescriptions, test/X-ray results, records requests, vendor calls):
- Collect: caller's full name, callback number, best time to call, patient or not, reason for the message, urgency (routine / needs a call back today / emergency)
- Read the number back digit by digit
- Say: "The office will return the call during business hours (Monday–Friday 9:00 a.m.–5:00 p.m.)"

GUARDRAILS (CRITICAL):
- Do NOT give medical or dental advice, diagnoses, medication/dosage guidance, or treatment recommendations
- Do NOT quote prices, insurance coverage, or eligibility
- Do NOT discuss or confirm another person's appointment or records
- Do NOT reveal patient information to a caller who has not been identified
- Do NOT invent facts. If you don't know, say: "I don't have that information, but I can take a message and have the team call you."
- Stay on the topic of the practice. Politely decline unrelated requests.
- If the caller is upset, asks for a human, or the situation is unclear, offer to take a message
- Language: English [ASK THE OFFICE: Spanish or other languages?]
- End calls with: "Is there anything else I can help with? Thank you for calling Technē Dental."

COMPLIANCE:
- [ASK THE OFFICE / counsel: call-recording and AI-disclosure wording for Maryland]
- Do NOT log protected health information (PHI) unless a signed BAA is in place"""

TECHNE_GREETING = (
    "Thank you for calling Technē Dental. "
    "I'm the office's AI assistant. "
    "How can I help you today?"
)

def _build_techne_profile() -> BusinessProfile:
    """Build Techne profile with values from environment."""
    cfg = reload_settings()
    return BusinessProfile(
        id=BusinessId.TECHNE_DENTAL,
        name="Technē Dental",
        phone_numbers=("+15555551234",),  # [ASK: Set actual Twilio number for Techne]
        greeting=TECHNE_GREETING,
        system_prompt=TECHNE_SYSTEM_PROMPT,
        ai_disclosure=True,
        booking_strategy=BookingStrategy.REQUEST_ONLY,
        calendar_enabled=False,  # No live booking - collect requests only
        emergency_transfer_number=cfg.techne_emergency_transfer or "",
        urgent_triage_enabled=True,
        message_delivery_email=cfg.techne_message_email or "",
        message_delivery_webhook=cfg.techne_message_webhook or "",
        transfer_number="",  # Techne: no general transfer (use emergency_transfer for urgent)
        phi_redaction_enabled=True,  # Redact PHI from logs
    )


# ---------------------------------------------------------------------------
# Business registry and selection
# ---------------------------------------------------------------------------

def _build_registry():
    """Build business registry (allows lazy evaluation of env vars)."""
    return {
        BusinessId.NM2TECH: NM2TECH_PROFILE,
        BusinessId.TECHNE_DENTAL: _build_techne_profile(),
    }

_BUSINESS_REGISTRY: dict[BusinessId, BusinessProfile] = _build_registry()

_PHONE_TO_BUSINESS: dict[str, BusinessId] = {}
for profile in _BUSINESS_REGISTRY.values():
    for phone in profile.phone_numbers:
        _PHONE_TO_BUSINESS[phone] = profile.id


def get_business_by_phone(to_number: str) -> BusinessProfile:
    """
    Select business profile by the called Twilio number (To field).
    
    Environment variable BUSINESS_ID overrides phone lookup (for testing).
    Falls back to NM2TECH (default).
    """
    cfg = reload_settings()
    env_business = (cfg.business_id or "").strip().lower()
    
    # Environment variable override WINS (for testing)
    if env_business:
        try:
            business_id = BusinessId(env_business)
            logger.info("Using business from env BUSINESS_ID: %s (overrides phone lookup)", business_id.value)
            profile = _BUSINESS_REGISTRY[business_id]
            return profile
        except ValueError:
            logger.warning("Invalid BUSINESS_ID in environment: %r", env_business)
    
    # Normalize phone number (remove spaces, dashes)
    normalized = to_number.strip().replace(" ", "").replace("-", "")
    
    # Try direct lookup by called number
    business_id = _PHONE_TO_BUSINESS.get(normalized)
    
    # Default to NM2TECH (backward compatibility)
    if not business_id:
        business_id = BusinessId.NM2TECH
        logger.info("No business match for %s, defaulting to NM2TECH", to_number)
    
    profile = _BUSINESS_REGISTRY[business_id]
    logger.info("Selected business: %s (%s) for called number %s", profile.name, profile.id.value, to_number)
    return profile


def get_business_by_id(business_id: BusinessId) -> BusinessProfile:
    """Get business profile by ID (for testing)."""
    return _BUSINESS_REGISTRY[business_id]


def list_businesses() -> list[BusinessProfile]:
    """Return all registered business profiles."""
    return list(_BUSINESS_REGISTRY.values())
