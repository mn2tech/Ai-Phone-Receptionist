"""Twilio voice webhook handlers and TwiML generation."""

import logging
import re
import time
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from twilio.twiml.voice_response import Gather, VoiceResponse

from app.auth import validate_twilio_signature
from app.business_profiles import BusinessProfile, get_business_by_phone
from app.tts import generate_speech_audio, get_audio

from app.cancel_flow import (
    cancel_intent_from_context,
    detect_cancel_intent,
    process_cancel_input,
    start_cancel_flow,
    try_retarget_cancel,
)
from app.booking_flow import (
    finalize_booking,
    get_booking_prompt,
    is_booking_ready_to_confirm,
    is_slot_selection,
    parse_spoken_date,
    process_booking_input,
    start_booking_flow,
    start_booking_for_speech,
    try_booking_time_followup,
)
from app.calendar_service import (
    availability_day_offset,
    build_calendar_context,
    calendar_is_ready,
    detect_availability_intent,
)
from app.ai_agent import (
    collection_complete_message,
    detect_appointment_inquiry,
    detect_availability_inquiry,
    detect_booking_intent,
    detect_flow_abort,
    detect_cancel_abort,
    detect_message_intent,
    detect_transfer_intent,
    transfer_prompt,
    generate_ai_response,
    generate_call_summary,
    get_next_collection_prompt,
    is_collection_complete,
    process_collection_input,
    should_end_call,
    try_faq_response,
)
from app.config import get_settings, reload_settings
from app.products import build_product_context
from app.local_business import build_local_business_context
from app.database import (
    cancel_latest_booking_for_phone,
    get_db_session,
    get_flow_state,
    get_demos_for_call,
    get_or_create_call,
    get_turns_for_call,
    get_voicemails_for_call,
    mark_call_completed,
    save_conversation_turn,
    save_demo_request,
    save_voicemail,
    set_flow_state,
)
from app.models import CallFlow
from app.models import CallStatus as CallStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/twilio", tags=["twilio"])

# NM2TECH-specific greetings (used when business is NM2TECH)
DEFAULT_GREETING = (
    "Hello, thank you for calling NM2TECH. "
    "I can tell you how we help local businesses with AI, or answer questions about our apps. "
    "How can I help you today?"
)

# Olney National Night Out — first Tuesday of August (2026: Aug 4)
OLNEY_NNO_DATES = frozenset({date(2026, 8, 4)})

OLNEY_NNO_GREETING = (
    "Hello, and enjoy Olney National Night Out! "
    "Thanks for calling NM2TECH. "
    "Try Turtle Dash, our arcade game for tonight, or ask about our AI apps for local businesses. "
    "How can I help you today?"
)

# Backward compatibility for imports
GREETING = DEFAULT_GREETING

# PHI redaction pattern for logging (names, phone numbers, DOB, SSN, MRN)
PHI_PATTERNS = [
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN-REDACTED]'),  # SSN
    (re.compile(r'\b\d{3}-\d{3}-\d{4}\b'), '[PHONE-REDACTED]'),  # Phone
    (re.compile(r'\b\+1\d{10}\b'), '[PHONE-REDACTED]'),  # E.164 phone
    (re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'), '[DATE-REDACTED]'),  # Dates
    (re.compile(r'\b(MRN|DOB|SSN):\s*\S+', re.IGNORECASE), r'\1: [REDACTED]'),
]

NO_SPEECH_PROMPT = (
    "I'm sorry, I didn't catch that. Could you please repeat what you need help with?"
)

NO_SPEECH_FINAL = (
    "I'm still having trouble hearing you. "
    "Thank you for calling NM2TECH. Goodbye!"
)

GOODBYE_MESSAGE = "Thank you for calling NM2TECH. Have a great day. Goodbye!"

TECHNE_GOODBYE_MESSAGE = "Thank you for calling Technē Dental. Have a great day. Goodbye!"

def _get_goodbye_message(business: BusinessProfile) -> str:
    """Get business-specific goodbye message."""
    if business.id.value == "techne_dental":
        return TECHNE_GOODBYE_MESSAGE
    return GOODBYE_MESSAGE

