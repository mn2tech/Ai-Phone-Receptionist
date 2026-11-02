# Security Audit & Code Review — NM2TECH AI Phone Agent

**Review Date:** November 2, 2026  
**Reviewer:** Cloud Agent  
**Scope:** Multi-tenant phone receptionist implementation and security assessment

---

## Executive Summary

The NM2TECH AI Phone Agent is a Twilio-based voice receptionist that uses OpenAI for conversation. This review identified **4 high-priority** and **2 medium-priority** security issues that should be addressed before handling protected health information (PHI) for Techne Dental.

**Current State:** Suitable for NM2TECH demo use. **Not HIPAA-ready** without remediation.

---

## How the System Works

### Call Flow
```
Caller dials Twilio number
    ↓
POST /twilio/voice
    → Business selected by 'To' number (called number)
    → TwiML greeting returned
    ↓
Caller speaks → Twilio transcribes speech
    ↓
POST /twilio/gather
    → Speech sent to OpenAI with business-specific system prompt
    → AI response converted to TwiML (Say/Play)
    → Gather listens for next input (loop)
    ↓
Transfer intent? → Dial out to configured number
Message intent? → Collect name/phone/message (structured flow)
Booking intent? → Live calendar (NM2TECH) or request-only (Techne)
    ↓
Call ends → POST /twilio/status
    → Generate AI summary (OpenAI)
    → Save to database
```

### Business Configuration (`app/business_profiles.py`)
- **BusinessProfile** dataclass defines behavior per business:
  - `phone_numbers`: tuple of Twilio numbers (E.164 format)
  - `greeting`, `system_prompt`: business-specific AI behavior
  - `booking_strategy`: LIVE_CALENDAR (NM2TECH) or REQUEST_ONLY (Techne)
  - `transfer_number`, `emergency_transfer_number`
  - `phi_redaction_enabled`: redact PHI from logs
  - `message_delivery_email`, `message_delivery_webhook`

- Business selection: `get_business_by_phone(to_number)`
  1. Lookup by called Twilio number (`To` field)
  2. Fall back to `BUSINESS_ID` env var (testing override)
  3. Default to NM2TECH (backward compatibility)

### Data Storage (`phone_agent.db` / Postgres)
Tables:
- `calls`: call_sid, caller_phone, status, flow, flow_state (JSON), summary
- `conversation_turns`: call_sid, caller_speech, ai_response, created_at
- `voicemail_messages`: call_sid, caller_name, caller_phone, message_text
- `demo_requests`: call_sid, caller_name, business_name, caller_phone, preferred_time, email, status

**PHI Storage:**
- Techne Dental: caller_phone (phone number), caller_name, message_text (may contain symptoms/DOB), conversation_turns (full transcript including medical details)
- All PHI stored in plaintext
- No encryption at rest configured

### Deployment
- **Procfile:** `web: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`
- Railway / Render auto-deploy from `main` branch
- Environment variables set in hosting dashboard
- Single shared database (SQLite local, Postgres production)

---

## Security Findings

### 🔴 CRITICAL: No Twilio Signature Validation

**Issue:** Webhook endpoints (`/twilio/voice`, `/twilio/gather`, `/twilio/status`) accept unauthenticated POST requests. Anyone can forge Twilio webhooks.

**Impact:**
- Attacker can inject fake calls into the database
- Spam call summaries / messages
- Trigger OpenAI API calls (cost)
- Harvest AI responses by crafting malicious `SpeechResult` payloads

**Location:** `app/twilio_routes.py` — no signature validation in any handler

**Remediation:**
```python
from twilio.request_validator import RequestValidator

def validate_twilio_request(request: Request, cfg: Settings):
    validator = RequestValidator(cfg.twilio_auth_token)
    url = str(request.url)
    post_vars = dict(request.form)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, post_vars, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
```
Apply to all `/twilio/*` routes.

**References:**
- https://www.twilio.com/docs/usage/security#validating-requests
- https://github.com/twilio/twilio-python

---

### 🔴 HIGH: Plaintext PHI in Database and Logs

**Issue:** Protected Health Information (PHI) is stored unencrypted and logged to stdout.

**PHI Stored:**
- Caller phone numbers (all businesses)
- Caller names
- Conversation transcripts (may contain symptoms, DOB, SSN, insurance details)
- Voicemail messages

