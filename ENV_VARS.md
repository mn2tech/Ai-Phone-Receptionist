# Environment Variables

## Existing Variables
(See main README for full list)

## New Variables for Techne Features

### SMTP Email Configuration
Required for sending call summary emails to Techne staff:

- `SMTP_HOST` - SMTP server hostname (e.g., `smtp.gmail.com`)
- `SMTP_PORT` - SMTP server port (default: `587` for STARTTLS)
- `SMTP_USERNAME` - SMTP authentication username
- `SMTP_PASSWORD` - SMTP authentication password
- `SMTP_FROM` - From email address (e.g., `receptionist@techne.dental`)

If SMTP is not configured, emails will be skipped with a warning log. Email failures never block or crash call handling.

### Staff Portal Authentication
Required for accessing the Techne staff page at `/staff/techne`:

- `TECHNE_STAFF_USERNAME` - Username for staff login (default: `techne_admin`)
- `TECHNE_STAFF_PASSWORD_HASH` - Bcrypt hash of staff password

Generate the password hash using:
```bash
python scripts/generate_password_hash.py
```

The staff portal is rate-limited: 5 failed login attempts per IP address within 15 minutes.

### Existing Techne Variables
- `TECHNE_MESSAGE_EMAIL` - Comma-separated list of email addresses to receive call summaries
- `TECHNE_EMERGENCY_TRANSFER` - Phone number for urgent call transfers (optional)