FILLER_PHRASE = "Just a moment."  # unused — kept for reference

# Static phrases to pre-generate TTS for (instant playback, no API wait)
_BASE_PREWARM_PHRASES = [
    NO_SPEECH_PROMPT,
    NO_SPEECH_FINAL,
    "May I have your name please?",
    "What is the best phone number to reach you?",
    "What is your business name?",
    "What date and time works best for a demo?",
    "Do you have an email address? If not, just say skip.",
    "Please leave your message after the tone, and I'll make sure someone gets back to you.",
    "One moment please, I'm connecting you now.",
    "One moment please, I'm connecting you to Michael now.",
    "Could you repeat that please?",
]


def _redact_phi(text: str) -> str:
    """Redact PHI from text for logging (applies PHI_PATTERNS)."""
    result = text
    for pattern, replacement in PHI_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def get_greeting(business: Optional[BusinessProfile] = None) -> str:
    """
    Return today's call greeting for the given business.
    
    Priority: event override > seasonal/special > business default
    """
    cfg = reload_settings()
    custom = (cfg.event_greeting or "").strip()
    if custom:
        return custom

    # NM2TECH-specific seasonal greetings
    if business and business.id.value == "nm2tech":
        tz = ZoneInfo(cfg.calendar_timezone or "America/New_York")
        today = datetime.now(tz).date()
        if today in OLNEY_NNO_DATES:
            logger.info("Using Olney National Night Out greeting for %s", today)
            return OLNEY_NNO_GREETING

    # Use business-specific default greeting
    if business:
        return business.greeting

    return DEFAULT_GREETING


def get_prewarm_phrases() -> list[str]:
    """Phrases to pre-generate TTS for — includes active and alternate greetings."""
    candidates = [get_greeting(), DEFAULT_GREETING, OLNEY_NNO_GREETING, *_BASE_PREWARM_PHRASES]
    seen: set[str] = set()
    unique: list[str] = []
    for phrase in candidates:
        if phrase not in seen:
            seen.add(phrase)
            unique.append(phrase)
    return unique


PREWARM_PHRASES = get_prewarm_phrases()


def _webhook_url(path: str) -> str:
    """Build absolute URL for Twilio action callbacks."""
    # Always read fresh from .env so ngrok URL changes take effect after restart
    base = reload_settings().base_url.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _build_extra_context(speech: str, caller_phone: str = "", *, calendar: bool = False) -> str:
    """Combine local business, product, and optional calendar context for OpenAI."""
    parts: list[str] = []
    local_ctx = build_local_business_context(speech)
    if local_ctx:
        parts.append(local_ctx)
    product_ctx = build_product_context(speech)
    if product_ctx:
        parts.append(product_ctx)
    if calendar and calendar_is_ready():
        calendar_ctx = build_calendar_context(speech, caller_phone)
        if calendar_ctx:
            parts.append(calendar_ctx)
    return "\n\n".join(parts)


def _append_speech_to_gather(gather: Gather, text: str) -> None:
    """Nest Say or Play inside Gather so barge-in can interrupt playback."""
    cfg = reload_settings()
    style = cfg.voice_style.lower()

    if style in ("openai", "natural"):
        audio_id = generate_speech_audio(text)
        if audio_id:
            gather.play(_webhook_url(f"/twilio/audio/{audio_id}"))
            return
        logger.warning("OpenAI TTS failed — falling back to Twilio")

    if style in ("robotic",):
        gather.say(text, voice="alice")
        return

    gather.say(text, voice=cfg.twilio_voice)


def _build_gather(**overrides) -> Gather:
    """Shared Gather config — long timeout so barge-in works on long agent replies."""
    cfg = reload_settings()
    params = {
        "input": "speech",
        "action": _webhook_url("/twilio/gather"),
        "method": "POST",
        "barge_in": cfg.twilio_barge_in,
        "timeout": cfg.gather_timeout,
        "speech_timeout": cfg.speech_timeout,
        "max_speech_time": cfg.gather_max_speech_time,
        "language": cfg.speech_language,
        "speech_model": "phone_call",
        "enhanced": True,
        "action_on_empty_result": True,
        "profanity_filter": False,
        "hints": cfg.gather_hints,
    }
    params.update(overrides)
    return Gather(**params)


