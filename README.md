# Burjeel Smart Care — Backend

A REST API and WebSocket server for the Burjeel Smart Care patient management system. Built with FastAPI (Python) and backed by a Supabase (PostgreSQL) database.

---

## Tech Stack

| What | Tool |
|---|---|
| Web Framework | FastAPI |
| ASGI Server | Uvicorn |
| Database | Supabase (PostgreSQL via Supabase Python SDK) |
| Auth | JWT tokens (`python-jose`) + bcrypt password hashing |
| 2FA | TOTP via `pyotp` (Google Authenticator compatible) |
| SMS | TextBee API (via `httpx`) |
| Email | Google Apps Script webhook (via `requests`) |
| Rate Limiting | `slowapi` |
| Validation | Pydantic v2 |
| Testing | pytest + pytest-asyncio |

---

## Project Structure

```
app/
├── main.py                  # Creates the FastAPI app, registers all routers, sets up CORS
│
├── api/
│   ├── deps.py              # Shared dependencies: get current user, role checker, WebSocket auth
│   └── v1/                  # All API endpoints, grouped by topic
│       ├── auth.py          # Register, login, 2FA setup/verify, list users
│       ├── patients.py      # Create, read, update, delete patient records
│       ├── reminders.py     # Schedule reminders, send SMS/email, process due reminders
│       ├── attendance.py    # Mark and retrieve patient attendance
│       ├── reports.py       # Attendance and reminder summary statistics
│       ├── chat.py          # WebSocket real-time chat + REST message history
│       ├── unified_reminders.py # Send SMS + email together in one request
│       ├── users.py         # Admin: edit/delete any user, reset passwords
│       └── profile.py       # Self-service: update own profile, change password, upload avatar
│
├── core/
│   ├── config.py            # Reads all settings from the .env file
│   ├── supabase.py          # Creates and exports the Supabase client (used everywhere)
│   ├── security.py          # Password hashing (bcrypt) and JWT creation/verification
│   ├── gmail_service.py     # Sends HTML emails via a Google Apps Script webhook
│   └── validators.py        # Password complexity rules
│
├── schemas/                 # Pydantic models — define the shape of request and response data
│   ├── user.py
│   ├── patient.py
│   ├── reminder.py
│   ├── attendance.py
│   ├── chat_message.py
│   ├── sms_log.py
│   ├── doctor.py
│   └── unified_reminder.py
│
├── services/                # Business logic — the "how" behind each feature
│   ├── auth_service.py          # User creation, authentication, profile updates
│   ├── supabase_service.py      # Low-level Supabase query helpers
│   ├── reminder_service.py      # Reminder scheduling and notification dispatch
│   ├── unified_reminder_service.py # SMS + email combined sending with retry logic
│   ├── sms_service.py           # TextBee SMS API integration
│   └── report_service.py        # Aggregation queries for the reports endpoints
│
├── Send_Body/               # HTML and plain-text email/SMS templates
│   ├── appointment.html / .txt
│   ├── appointment_issued.html / .txt
│   ├── medication.html / .txt
│   ├── medication_issued.html / .txt
│   ├── chat_notification.html
│   └── user_registered.html
│
└── utils/                   # Reserved for future helper functions

tests/                       # Pytest test files
requirements.txt             # Python dependencies
Dockerfile                   # Container build instructions
docker-compose.yml           # Runs backend (and frontend) together
```

---

## How It Works

### Request Lifecycle
1. A request arrives at a route in `app/api/v1/`.
2. FastAPI runs the **dependency** from `app/api/deps.py` — this decodes the JWT token and loads the current user.
3. `RoleChecker` verifies the user's role is allowed for that endpoint.
4. The route handler calls a **service** function that contains the business logic.
5. The service calls **Supabase** to read or write data.
6. The response is serialised through a **Pydantic schema** and returned as JSON.

### Authentication
- `POST /api/v1/auth/login` — returns a JWT access token (valid 30 minutes by default).
- Every protected endpoint requires `Authorization: Bearer <token>` in the request header.
- Tokens are verified in `app/api/deps.py` using the secret key from `.env`.
- Optional TOTP 2FA: users can enable it via `/auth/2fa/setup` and `/auth/2fa/verify`.

### Roles
| Role | Access |
|---|---|
| `admin` | Everything |
| `doctor` | Patients, reminders, attendance, reports, chat |
| `patient` | Own profile, own reminders, chat |

### Notifications
- **SMS**: sent via TextBee API (`app/services/sms_service.py`).
- **Email**: sent via a Google Apps Script webhook (`app/core/gmail_service.py`). Templates are HTML files in `app/Send_Body/`.
- Reminders are processed by hitting `GET /api/v1/reminders/process-upcoming` — this endpoint is intentionally unauthenticated so a cron job can call it.