**Logging Examples:**
```python
# app/twilio_routes.py
logger.info("Incoming call: sid=%s from=%s to=%s", CallSid, From, To)
# Logs caller phone number directly

# app/database.py
save_conversation_turn(session, CallSid, caller_speech, ai_response)
# Full transcript saved verbatim
```

**Implemented Mitigation (Partial):**
- `business_profiles.py`: `phi_redaction_enabled=True` for Techne Dental
- `twilio_routes.py`: `_redact_phi()` function redacts SSN, phone, dates from logs
- **BUT:** Database storage still plaintext

**What's Still Missing:**
1. Encryption at rest (database-level or application-level)
2. Redaction in call summaries sent via email/webhook
3. Access controls on `/calls` API (currently public)
4. Audit logging for PHI access

**Recommendations:**
1. Enable Postgres encryption at rest (Supabase, AWS RDS encryption)
2. Encrypt `caller_phone`, `caller_name`, `message_text`, `caller_speech`, `ai_response` before insert
3. Add authentication to `/calls`, `/calls/{sid}`, `/demos` endpoints (API key or OAuth)
4. Sign BAA with Twilio, OpenAI, and hosting provider **before** handling real patient data
5. Document retention policy (delete calls after 30/60/90 days)

---

### 🔴 HIGH: No Authentication on API Endpoints

**Issue:** Anyone can list calls, view transcripts, and see PHI via public HTTP endpoints.

**Exposed Endpoints:**
- `GET /calls` — list all calls with summaries
- `GET /calls/{call_sid}` — full transcript, voicemails, demos
- `GET /demos` — all appointment requests
- `GET /demos/{demo_id}` — single appointment request

**Impact:**
- Public access to PHI
- HIPAA violation if real patient data is present

**Remediation:**
```python
from fastapi import Depends, HTTPException, Header

def verify_api_key(x_api_key: str = Header(...)):
    cfg = get_settings()
    if x_api_key != cfg.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

@app.get("/calls", dependencies=[Depends(verify_api_key)])
async def get_calls(...):
    ...
```

Add `API_KEY` to environment variables. For production, use OAuth or JWT.

---

### 🟠 MEDIUM: Credentials in Environment Variables (Railway/Render)

**Issue:** Secrets stored in hosting dashboard as plaintext environment variables.

**Affected Secrets:**
- `OPENAI_API_KEY`
- `TWILIO_AUTH_TOKEN`
- `GOOGLE_SERVICE_ACCOUNT_JSON` (base64, but still plaintext)

**Current Mitigation:**
- `.gitignore` excludes `.env` and credential files ✅
- No secrets committed to git (verified with `git log --all --full-history`) ✅

**Recommendations:**
1. Use Railway's secret management or AWS Secrets Manager
2. Rotate keys after initial setup
3. Limit API key permissions (OpenAI: restrict to GPT-4o-mini, Twilio: IP allowlist)

---

### 🟠 MEDIUM: No Rate Limiting

**Issue:** Webhooks and API endpoints have no rate limits.

**Impact:**
- OpenAI API abuse (cost)
- Spam voicemails/demos in database
- DoS via repeated calls

**Remediation:**
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/twilio/gather")
@limiter.limit("60/minute")  # 60 calls per minute per IP
async def handle_gather(...):
    ...