def _speak_and_gather(response: VoiceResponse, text: str) -> VoiceResponse:
    """
    Speak text and listen — caller can interrupt (barge-in) while the agent talks.
    Say/Play must be nested inside Gather for Twilio to stop playback on speech.
    """
    gather = _build_gather()
    _append_speech_to_gather(gather, text)
    response.append(gather)
    return response


def _listen_only(response: VoiceResponse, prompt: str = "Go ahead, I'm listening.") -> VoiceResponse:
    """Listen without a long prompt — used when an interrupt may have been missed."""
    gather = _build_gather(timeout=20, speech_timeout="auto")
    gather.say(prompt, voice=reload_settings().twilio_voice)
    response.append(gather)
    return response


def _speak(response: VoiceResponse, text: str) -> None:
    """Speak text without listening (e.g. before transfer)."""
    cfg = reload_settings()
    style = cfg.voice_style.lower()

    if style in ("robotic",):
        response.say(text, voice="alice")
        return

    if style in ("openai", "natural"):
        audio_id = generate_speech_audio(text)
        if audio_id:
            response.play(_webhook_url(f"/twilio/audio/{audio_id}"))
            return
        logger.warning("OpenAI TTS failed — falling back to Twilio")

    response.say(text, voice=cfg.twilio_voice)


def _speak_and_hangup(response: VoiceResponse, text: str) -> VoiceResponse:
    """Speak a final message and end the call."""
    _speak(response, text)
    response.hangup()
    return response


def _twiml_response(voice_response: VoiceResponse) -> Response:
    """Return TwiML as a FastAPI Response."""
    return Response(content=str(voice_response), media_type="application/xml")


def _build_history(turns: list) -> list[dict[str, str]]:
    """Convert DB turns into OpenAI chat history."""
    history: list[dict[str, str]] = []
    for turn in turns:
        if turn.caller_speech:
            history.append({"role": "user", "content": turn.caller_speech})
        if turn.ai_response:
            history.append({"role": "assistant", "content": turn.ai_response})
    return history


def _get_business_from_call(flow_state: dict, to_number: str = "") -> BusinessProfile:
    """
    Retrieve business profile from call's flow_state or by called number.
    
    Falls back to NM2TECH if not found (backward compatibility).
    """
    from app.business_profiles import BusinessId, get_business_by_id, get_business_by_phone
    
    business_id_str = flow_state.get("business_id", "")
    if business_id_str:
        try:
            business_id = BusinessId(business_id_str)
            return get_business_by_id(business_id)
        except ValueError:
            logger.warning("Invalid business_id in flow_state: %r", business_id_str)
    
    # Try by called number if provided
    if to_number:
        return get_business_by_phone(to_number)
    
    # Default to NM2TECH (backward compatibility)
    return get_business_by_id(BusinessId.NM2TECH)


def _reset_flow_state_preserve_business(call: CallRecord) -> None:
    """
    Reset flow_state to empty dict but preserve business_id.
    
    Critical: business_id must persist across all flow state resets
    so the correct business context is maintained for the entire call.
    """
    current_state = get_flow_state(call)
    business_id = current_state.get("business_id", "")
    new_state = {"business_id": business_id} if business_id else {}
    set_flow_state(call, new_state)


@router.post("/voice", dependencies=[Depends(validate_twilio_signature)])
async def incoming_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(default="unknown"),
    To: str = Form(default=""),
) -> Response:
    """
    Twilio hits this when a call comes in.
    Selects business by called number and returns greeting TwiML.
    """
    business = get_business_by_phone(To)
    
    # Redact caller number from logs if PHI redaction enabled
    display_from = _redact_phi(From) if business.phi_redaction_enabled else From
    logger.info("Incoming call: sid=%s from=%s to=%s business=%s", 
                CallSid, display_from, To, business.id.value)

    with get_db_session() as session:
        call = get_or_create_call(session, call_sid=CallSid, caller_phone=From)
        # Store business ID in flow_state for later retrieval
        state = get_flow_state(call)
        state["business_id"] = business.id.value
        set_flow_state(call, state)

    response = VoiceResponse()
    _speak_and_gather(response, get_greeting(business))

    return _twiml_response(response)