### Real-time Chat
- Clients connect to `ws://<host>/api/v1/chat/ws/{user_id}?token=<jwt>`.
- The server keeps a dictionary of active connections and broadcasts messages to the right recipient.
- Message history is stored in the `chat_messages` Supabase table.
- `is_read` starts as `False` on every message. The frontend calls `PUT /api/v1/chat/messages/read` (with the sender's ID) whenever a conversation is opened, which flips `is_read` to `True` for all unread messages in that thread. The unread badge count is updated in the UI immediately without waiting for the next API poll.

---

## Database Tables

| Table | Purpose |
|---|---|
| `users` | All accounts (every role) |
| `patients` | Extended patient profile linked to a user |
| `doctors` | Extended doctor profile linked to a user |
| `reminders` | Scheduled medication / appointment reminders |
| `attendance` | Whether a patient attended their appointment |
| `chat_messages` | Chat messages between users |

---

## Running Locally

```bash
# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Copy the example env file and fill in your values
cp .env.example .env

# Start the server with hot reload
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`  
Interactive docs at `http://localhost:8000/docs`

---

## Running with Docker

```bash
# From the backend directory — starts backend on port 8000 and frontend on port 80
docker-compose up --build
```

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (bypasses row-level security) |
| `SUPABASE_ANON_KEY` | Supabase anon key |
| `SECRET_KEY` | Secret used to sign JWT tokens — keep this private |
| `ALGORITHM` | JWT signing algorithm (default: `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | How long tokens stay valid (default: `30`) |
| `KEY` | TextBee API key for SMS |
| `DEVICE_ID` | TextBee device ID for SMS |
| `GOOGLE_SCRIPT_URL` | Google Apps Script webhook URL for email |
| `EMAIL_TOKEN` | Auth token for the Google Apps Script |
| `EMAIL_NAME` | Sender name shown in emails |

---

## Database Setup (Supabase)

1. Create a new project at [app.supabase.com](https://app.supabase.com).
2. Open the **SQL Editor** and run the following script to create all tables:

```sql
-- Users table: stores every account regardless of role
CREATE TABLE users (
    user_id              SERIAL PRIMARY KEY,
    username             VARCHAR(50)  NOT NULL UNIQUE,
    email                VARCHAR(100) UNIQUE,
    password_hash        VARCHAR(255) NOT NULL,
    role                 VARCHAR(20)  NOT NULL CHECK (role IN ('admin','doctor','patient')),
    gender               VARCHAR(10),
    profile_picture_url  TEXT,
    notification_preferences JSONB,
    two_factor_enabled   BOOLEAN DEFAULT FALSE,
    two_factor_secret    TEXT,
    last_login           TIMESTAMPTZ,
    account_status       VARCHAR(10)  NOT NULL DEFAULT 'active' CHECK (account_status IN ('active','inactive','suspended')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by           INTEGER REFERENCES users(user_id)
);

-- Patients table: extra info for users with role = 'patient'
CREATE TABLE patients (
    patient_id         SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    full_name          VARCHAR(100) NOT NULL,
    phone_number       VARCHAR(15),
    medical_record_ref VARCHAR(50),
    registered_date    DATE,
    gender             VARCHAR(10),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Doctors table: extra info for users with role = 'doctor'
CREATE TABLE doctors (
    doctor_id      SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    specialty      VARCHAR(100),
    license_number VARCHAR(50),
    department     VARCHAR(100),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Reminders: scheduled SMS/email notifications for patients
CREATE TABLE reminders (
    reminder_id     SERIAL PRIMARY KEY,
    patient_id      INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    reminder_type   VARCHAR(50),
    message         TEXT,
    scheduled_date  DATE NOT NULL,
    sent_status     VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (sent_status IN ('pending','sent','failed')),
    success_sent    INTEGER DEFAULT 0,
    failed_sent     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by      INTEGER REFERENCES users(user_id)
);

-- Attendance: records whether a patient came to their appointment
CREATE TABLE attendance (
    attendance_id    SERIAL PRIMARY KEY,
    patient_id       INTEGER NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    appointment_date DATE NOT NULL,
    status           VARCHAR(10) NOT NULL CHECK (status IN ('present','absent','late')),
    notes            TEXT,
    marked_by        INTEGER REFERENCES users(user_id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Chat messages: stored messages between any two users
CREATE TABLE chat_messages (
    message_id   SERIAL PRIMARY KEY,
    sender_id    INTEGER NOT NULL REFERENCES users(user_id),
    receiver_id  INTEGER NOT NULL REFERENCES users(user_id),
    message_text TEXT NOT NULL,
    is_read      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX idx_users_role           ON users(role);
CREATE INDEX idx_patients_user_id     ON patients(user_id);
CREATE INDEX idx_reminders_patient    ON reminders(patient_id);
CREATE INDEX idx_reminders_date       ON reminders(scheduled_date);
CREATE INDEX idx_attendance_patient   ON attendance(patient_id);
CREATE INDEX idx_chat_sender          ON chat_messages(sender_id);
CREATE INDEX idx_chat_receiver        ON chat_messages(receiver_id);
```

3. Copy the `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from your Supabase project settings into `.env`.
