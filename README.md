# NM2TECH AI Phone Agent

Phase 1 MVP — an AI receptionist that answers incoming Twilio voice calls, converses with callers using OpenAI, and saves call transcripts and summaries.

## Features

- **Multi-tenant support** — serve multiple businesses from one deployment
  - Business selected by called Twilio number
  - NM2TECH (default): AI phone agent demo, live calendar booking, product catalog
  - Techne Dental: after-hours receptionist, AI disclosure, request-only booking, PHI redaction
- Answers incoming calls with a branded AI greeting
- Multi-turn voice conversation via Twilio `<Gather>` speech recognition
- OpenAI-powered responses using business-specific knowledge
- Transfer to a human when caller says "human", "representative", "agent", or "transfer"
- Leave-a-message flow (collects name, phone, message)
- Demo scheduling flow (collects name, business, phone, preferred time, email)
- Post-call AI summary
- SQLite locally, Postgres/Supabase in production
- Deploy-ready for Railway and Render

## Project Structure

```
app/
  main.py          # FastAPI app, health & calls API
  config.py        # Environment settings
  ai_agent.py      # OpenAI logic, intent detection
  twilio_routes.py # Twilio webhooks & TwiML
  database.py      # SQLAlchemy setup & helpers
  models.py        # ORM + Pydantic schemas
requirements.txt
.env.example
Procfile
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/twilio/voice` | Incoming call webhook (TwiML greeting) |
| POST | `/twilio/gather` | Speech result webhook (AI reply) |
| POST | `/twilio/status` | Call status callback (generates summary) |
| GET | `/calls` | List recent calls |
| GET | `/calls/{call_sid}` | Get call details + transcript |

## Quick Start (Local)

### 1. Clone and install

```bash
cd Ai-Phone-agent
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your keys:

- `OPENAI_API_KEY` — from [OpenAI Platform](https://platform.openai.com/api-keys)
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — from [Twilio Console](https://console.twilio.com)
- `TWILIO_PHONE_NUMBER` — your Twilio phone number
- `TRANSFER_PHONE_NUMBER` — number to dial when caller asks for a human
- `BASE_URL` — your public URL (ngrok URL during local dev)

### 3. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/health to confirm it is running.

## Local Testing with ngrok

Twilio needs a public HTTPS URL to send webhooks. Use [ngrok](https://ngrok.com/) to tunnel your local server.

### 1. Start the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Start ngrok

```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g. `https://abc123.ngrok-free.app`).

### 3. Update BASE_URL

Set in `.env`:

```
BASE_URL=https://abc123.ngrok-free.app
```

Restart the app after changing `.env`.

### 4. Configure Twilio webhooks