@router.post("/gather", dependencies=[Depends(validate_twilio_signature)])
async def handle_gather(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(default="unknown"),
    To: str = Form(default=""),
    SpeechResult: Optional[str] = Form(default=None),
    UnstableSpeechResult: Optional[str] = Form(default=None),
    Confidence: Optional[str] = Form(default=None),
) -> Response:
    """
    Twilio sends recognized speech here.
    Generates AI reply, handles transfers, messages, and multi-turn chat.
    Uses business profile for routing and behavior.
    """
    speech = (SpeechResult or UnstableSpeechResult or "").strip()
    
    response = VoiceResponse()

    with get_db_session() as session:
        call = get_or_create_call(session, call_sid=CallSid, caller_phone=From)
        turns = get_turns_for_call(session, call_sid=CallSid)
        flow_state = get_flow_state(call)
        cfg = reload_settings()
        
        # Get business profile for this call
        business = _get_business_from_call(flow_state, To)
        
        # Redact speech from logs if PHI redaction enabled
        display_speech = _redact_phi(speech) if business.phi_redaction_enabled else speech
        logger.info(
            "Gather: sid=%s business=%s speech=%r unstable=%r confidence=%s",
            CallSid,
            business.id.value,
            display_speech[:100] if display_speech else "",
            "[REDACTED]" if business.phi_redaction_enabled else (UnstableSpeechResult or "")[:100],
            Confidence,
        )

        # --- No speech detected (often a missed barge-in — listen again briefly) ---
        if not speech:
            call.no_speech_count += 1
            if call.no_speech_count == 1:
                save_conversation_turn(
                    session, CallSid, caller_speech="[no speech]", ai_response="[listening retry]"
                )
                return _twiml_response(_listen_only(response))
            save_conversation_turn(session, CallSid, caller_speech="[no speech]", ai_response=NO_SPEECH_FINAL)
            mark_call_completed(session, call, status=CallStatusEnum.COMPLETED.value)
            return _twiml_response(_speak_and_hangup(response, NO_SPEECH_FINAL))

        # Reset no-speech counter when we got input
        call.no_speech_count = 0

        # --- Caller wants to end the call ---
        if should_end_call(speech, call.flow, flow_state, turns):
            logger.info("Caller ending call: sid=%s speech=%r", CallSid, speech[:60])
            goodbye = _get_goodbye_message(business)
            save_conversation_turn(session, CallSid, speech, goodbye)
            mark_call_completed(session, call, status=CallStatusEnum.COMPLETED.value)
            return _twiml_response(_speak_and_hangup(response, goodbye))

        # --- Abort any active flow when caller changes their mind ---
        aborted_flow = False
        if call.flow != CallFlow.NORMAL.value and detect_flow_abort(speech):
            logger.info("Caller aborted flow %s: %r", call.flow, speech[:60])
            call.flow = CallFlow.NORMAL.value
            _reset_flow_state_preserve_business(call)
            flow_state = get_flow_state(call)
            aborted_flow = True

        # --- Transfer intent (business-specific) ---
        if detect_transfer_intent(speech):
            # Techne: check if it's an emergency (use emergency_transfer), else take message
            if business.id.value == "techne_dental":
                # Techne doesn't transfer to general number - only emergency_transfer for urgent cases
                # If not emergency, offer to take a message
                ai_text = (
                    "I'd be happy to help you with that. "
                    "Would you like to leave a message for the team, or is this an urgent matter?"
                )
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))
            
            # NM2TECH: use business-specific transfer number
            dest = business.transfer_number or (cfg.transfer_phone_number or "").strip()
            
            # Normalize phone number to E.164 if needed
            if dest and not dest.startswith("+"):
                digits = "".join(c for c in dest if c.isdigit())
                if len(digits) == 10:
                    dest = f"+1{digits}"
                elif len(digits) == 11 and digits.startswith("1"):
                    dest = f"+{digits}"
            
            if not dest:
                ai_text = (
                    "I'd like to transfer you, but transfer is not available right now. "
                    "Would you like to leave a message instead?"
                )
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            ai_text = transfer_prompt(speech)
            save_conversation_turn(session, CallSid, speech, ai_text)
            call.status = CallStatusEnum.TRANSFERRED.value
            _speak(response, ai_text)
            caller_id = (cfg.twilio_phone_number or "").strip()
            # Always show the NM2TECH number. If we pass the caller's ID and they
            # are calling from Michael's Google Fi phone, Fi treats it as
            # "check my voicemail" and asks for a PIN.
            logger.info(
                "Transferring call %s to %s (caller_id=%s)",
                CallSid,
                dest,
                caller_id or "default",
            )
            dial_kwargs: dict = {
                "timeout": 22,
                "action": _webhook_url("/twilio/transfer-status"),
                "method": "POST",
                "hangup_on_star": True,
                "answer_on_bridge": True,
            }
            if caller_id:
                dial_kwargs["caller_id"] = caller_id
            response.dial(dest, **dial_kwargs)
            return _twiml_response(response)

        # --- Live calendar booking flow ---
        if call.flow == CallFlow.BOOKING_DEMO.value:
            # Caller asking about other dates/times — not picking from the list
            if (
                flow_state.get("step") == "slot_choice"
                and detect_appointment_inquiry(speech)
                and not is_slot_selection(speech, flow_state)
            ):
                logger.info("Booking flow → calendar inquiry: %r", speech[:60])
                call.flow = CallFlow.NORMAL.value
                _reset_flow_state_preserve_business(call)
                history = _build_history(turns)
                extra_ctx = _build_extra_context(speech, From, calendar=True)
                t0 = time.perf_counter()
                ai_text = generate_ai_response(speech, history, extra_context=extra_ctx, business=business)
                logger.info("OpenAI calendar inquiry (from booking) in %.2fs", time.perf_counter() - t0)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            flow_state, error = process_booking_input(flow_state, speech)
            if error:
                ai_text = error
                set_flow_state(call, flow_state)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            if is_booking_ready_to_confirm(flow_state) or flow_state.get("booking_status") == "confirming":
                if flow_state.get("booking_status") == "confirmed":
                    ai_text = flow_state.get(
                        "confirmation_message",
                        "That appointment is already confirmed.",
                    )
                    call.flow = CallFlow.NORMAL.value
                    _reset_flow_state_preserve_business(call)
                    save_conversation_turn(session, CallSid, speech, ai_text)
                    return _twiml_response(_speak_and_gather(response, ai_text))

                if flow_state.get("booking_status") != "confirming":
                    flow_state["booking_status"] = "confirming"
                    set_flow_state(call, flow_state)
                    session.flush()

                ok, ai_text = finalize_booking(flow_state)
                set_flow_state(call, flow_state)
                session.flush()
                if ok:
                    slot_iso = flow_state.get("selected_slot", "")
                    try:
                        tz = ZoneInfo(flow_state.get("timezone", "America/New_York"))
                        slot_dt = datetime.fromisoformat(slot_iso).astimezone(tz)
                        preferred = (
                            f"{slot_dt.strftime('%A %B %d')} at "
                            f"{slot_dt.strftime('%I:%M %p').lstrip('0')}"
                        )
                    except ValueError:
                        preferred = slot_iso

                    if not flow_state.get("demo_saved"):
                        save_demo_request(
                            session,
                            call_sid=CallSid,
                            caller_name=flow_state.get("name", ""),
                            business_name="",
                            caller_phone=From,
                            preferred_time=preferred,
                            email="",
                            status="booked",
                        )
                        flow_state["demo_saved"] = True
                    call.flow = CallFlow.NORMAL.value
                    _reset_flow_state_preserve_business(call)
                else:
                    flow_state["step"] = "slot_choice"
                    flow_state.pop("selected_slot", None)
                    flow_state.pop("name", None)
                    flow_state.pop("booking_status", None)
                    set_flow_state(call, flow_state)
            else:
                ai_text = get_booking_prompt(flow_state) or "Could you repeat that please?"
                set_flow_state(call, flow_state)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Cancel appointment flow ---
        if call.flow == CallFlow.CANCELLING_APPOINTMENT.value:
            if detect_cancel_abort(speech):
                ai_text = "Okay, your appointment is still scheduled. Anything else I can help with?"
                call.flow = CallFlow.NORMAL.value
                _reset_flow_state_preserve_business(call)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            recent_hint = " ".join(
                t.caller_speech for t in turns[-4:] if t.caller_speech and t.caller_speech != "[no speech]"
            )
            retarget_state, retarget_prompt = try_retarget_cancel(From, speech, recent_hint)
            if retarget_prompt is not None:
                if retarget_state:
                    flow_state = retarget_state
                    set_flow_state(call, flow_state)
                else:
                    call.flow = CallFlow.NORMAL.value
                    _reset_flow_state_preserve_business(call)
                ai_text = retarget_prompt
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            flow_state, error, success = process_cancel_input(flow_state, speech)
            if error:
                ai_text = error
                set_flow_state(call, flow_state)
            elif success:
                ai_text = success
                cancel_latest_booking_for_phone(session, From)
                call.flow = CallFlow.NORMAL.value
                _reset_flow_state_preserve_business(call)
            else:
                ai_text = "Should I cancel your appointment? Say yes or no."
                set_flow_state(call, flow_state)
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Active collection flow (message, demo, or dental appointment) ---
        if call.flow in (CallFlow.TAKING_MESSAGE.value, CallFlow.TAKING_DEMO.value):
            # Techne uses dental appointment flow, NM2TECH uses demo flow
            if call.flow == CallFlow.TAKING_DEMO.value and business.id.value == "techne_dental":
                # Dental appointment collection
                from app.dental_flow import (
                    process_dental_input,
                    is_dental_collection_complete,
                    get_next_dental_prompt,
                    dental_complete_message,
                )
                
                flow_state = process_dental_input(flow_state, speech)
                set_flow_state(call, flow_state)
                
                if is_dental_collection_complete(flow_state):
                    # Save dental appointment request
                    save_demo_request(
                        session,
                        call_sid=CallSid,
                        caller_name=flow_state.get("name", ""),
                        business_name="",  # Not collected for dental
                        caller_phone=flow_state.get("phone", From),
                        preferred_time=flow_state.get("preferred_times", ""),
                        email="",  # Not collected for dental
                        status="pending",
                    )
                    ai_text = dental_complete_message(flow_state)
                    call.flow = CallFlow.NORMAL.value
                    _reset_flow_state_preserve_business(call)
                    save_conversation_turn(session, CallSid, speech, ai_text)
                    return _twiml_response(_speak_and_gather(response, ai_text))
                
                # Ask next dental question
                ai_text = get_next_dental_prompt(flow_state) or "Could you repeat that please?"
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))
            
            # NM2TECH demo flow or message flow
            flow_state = process_collection_input(call.flow, flow_state, speech)
            set_flow_state(call, flow_state)

            if is_collection_complete(call.flow, flow_state):
                if call.flow == CallFlow.TAKING_MESSAGE.value:
                    save_voicemail(
                        session,
                        call_sid=CallSid,
                        caller_name=flow_state.get("name", ""),
                        caller_phone=flow_state.get("phone", From),
                        message_text=flow_state.get("message", ""),
                    )
                elif call.flow == CallFlow.TAKING_DEMO.value:
                    save_demo_request(
                        session,
                        call_sid=CallSid,
                        caller_name=flow_state.get("name", ""),
                        business_name=flow_state.get("business_name", ""),
                        caller_phone=flow_state.get("phone", From),
                        preferred_time=flow_state.get("preferred_time", ""),
                        email=flow_state.get("email", ""),
                    )
                ai_text = collection_complete_message(call.flow, flow_state)
                call.flow = CallFlow.NORMAL.value
                _reset_flow_state_preserve_business(call)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

            # Ask next collection question
            ai_text = get_next_collection_prompt(call.flow, flow_state) or (
                "Could you repeat that please?"
            )
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        recent_hint = " ".join(
            t.caller_speech for t in turns[-4:] if t.caller_speech and t.caller_speech != "[no speech]"
        )

        # --- Cancel appointment intent (NM2TECH only - Techne has no calendar) ---
        if business.calendar_enabled and calendar_is_ready() and cancel_intent_from_context(speech, recent_hint):
            flow_state, ai_text = start_cancel_flow(From, speech, recent_hint)
            if flow_state:
                call.flow = CallFlow.CANCELLING_APPOINTMENT.value
                set_flow_state(call, flow_state)
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Explicit booking request — real calendar flow first (NM2TECH) or request-only (Techne) ---
        if detect_booking_intent(speech):
            from app.business_profiles import BookingStrategy
            
            # Techne Dental: request-only mode (no live calendar booking)
            if business.booking_strategy == BookingStrategy.REQUEST_ONLY:
                call.flow = CallFlow.TAKING_DEMO.value
                _reset_flow_state_preserve_business(call)
                ai_text = (
                    "I'll be happy to help you with that. "
                    "May I have your name please?"
                )
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))
            
            # NM2TECH: live calendar booking if enabled and available
            if business.calendar_enabled and calendar_is_ready():
                day_offset = (
                    availability_day_offset(speech) if detect_availability_intent(speech) else None
                )
                flow_state, ai_text = start_booking_flow(
                    day_offset=day_offset, caller_phone=From
                )
                if flow_state:
                    call.flow = CallFlow.BOOKING_DEMO.value
                    set_flow_state(call, flow_state)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))
            call.flow = CallFlow.TAKING_DEMO.value
            _reset_flow_state_preserve_business(call)
            ai_text = get_next_collection_prompt(CallFlow.TAKING_DEMO.value, {}) or (
                "May I have your name please?"
            )
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Caller picked a specific date — real booking flow (NM2TECH only) ---
        if business.calendar_enabled and calendar_is_ready() and parse_spoken_date(speech, conversation_hint=recent_hint):
            flow_state, ai_text = start_booking_for_speech(
                speech, caller_phone=From, conversation_hint=recent_hint
            )
            if flow_state:
                call.flow = CallFlow.BOOKING_DEMO.value
                set_flow_state(call, flow_state)
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Open times / availability — live booking flow (NM2TECH only) ---
        if business.calendar_enabled and calendar_is_ready() and detect_availability_inquiry(speech):
            if parse_spoken_date(speech, conversation_hint=recent_hint):
                flow_state, ai_text = start_booking_for_speech(
                    speech, caller_phone=From, conversation_hint=recent_hint
                )
            else:
                day_offset = (
                    availability_day_offset(speech)
                    if any(w in speech.lower() for w in ("today", "tomorrow"))
                    else None
                )
                flow_state, ai_text = start_booking_flow(
                    day_offset=day_offset, caller_phone=From
                )
            if flow_state:
                call.flow = CallFlow.BOOKING_DEMO.value
                set_flow_state(call, flow_state)
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Caller picked a time after an availability reply (NM2TECH only) ---
        if business.calendar_enabled and calendar_is_ready() and call.flow == CallFlow.NORMAL.value:
            last_ai = ""
            for turn in reversed(turns):
                resp = turn.ai_response or ""
                if resp and resp not in ("[listening retry]",):
                    last_ai = resp
                    break
            flow_state, ai_text = try_booking_time_followup(
                speech, recent_hint, last_ai, caller_phone=From
            )
            if flow_state or ai_text:
                if flow_state:
                    call.flow = CallFlow.BOOKING_DEMO.value
                    set_flow_state(call, flow_state)
                save_conversation_turn(session, CallSid, speech, ai_text)
                return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Existing appointment questions — OpenAI with live calendar data (NM2TECH only) ---
        if business.calendar_enabled and calendar_is_ready() and detect_appointment_inquiry(speech):
            history = _build_history(turns)
            extra_ctx = _build_extra_context(speech, From, calendar=True)
            t0 = time.perf_counter()
            ai_text = generate_ai_response(speech, history, extra_context=extra_ctx, business=business)
            logger.info("OpenAI calendar inquiry in %.2fs", time.perf_counter() - t0)
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Start message flow ---
        if detect_message_intent(speech):
            call.flow = CallFlow.TAKING_MESSAGE.value
            _reset_flow_state_preserve_business(call)
            ai_text = get_next_collection_prompt(CallFlow.TAKING_MESSAGE.value, {}) or (
                "May I have your name please?"
            )
            save_conversation_turn(session, CallSid, speech, ai_text)
            return _twiml_response(_speak_and_gather(response, ai_text))

        # --- Normal AI conversation ---
        history = _build_history(turns)
        faq_answer = try_faq_response(speech, history)
        if faq_answer:
            ai_text = faq_answer
            logger.info("FAQ fast-path response (no OpenAI)")
        else:
            extra_ctx = _build_extra_context(speech, From)
            t0 = time.perf_counter()
            ai_text = generate_ai_response(speech, history, extra_context=extra_ctx, business=business)
            logger.info("OpenAI response in %.2fs", time.perf_counter() - t0)
        save_conversation_turn(session, CallSid, speech, ai_text)

    return _twiml_response(_speak_and_gather(response, ai_text))


