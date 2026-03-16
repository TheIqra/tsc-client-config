# TSC Client Config Microservice

---

## Architecture

```
┌──────────────────────┐    POST /api/v1/webhook/telegram    ┌──────────────────────────┐
│  Telegram Listener   │  ──────────────────────────────────▶ │  TSC Client Config API   │
│  Microservice        │  phone, client_id, channel_id,      │  (this service)          │
│                      │  message_id, text                    │                          │
│  • Watches channels  │                                      │  1. Lookup ChannelConfig │
│  • Forwards messages │  ◀──────────────────────────────────  │  2. Parse signal         │
│                      │       { signals: [...] }             │  3. Log to DB            │
└──────────────────────┘                                      │  4. Return result        │
                                                              └──────────────────────────┘
                                                                        │
                                                                        ▼
                                                              ┌──────────────────────┐
                                                              │  SQLite (local) or   │
                                                              │  PostgreSQL (prod)   │
                                                              └──────────────────────┘
```

---

## Quick Start

### 1. Install dependencies

```bash
python -m venv venv
.\venv\Scripts\activate   # Windows
pip install -r requirements.txt
pip install unidecode emoji
```

### 2. Configure environment

The `.env` file controls database, API authentication, and cache settings:

```env
# Local development (default — SQLite, no setup required)
DATABASE_URL=sqlite+aiosqlite:///./tscweb.db

# Required on protected endpoints (send as X-API-KEY header)
API_KEY=replace-with-a-long-random-secret

# Local Redis
REDIS_URL=redis://localhost:6379/0

# Cache TTL (seconds)
CACHE_TTL_SECONDS=300

# Production — uncomment and fill in real credentials:
# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/yourdb
```

### 3. Run the server

```bash
python main.py
```

The server starts on `http://localhost:8000`. On first startup, all database tables are created automatically.

- **Swagger docs**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/health

---

## Database Schema

5 tables are created automatically on startup:

| Table | Purpose |
|---|---|
| `clients` | Registered clients (external client_id, telegram number, default channel) |
| `telegram_accounts` | Optional Telethon session credentials per client |
| `broker_accounts` | MT4/MT5 trading accounts per client |
| `channel_configs` | Per-channel signal parsing configuration (keywords, flags, parser settings) |
| `signal_logs` | Audit log of every parsed signal from webhooks |

### Relationships

```
Client (1)
 ├── TelegramAccount (N)     — Telethon sessions
 └── BrokerAccount (N)       — MT4/MT5 accounts
      └── ChannelConfig (N)  — per-channel parser config
               │
               └── SignalLog (N)  — parsed signal audit trail
```

### Dual Database Support

The exact same code runs on both:
- **SQLite** (`aiosqlite`) — local development, zero setup
- **PostgreSQL** (`asyncpg`) — production, set `DATABASE_URL` in `.env`

Driver-specific settings (like `check_same_thread` for SQLite or `pool_pre_ping` for PostgreSQL) are applied automatically.

---

## API Endpoints

All business endpoints require this header:

```http
X-API-KEY: <your API_KEY>
```

The `/health` endpoint is public.

### `Auth troubleshooting (403)`

If you get `{"detail":"Invalid or missing API key."}`:

1. Restart the API after editing `.env` (`settings` are loaded at startup).
2. Confirm you are running from the project root so `.env` is found.
3. Check if an OS-level `API_KEY` environment variable is overriding `.env`.
4. Use `curl.exe` on Windows to avoid PowerShell alias behavior.

### `GET /health`

Health check.

```json
{ "status": "ok", "service": "tsc-config-microservice", "version": "2.0.0" }
```

### `Clients`

- `POST /api/v1/clients/`
- `GET /api/v1/clients/`
- `GET /api/v1/clients/{client_id}`
- `PATCH /api/v1/clients/{client_id}`
- `DELETE /api/v1/clients/{client_id}`

### `Broker Accounts` (nested under client)