In the [Twilio Console](https://console.twilio.com) → **Phone Numbers** → select your number:

| Setting | URL |
|---------|-----|
| **A call comes in** | `https://abc123.ngrok-free.app/twilio/voice` (HTTP POST) |
| **Call status changes** | `https://abc123.ngrok-free.app/twilio/status` (HTTP POST) |

Save the number configuration.

### 5. Call your Twilio number

Dial your Twilio phone number from any phone. You should hear:

> "Hello, thank you for calling NM2TECH AI Phone Agent demo..."

Try asking about pricing, say "leave a message", or say "transfer" to test those flows.

## Twilio Webhook Configuration (Production)

When deployed to Railway or Render, set `BASE_URL` to your production domain and configure the same webhooks:

- **Voice URL:** `https://your-app.railway.app/twilio/voice`
- **Status callback:** `https://your-app.railway.app/twilio/status`

## Example curl Commands

### Health check

```bash
curl http://localhost:8000/health
```

### Simulate incoming call (TwiML greeting)

```bash
curl -X POST http://localhost:8000/twilio/voice \
  -d "CallSid=CAtest123" \
  -d "From=+15551234567" \
  -d "To=+15559876543"
```

### Simulate speech input

```bash
curl -X POST http://localhost:8000/twilio/gather \
  -d "CallSid=CAtest123" \
  -d "From=+15551234567" \
  -d "SpeechResult=What are your pricing plans?"
```

### Simulate call completed (triggers summary)

```bash
curl -X POST http://localhost:8000/twilio/status \
  -d "CallSid=CAtest123" \
  -d "CallStatus=completed" \
  -d "From=+15551234567"
```

### List calls

```bash
curl http://localhost:8000/calls
```

### Get call details

```bash
curl http://localhost:8000/calls/CAtest123
```

## Deploy to Railway

1. Push this repo to GitHub.
2. Create a new project on [Railway](https://railway.app).
3. Add a **PostgreSQL** plugin (optional — SQLite works for demos but Postgres is recommended).
4. Set environment variables from `.env.example`.
5. Set `DATABASE_URL` to the Postgres connection string Railway provides.
6. Set `BASE_URL` to your Railway public URL.
7. Railway uses the `Procfile` automatically.

## Deploy to Render

1. Create a new **Web Service** on [Render](https://render.com).
2. Connect your GitHub repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables from `.env.example`.
6. Optionally add a Render Postgres database and set `DATABASE_URL`.

## Call Flow

```
Caller dials Twilio number
        │
        ▼
POST /twilio/voice  →  Greeting + Gather
        │
        ▼
Caller speaks  →  POST /twilio/gather
        │
        ├── Transfer intent?  →  Dial TRANSFER_PHONE_NUMBER
        ├── Message intent?   →  Collect name / phone / message
        ├── Demo intent?      →  Collect demo details
        └── Otherwise         →  OpenAI reply + Gather (loop)
        │
        ▼
Call ends  →  POST /twilio/status  →  Save AI summary
```

## Multi-Tenant Configuration

This codebase supports multiple businesses. The active business is selected by the **called Twilio number** (`To` field in webhooks).

### Supported Businesses

| Business | Phone Numbers | Behavior |
|----------|---------------|----------|
| **NM2TECH** (default) | `+13012982874` | AI phone agent demo, live calendar booking, product catalog |
| **Techne Dental** | `+15555551234` (configure in `business_profiles.py`) | After-hours receptionist, AI disclosure, request-only appointment booking, PHI redaction |

### Adding a Business

1. Edit `/workspace/app/business_profiles.py`
2. Update the business profile's `phone_numbers` tuple with your Twilio number(s)
3. Configure business-specific settings in `.env`:
   - `TECHNE_EMERGENCY_TRANSFER` — on-call provider number (E.164)
   - `TECHNE_MESSAGE_EMAIL` — where to send post-call summaries
   - `TECHNE_MESSAGE_WEBHOOK` — HTTP POST endpoint for summaries

### Testing with a Single Number

To test both businesses with one Twilio number, set `BUSINESS_ID`:

```bash
# Force all calls to act as Techne Dental
BUSINESS_ID=techne_dental
```

**Important:** Leave `BUSINESS_ID` empty in production. The system will auto-detect the business by the called number.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio auth token (also used for signature validation) |
| `TWILIO_PHONE_NUMBER` | Yes | Your Twilio number |
| `TRANSFER_PHONE_NUMBER` | Yes | Human transfer destination (NM2TECH) |
| `DATABASE_URL` | No | Defaults to SQLite locally |
| `BASE_URL` | Yes | Public app URL for Twilio callbacks |
| **Security** | | |
| `API_KEY` | **Recommended** | API key for `/calls` and `/demos` endpoints. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENCRYPTION_KEY` | **Required for Techne** | Fernet encryption key for PHI. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `TWILIO_VALIDATE_REQUESTS` | No | Enable Twilio signature validation (default: `true`). Set to `false` for local testing only. |
| **Multi-tenant** | | |
| `BUSINESS_ID` | No | Override business selection (testing only): `nm2tech` or `techne_dental` |
| `TECHNE_EMERGENCY_TRANSFER` | No | Techne on-call provider number (E.164) |
| `TECHNE_MESSAGE_EMAIL` | No | Techne post-call summary email |
| `TECHNE_MESSAGE_WEBHOOK` | No | Techne post-call summary webhook URL |

## Troubleshooting

- **No speech detected:** Speak clearly after the greeting pause. The agent will retry once, then offer to take a message.
- **OpenAI errors:** Check `OPENAI_API_KEY` and account billing. The agent falls back to a generic message if OpenAI is unavailable.
- **Transfer not working:** Verify `TRANSFER_PHONE_NUMBER` is set and in E.164 format (`+1...`).
- **Webhooks not hitting your app:** Confirm ngrok is running and `BASE_URL` matches the ngrok HTTPS URL. Check Twilio debugger in the console.
- **Wrong business selected:** Check the `To` field in Twilio webhooks matches a phone number in `business_profiles.py`. Set `BUSINESS_ID` for testing.
- **403 on Twilio webhooks:** Twilio signature validation is enabled. For local testing without ngrok, set `TWILIO_VALIDATE_REQUESTS=false`. For production, ensure `BASE_URL` uses HTTPS.
- **403 on /calls or /demos:** API key authentication is enabled. Provide `X-API-Key` header with the value from `API_KEY` environment variable.
- **[ENCRYPTED - KEY MISSING] in API responses:** Database has encrypted data but `ENCRYPTION_KEY` is not set. Set the correct encryption key to decrypt.
- **Railway/Render signature validation fails:** The app handles `X-Forwarded-Proto` correctly. Ensure `BASE_URL` matches your production domain exactly (including HTTPS).

## Security Features

**Implemented (as of this PR):**
- ✅ **Twilio signature validation** — all `/twilio/*` webhooks verify `X-Twilio-Signature` (enabled by default)
- ✅ **API key authentication** — `/calls` and `/demos` endpoints require `X-API-Key` header
- ✅ **Field-level encryption** — PHI data encrypted at rest using Fernet (AES-128 CBC + HMAC)
- ✅ **PHI redaction in logs** — caller numbers and sensitive data redacted from logs for Techne Dental
- ✅ Secrets in `.gitignore` — `.env`, Google service account JSON, and credentials excluded from git

**Configuration (Required for Production):**

```bash
# 1. Generate API key
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Set as API_KEY=<output>

# 2. Generate encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Set as ENCRYPTION_KEY=<output>

# 3. Enable Twilio signature validation (enabled by default)
TWILIO_VALIDATE_REQUESTS=true
```

**Security Status:**
- ✅ Webhooks authenticated (Twilio signature validation)
- ✅ API endpoints protected (API key required)
- ✅ PHI encrypted at rest (Fernet symmetric encryption)
- ⚠️ No rate limiting — add `slowapi` or use Cloudflare
- ⚠️ BAA required — sign with Twilio, OpenAI, and hosting provider before handling real patient data

**Testing Security:**

```bash
# Run security test suite
python3 test_security.py
```

**Backward Compatibility:**
- Encryption is **opt-in** — leave `ENCRYPTION_KEY` empty to disable (not recommended for Techne)
- API auth is **opt-in** — leave `API_KEY` empty to disable (logs warning)
- Twilio validation can be disabled for local testing: `TWILIO_VALIDATE_REQUESTS=false`
- Existing plaintext data is readable (decryption detects `enc:` prefix)

**Migrating Existing Data:**

If you have existing plaintext PHI in the database and want to encrypt it:

```python
# Run this script once after setting ENCRYPTION_KEY
from app.database import SessionLocal
from app.encryption import encrypt_field
from app.models import CallRecord, ConversationTurn, VoicemailMessage, DemoRequest

session = SessionLocal()

# Encrypt CallRecord.caller_phone
for call in session.query(CallRecord).all():
    if not call.caller_phone.startswith("enc:"):
        call.caller_phone = encrypt_field(call.caller_phone)

# Encrypt ConversationTurn fields
for turn in session.query(ConversationTurn).all():
    if not turn.caller_speech.startswith("enc:"):
        turn.caller_speech = encrypt_field(turn.caller_speech)
    if not turn.ai_response.startswith("enc:"):
        turn.ai_response = encrypt_field(turn.ai_response)

# (Repeat for VoicemailMessage and DemoRequest)

session.commit()
session.close()
```

## Deployment Notes

**⚠️ REQUIRED: Set These Environment Variables Before Merging**

To keep the **live NM2TECH app working** after merge, you **must** set these in your Railway/Render dashboard **before** merging this PR:

```bash
# 1. API Key (protects /calls and /demos endpoints)
API_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">

# 2. Encryption Key (encrypts PHI at rest)
ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# 3. Twilio signature validation (already enabled by default)
TWILIO_VALIDATE_REQUESTS=true
```

**If you don't set these before merging:**
- ❌ `/calls` and `/demos` API endpoints will return 403 (if `API_KEY` is required but missing)
- ⚠️ If `API_KEY` is not set, endpoints will be **unauthenticated** (logs warning)
- ⚠️ If `ENCRYPTION_KEY` is not set, PHI will be stored in **plaintext** (logs warning)
- ✅ Twilio webhooks will continue to work (validation enabled by default, uses existing `TWILIO_AUTH_TOKEN`)

**Generate keys now:**

```bash
# API Key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Encryption Key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**After setting keys in Railway/Render:**
1. Merge this PR
2. Deployment will auto-trigger
3. App will restart with new security features enabled
4. Verify with: `curl -H "X-API-Key: YOUR_KEY" https://your-app.railway.app/calls`

**Backward Compatibility:**
- ✅ NM2TECH behavior unchanged (default business, existing phone number works)
- ✅ Existing plaintext data readable (encryption detects `enc:` prefix, passes through old data)
- ✅ No database migrations required
- ✅ Can disable features temporarily (not recommended): set `API_KEY=""` or `TWILIO_VALIDATE_REQUESTS=false`

**To activate Techne Dental (after merge):**
1. Provision a new Twilio phone number for Techne
2. Update `TECHNE_PROFILE.phone_numbers` in `app/business_profiles.py`
3. Configure webhooks for the new number to point to this app
4. Set `TECHNE_MESSAGE_EMAIL` or `TECHNE_MESSAGE_WEBHOOK` in production environment
5. Test with `BUSINESS_ID=techne_dental` before going live
6. Sign BAAs with Twilio, OpenAI, and hosting provider

**No Procfile changes** — deployment command unchanged.

## Testing

Run the multi-tenant test suite:

```bash
# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# In another terminal
python test_multi_tenant.py
```

## License

MIT — NM2TECH LLC demo project.