@router.post("/process")
async def process_ai_reply(
    CallSid: str = Form(...),
    From: str = Form(default="unknown"),
) -> Response:
    """Legacy endpoint — redirects to gather if hit directly."""
    response = VoiceResponse()
    return _twiml_response(
        _speak_and_gather(response, "Sorry, could you repeat your question?")
    )


@router.post("/transfer-status", dependencies=[Depends(validate_twilio_signature)])
async def transfer_status(
    CallSid: str = Form(...),
    From: str = Form(default="unknown"),
    DialCallStatus: str = Form(default=""),
) -> Response:
    """
    After a transfer Dial ends: if Michael didn't answer, offer to take a message
    instead of dumping the caller into Google Fi voicemail.
    """
    status = (DialCallStatus or "").lower()
    logger.info("Transfer Dial ended: sid=%s dial_status=%s", CallSid, status)
    response = VoiceResponse()

    if status in ("completed", "answered"):
        # Get business for goodbye message
        with get_db_session() as session:
            call = get_or_create_call(session, call_sid=CallSid, caller_phone=From)
            flow_state = get_flow_state(call)
        business = _get_business_from_call(flow_state)
        goodbye = _get_goodbye_message(business)
        return _twiml_response(_speak_and_hangup(response, goodbye))

    with get_db_session() as session:
        call = get_or_create_call(session, call_sid=CallSid, caller_phone=From)
        call.flow = CallFlow.TAKING_MESSAGE.value
        _reset_flow_state_preserve_business(call)
        call.status = CallStatusEnum.IN_PROGRESS.value
        ai_text = (
            "I wasn't able to reach Michael. "
            "I can take a message for him. May I have your name please?"
        )
        save_conversation_turn(session, CallSid, "[transfer ended]", ai_text)

    return _twiml_response(_speak_and_gather(response, ai_text))