```

Alternatively, use Cloudflare rate limiting (recommended for production).

---

### ✅ GOOD: Secrets Not Committed to Git

**Finding:** `.gitignore` correctly excludes:
- `.env`
- `google-service-account.json`
- `*credentials*.json`
- `*.db`

**Verified:** No secrets in git history (`git log --all --full-history --name-only`)

**Note:** Google service account JSON was added as `GOOGLE_SERVICE_ACCOUNT_JSON` env var in commit `06fafcf`, but only as an environment variable (not committed as a file). ✅

---

## Techne Dental-Specific Requirements

### ✅ Implemented
- **AI disclosure:** "I'm the office's AI assistant" in greeting (`TECHNE_GREETING`)
- **Request-only booking:** No live calendar; collects info and front desk books later
- **PHI redaction in logs:** `phi_redaction_enabled=True` applies `_redact_phi()` to logs
- **Emergency triage:** System prompt includes red-flag symptoms (trouble breathing, facial swelling, uncontrolled bleeding) → advise 911/ER
- **No clinical advice:** System prompt explicitly forbids diagnoses, medication recommendations, coverage quotes
- **Insurance verification:** Lists accepted plans; does not quote coverage/copays

### ⚠️ Placeholder Items (From receptionist-prompt.md)
The following are marked `[ASK THE OFFICE]` in the Techne system prompt and must be configured before go-live:

1. **Confirmed phone numbers:**
   - Main: (301) 598-7800 ✅
   - Secondary: 301-963-6300 — purpose unclear
   - Twilio number for Techne: `+15555551234` (placeholder in code)

2. **On-call emergency transfer:**
   - `emergency_transfer_number` is empty in `TECHNE_PROFILE`
   - System prompt: "Until configured, say: 'The team has been alerted and will call you back as soon as possible.'"

3. **Office hours and closures:**
   - Website: Mon–Fri 9–5, weekend closure not confirmed
   - Holidays, lunch breaks not specified

4. **Email address:**
   - Website shows both `contact@technedental.com` and `contact@technedentalgallery.com`

5. **Staff names:**
   - Dr. Ernest Ponraj listed; other dentists/hygienists not confirmed

6. **PMS integration:**
   - Likely Curve Dental (per Michael's note), **not confirmed**
   - Curve API requires "Open Orange" add-on activation and approval
   - No live booking until integration confirmed

7. **Post-call summary delivery:**
   - `message_delivery_email` and `message_delivery_webhook` are empty
   - Must configure before production (where do messages go?)

8. **BAA (Business Associate Agreement):**
   - Not signed with Twilio, OpenAI, or hosting provider
   - **Required before handling real patient data**

---

## Code Quality & Architecture

### ✅ Strengths
- Clean separation: `business_profiles.py` isolates multi-tenant logic
- Backward compatible: NM2TECH behavior unchanged (default business)
- Business selection by called number: scalable to N tenants
- PHI redaction foundation in place (needs database encryption)
- Comprehensive system prompts for Techne (HIPAA-aware tone)

### ⚠️ Improvements Needed
- Add Twilio signature validation (high priority)
- Encrypt PHI at rest (database-level or app-level)
- Add authentication to `/calls` and `/demos` APIs
- Add integration tests for business routing
- Document post-call summary delivery flow (email/webhook)

---

## Deployment Checklist (Before Merge)

### For NM2TECH (No Changes Needed)
- ✅ Existing behavior unchanged (default business)
- ✅ Current Twilio number continues to work

### For Techne Dental (Before Go-Live)
1. **Configuration:**
   - [ ] Provision Twilio phone number for Techne
   - [ ] Update `TECHNE_PROFILE.phone_numbers` in `business_profiles.py`
   - [ ] Set `TECHNE_MESSAGE_EMAIL` or `TECHNE_MESSAGE_WEBHOOK` in production env
   - [ ] Set `TECHNE_EMERGENCY_TRANSFER` (on-call provider number)
   - [ ] Confirm office email, hours, staff names, PMS (replace `[ASK THE OFFICE]` items)

2. **Security:**
   - [ ] Implement Twilio signature validation
   - [ ] Enable database encryption at rest
   - [ ] Add authentication to `/calls` and `/demos` endpoints
   - [ ] Sign BAA with Twilio, OpenAI, and hosting provider

3. **Testing:**
   - [ ] Set `BUSINESS_ID=techne_dental` in staging
   - [ ] Run `python test_multi_tenant.py`
   - [ ] Test emergency scenarios (red-flag symptoms)
   - [ ] Verify PHI redaction in logs
   - [ ] Confirm no NM2TECH info leaks into Techne calls

4. **Compliance:**
   - [ ] Review call recording disclosure wording for Maryland law
   - [ ] Document retention policy (30/60/90 days)
   - [ ] Obtain patient consent for AI assistant (if required)

---

## Summary

**What Changed:**
- Added `app/business_profiles.py` with BusinessProfile dataclass
- Updated `app/twilio_routes.py` to select business by called number
- Updated `app/ai_agent.py` to accept business parameter for system prompt
- Added `app/config.py` fields: `business_id`, `techne_*` settings
- Created `test_multi_tenant.py` test suite
- Updated `README.md` with multi-tenant docs and security notes
- Updated `.env.example` with new config options

**Security Posture:**
- 🔴 4 high-priority issues identified (webhook auth, PHI encryption, API auth, BAA)
- 🟠 2 medium-priority issues (secrets management, rate limiting)
- ✅ No secrets in git (verified)
- ✅ PHI redaction enabled for Techne (logs only; database needs encryption)

**Recommendation:** Safe to merge for **NM2TECH testing**. **Not production-ready for Techne Dental** until security issues are remediated and BAA is signed.