- `GET /api/v1/{client_id}/broker-accounts/`
- `POST /api/v1/{client_id}/broker-accounts/`
- `GET /api/v1/{client_id}/broker-accounts/{id}`
- `PATCH /api/v1/{client_id}/broker-accounts/{id}`
- `PUT /api/v1/{client_id}/broker-accounts/{id}`
- `DELETE /api/v1/{client_id}/broker-accounts/{id}`

### `Parser Configs` (ChannelConfig, nested under client)

- `GET /api/v1/{client_id}/configs/`
- `POST /api/v1/{client_id}/configs/`
- `GET /api/v1/{client_id}/configs/{id}`
- `PATCH /api/v1/{client_id}/configs/{id}`
- `PUT /api/v1/{client_id}/configs/{id}`
- `DELETE /api/v1/{client_id}/configs/{id}`

### `POST /api/v1/webhook/telegram`

Main webhook endpoint. Called by the Telegram listener microservice whenever a new or edited message arrives in a monitored channel.

**Request body:**

```json
{
  "phone": "+1234567890",
  "client_id": "abc123",
  "channel_id": "987654321",
  "message_id": "12345",
  "text": "XAUUSD BUY 2350.5\nSL 2340.0\nTP 2360.0\nTP 2370.0",

  "replied_message_id": null,
  "replied_text": null,
  "is_forwarded": false,
  "is_edited": false
}
```

| Field | Required | Description |
|---|---|---|
| `phone` | ✅ | Client phone number (international format) |
| `client_id` | ✅ | External client identifier used by this service |
| `channel_id` | ✅ | Telegram channel/chat numeric ID |
| `message_id` | ✅ | Telegram message ID |
| `text` | ✅ | Raw message text from Telegram |
| `replied_message_id` | ❌ | If this is a reply, the original message ID |
| `replied_text` | ❌ | If this is a reply, the original message text |
| `is_forwarded` | ❌ | Whether the message is forwarded (default: false) |
| `is_edited` | ❌ | Whether this is an edited message (default: false) |

**Response:**

```json
{
  "ok": true,
  "message": "Parsed 1 signal(s)",
  "channel_config_id": "uuid-of-channel-config",
  "signals": [
    {
      "signal": "/open XAUUSD,BUY,2350.5,2340.0,2360.0,2370.0,-1,-1,-1,12345,987654321,GoldSign",
      "filename": "MT4_001_123456_12345.txt",
      "status": "sent",
      "detail": null
    }
  ]
}
```

**How the lookup works:**

```
client_id (external) → clients.client_id → client.id
  → broker_accounts (where client_id = client.id)
    → channel_configs (where channel_id = payload.channel_id)
```

If no matching `ChannelConfig` is found, the endpoint returns `ok: false` with an error message and logs it.

---

## Signal Parsing — How It Works

The parser is a direct port of the desktop app's `5.4.4.py` signal processing logic, stripped of all GUI, Telethon, and file system dependencies.

### Processing Pipeline

```
1. Raw text arrives via webhook
2. Pre-processing:
   a. Remove emojis
   b. Uppercase
   c. Remove delimited sections (if DELIMITERS configured)
   d. Apply keyword aliases (replace user-defined keywords with internal codes)
3. Signal detection:
   - Check for BUY/SELL keywords (built-in + custom aliases from kw_buy/kw_sell)
   - Check for TIGNORE (skip if present)
   - Check READFORWARDED flag (skip forwarded if disabled)
4. Route to handler:
   - New signal       → channel_open()      → /open command
   - Close all        → channel_close_all() → /closeall command
   - Delete all       → channel_delete_all()→ /deleteall command
   - Edited message   → edit_open()         → /edit command
5. Reply routing (if replied_message_id is provided):
   - TP1-4 HIT        → /close with TP level
   - CLFL              → /close (full)
   - CLHF / CLPT       → /closehalf or /closepartial
   - MSENTRY           → /breakeven
   - SET SP / SET PP   → /update SL or TP
   - MOVE TP1-5        → /edit with individual TP
   - RMVSL             → /update SL to 0
   - DZF               → /delete
   - AGAINENTER        → re-parse original signal
```

### Signal Output Format

Same format as the desktop app's `.txt` files:

| Command | Format |
|---|---|
| `/open` | `/open SYMBOL,DIR,PRICE,SL,TP1,TP2,TP3,TP4,TP5,MSG_ID,CHANNEL_ID,CHANNEL_NAME` |
| `/edit` | `/edit SYMBOL,DIR,SL,TP1,TP2,TP3,TP4,TP5,MSG_ID` |
| `/close` | `/close SYMBOL,MSG_ID[,TPn]` |
| `/closeall` | `/closeall` |
| `/closehalf` | `/closehalf SYMBOL,MSG_ID` |
| `/closepartial` | `/closepartial SYMBOL,MSG_ID` |
| `/update` | `/update SYMBOL,DIR,SL\|TP,PRICE,MSG_ID` |
| `/breakeven` | `/breakeven SYMBOL,MSG_ID` |
| `/delete` | `/delete SYMBOL,MSG_ID` |
| `/deleteall` | `/deleteall` |

### Special Modes

| Feature | Config field | Behavior |
|---|---|---|
| **Price Range ALL** | `prefer_entry = 3` | Splits `2350.5/2352.5` into separate signals |
| **Multi-Signal (ALLORDER)** | `all_order = True` | Each BUY/SELL line becomes a separate signal |
| **SL/TP in Pips** | `sl_in_pips` / `tp_in_pips` | Appends " pips" to values |
| **Market Order (MKO)** | keyword in text | Clears entry price (forces market execution) |
| **Ignore (TIGNORE)** | keyword in text | Skips the entire message |

---

## ChannelConfig — Keyword System

Each `ChannelConfig` row stores keyword aliases that map the signal provider's language to internal signal codes. This is how the desktop app's `channel.json → msg` dict is stored in the database.

**Example:** If a signal provider writes "COMPRAR" instead of "BUY":

```
kw_buy = "COMPRAR,LONG"     →  replaces "COMPRAR" or "LONG" with " BUY" before parsing
kw_sell = "VENDER,SHORT"    →  replaces "VENDER" or "SHORT" with " SELL" before parsing
```

All 25+ keyword alias fields are optional. Empty/null means "use the default TSC keyword".

---

## Project Structure

```
tsc-web-api/
├── main.py                          # FastAPI entrypoint + lifespan
├── .env                             # Environment config (DATABASE_URL)
├── requirements.txt
│
├── app/
│   ├── core/
│   │   └── config.py                # Pydantic settings (reads .env)
│   │
│   ├── db/
│   │   ├── dbconf.py                # Engine, session, create_tables(), get_db()
│   │   └── orm_models.py            # 5 SQLAlchemy ORM models
│   │
│   ├── model/
│   │   └── schemas.py               # Pydantic request/response schemas
│   │
│   ├── api/
│   │   └── routers/
│   │       ├── clients.py           # /api/v1/clients
│   │       ├── broker_accounts.py   # /api/v1/{client_id}/broker-accounts
│   │       ├── parser_configs.py    # /api/v1/{client_id}/configs
│   │       └── webhook.py           # /api/v1/webhook/telegram endpoint
│   │
│   └── services/
│       └── parser.py                # Signal parser (ported from desktop 5.4.4.py)
│
└── desktop/
    ├── 5.4.4.py                     # Original desktop app (reference only)
    └── README.md                    # Desktop app codebase breakdown
```

---

## What Maps Where (Desktop → Web)

| Desktop (5.4.4.py) | Web Equivalent |
|---|---|
| `others/tpc.dat` (phone) | `clients.telegram_number` |
| `others/path.txt` (client identifier) | `clients.client_id` |
| `others/account.dat` (MT accounts) | `broker_accounts` table |
| `others/channel.json` (config) | `channel_configs` table |
| `Channel_Open()` | `parser.channel_open()` |
| `Edit_Open()` | `parser.edit_open()` |
| `Channel_Close/Update/Delete()` | `parser.channel_close/update/delete()` |
| `on_message()` routing | `parser.route_signal()` |
| `write_signal()` → `.txt` file | `signal_logs` table + API response |
| `log/log.txt` | `signal_logs` table |
| Tkinter GUI | Future web frontend |
| Telethon client | Partner microservice (sends webhooks) |