@router.get("/audio/{audio_id}")
async def serve_audio(audio_id: str) -> Response:
    """Serve OpenAI TTS MP3 files for Twilio <Play>."""
    audio = get_audio(audio_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/status", dependencies=[Depends(validate_twilio_signature)])
async def call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(default=""),  # noqa: N803 — Twilio form field name
    From: str = Form(default="unknown"),
) -> dict[str, str]:
    """
    Twilio status callback when a call completes.
    Generates and saves a call summary.
    """
    twilio_status = CallStatus
    logger.info("Status callback: sid=%s status=%s", CallSid, twilio_status)

    terminal_statuses = {"completed", "busy", "failed", "no-answer", "canceled"}

    if twilio_status.lower() not in terminal_statuses:
        return {"status": "ignored"}

    with get_db_session() as session:
        call = get_or_create_call(session, call_sid=CallSid, caller_phone=From)
        turns = get_turns_for_call(session, call_sid=CallSid)
        voicemails = get_voicemails_for_call(session, call_sid=CallSid)
        demos = get_demos_for_call(session, call_sid=CallSid)

        summary = generate_call_summary(From, turns, voicemails, demos)
        call.summary = summary

        if call.status != CallStatusEnum.TRANSFERRED.value:
            mark_call_completed(session, call, status=CallStatusEnum.COMPLETED.value)

        logger.info("Call %s summary saved: %s", CallSid, summary[:120])

    return {"status": "ok"}
