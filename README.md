# TSC Client Config — Signal Parser Microservice

A **Django REST Framework** microservice that manages trading signal clients, stores raw Telegram webhook messages, parses them into structured trade commands, and exposes a clean REST API for configuration and signal management.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
  - [Client Management](#client-management)
  - [Webhook Receiver](#webhook-receiver)
  - [Signal Parser](#signal-parser)
  - [Parsed Signals](#parsed-signals)
- [Signal Parsing — How It Works](#signal-parsing--how-it-works)
- [ChannelConfig — Keyword System](#channelconfig--keyword-system)
- [Default Config Values](#default-config-values)
- [Interactive Docs](#interactive-docs)

---

## Architecture

```
┌─────────────────────────┐
│  Telegram Listener      │  (partner microservice)
│  Microservice           │
│  · Watches channels     │
│  · Forwards messages    │
└────────────┬────────────┘
             │ POST /api/v1/webhook/receiver/
             │ { client_id, message_id, text, ... }
             ▼
┌─────────────────────────────────────────────────────┐
│          TSC Client Config Microservice              │
│                                                     │
│  ┌─────────────┐    ┌────────────────────────────┐  │
│  │  client app │    │       parser app           │  │
│  │             │    │                            │  │
│  │ ClientConfig│◄───│ ChannelConfig (1:1)        │  │
│  │ (who)       │    │ (how to parse signals)     │  │
│  │             │    │                            │  │
│  │ WebhookMsg  │◄───│ ParsedSignal (result)      │  │
│  │ (raw msg)   │    │ TakeProfit   (TP rows)     │  │
│  └─────────────┘    └────────────────────────────┘  │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  SQLite (dev)          │
              │  PostgreSQL (prod)     │
              └────────────────────────┘
```

**Flow:**
1. Telegram listener POSTs a raw message to `/webhook/receiver/`
2. Message is stored as a `WebhookMessage` linked to the client
3. Caller POSTs to `/parser/parse/` with `client_id` + `message_id`
4. Parser reads the client's `ChannelConfig`, preprocesses text, and routes the signal
5. Results are persisted as `ParsedSignal` + `TakeProfit` rows and returned

---

## Tech Stack

| Layer | Library | Version |
|---|---|---|
| Framework | Django | 6.0.3 |
| REST API | Django REST Framework | 3.16.1 |
| API Docs | drf-yasg (Swagger / ReDoc) | 1.21.15 |
| CORS | django-cors-headers | 4.9.0 |
| Filtering | django-filter | 25.2 |
| Text normalization | Unidecode | 1.4.0 |
| Environment | python-dotenv | 1.2.2 |
| Database | SQLite (dev) / PostgreSQL (prod) | — |

---

## Project Structure

```
tsc-client-config/
├── manage.py
├── .env                          # Environment variables (API key, DB, etc.)
├── requirements.txt
│
├── CORE/                         # Django project package
│   ├── settings.py               # All settings (reads .env)
│   ├── urls.py                   # Root URL conf → client + parser
│   ├── middleware.py             # ApiKeyMiddleware (X-API-KEY enforcement)
│   ├── asgi.py
│   └── wsgi.py
│
├── client/                       # Client identity + webhook ingestion
│   ├── models.py                 # ClientConfig, WebhookMessage
│   ├── serializers.py            # ClientConfigSerializer (writable nested config)
│   │                             # WebhookMessageSerializer
│   ├── views.py                  # ClientConfigViewSet, WebhookReceiverView
│   └── urls.py                   # /clients/, /webhook/receiver/
│
└── parser/                       # Signal parsing engine
    ├── models.py                 # SystemSettings, ChannelConfig,
    │                             # ParsedSignal, TakeProfit
    ├── serializers.py            # ChannelConfigSerializer,
    │                             # ParsedSignalSerializer,
    │                             # ParseSignalInputSerializer,
    │                             # TakeProfitSerializer
    ├── views.py                  # ParserViewSet
    ├── urls.py                   # /parser/parse/, /parser/signals/
    └── parser.py                 # Pure-Python signal parser (ported from TSC 5.4.4)
```

---

## Quick Start

### 1. Clone & create virtual environment

```bash
git clone <repo-url>
cd tsc-client-config

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
pip install unidecode
```

### 3. Configure environment

Copy or edit `.env` in the project root:

```env
# Required — all API requests must include: X-API-KEY: <this value>
X_API_KEY=your-long-random-secret-here

# Redis (optional, for future caching)
REDIS_URL=redis://localhost:6379/0
CACHE_TTL_SECONDS=300
```

### 4. Apply migrations

```bash
python manage.py migrate
```

### 5. Run the development server

```bash
python manage.py runserver
```

The server starts on `http://127.0.0.1:8000`.

- **Swagger UI**: http://127.0.0.1:8000/api/docs/
- **ReDoc**: http://127.0.0.1:8000/api/redoc/

---

## Authentication

Every request (except `/api/docs/`, `/api/redoc/`, `/admin/`) must include:

```http
X-API-KEY: <value from .env X_API_KEY>
```

**Error responses:**

| Status | Reason |
|---|---|
| `401` | Header missing → `{"detail": "X-API-KEY header is required."}` |
| `401` | Wrong key → `{"detail": "Invalid API key."}` |
| `500` | Key not configured on server → `{"detail": "Server API key is not configured."}` |

---

## Database Schema

```
ClientConfig (1)
 └── WebhookMessage (N)       — raw Telegram messages received
 └── ChannelConfig (1)        — keyword + behaviour config (auto-created with defaults)
      └── ParsedSignal (N)    — one trade command per parsed signal
           └── TakeProfit (N) — dynamic TP rows (TP1, TP2, …)

SystemSettings (singleton)    — global TP cap (admin-only)
```

| Table | App | Purpose |
|---|---|---|
| `client_clientconfig` | client | Client identity (telegram number, channel, broker) |
| `client_webhookmessage` | client | Raw messages from the listener microservice |
| `parser_channelconfig` | parser | Keyword aliases and behaviour flags per client |
| `parser_parsedsignal` | parser | Parser output — one row per trade action |
| `parser_takeprofit` | parser | Dynamic TP rows for each parsed signal |
| `parser_systemsettings` | parser | Singleton: global max TP count |

---

## API Reference

Base URL: `http://127.0.0.1:8000/api/v1/`

All requests require the `X-API-KEY` header.

---

### Client Management

The `config` field is always returned nested in every client response. It is also **writable** on `POST`, `PUT`, and `PATCH` — you can update client fields and parser configuration in a single request.

#### `GET /clients/` — List all clients

```bash
curl -X GET http://127.0.0.1:8000/api/v1/clients/ \
  -H "X-API-KEY: your-key"
```

**Response `200`** (paginated):
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "client_id": "1008",
      "telegram_number": "+19876543210",
      "channel_id": "888333444",
      "broker_account_number": "52785001",
      "broker_server": "MetaQuotes-Demo",
      "is_active": true,
      "created_at": "2026-03-16T14:08:44.483998Z",
      "updated_at": "2026-03-16T14:08:44.483998Z",
      "config": { ... }
    }
  ]
}
```

---

#### `POST /clients/` — Create a client

A `ChannelConfig` with all default values is **automatically created** alongside the client. You do not need to call a separate config endpoint.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/clients/ \
  -H "X-API-KEY: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "1008",
    "telegram_number": "+19876543210",
    "channel_id": "888333444",
    "broker_account_number": "52785001",
    "broker_server": "MetaQuotes-Demo",
    "is_active": true
  }'
```

You can also supply `"config": { ... }` in the same body to override specific defaults at creation time.

**Response `201`**:
```json
{
  "id": 1,
  "client_id": "1008",
  "telegram_number": "+19876543210",
  "channel_id": "888333444",
  "broker_account_number": "52785001",
  "broker_server": "MetaQuotes-Demo",
  "is_active": true,
  "created_at": "2026-03-16T14:08:44.483998Z",
  "updated_at": "2026-03-16T14:08:44.483998Z",
  "config": {
    "client_id": "1008",
    "kw_entry_point": "ENTRY",
    "kw_buy": "LONG",
    "kw_sell": "SHORT",
    "kw_sl": "SL",
    "kw_tp": "TP",
    "kw_market_order": "",
    "use_ai": false,
    "read_image": false,
    "kw_close_tp1": "",
    "kw_close_tp2": "",
    "kw_close_tp3": "",
    "kw_close_tp4": "",
    "kw_close_full": "",
    "kw_close_half": "",
    "kw_close_partial": "",
    "kw_breakeven": "",
    "kw_set_tp1": "",
    "kw_set_tp2": "",
    "kw_set_tp3": "",
    "kw_set_tp4": "",
    "kw_set_tp5": "",
    "kw_set_all_tp": "",
    "kw_set_sl": "",
    "kw_delete_pending": "",
    "kw_layer": "",
    "kw_close_all": "",
    "kw_delete_all": "",
    "kw_ignore": "",
    "kw_skip": "",
    "kw_remove_sl": "",
    "delay_ms": 0,
    "prefer_entry": 2,
    "sl_in_pips": false,
    "tp_in_pips": false,
    "delimiters": "",
    "all_order": false,
    "read_forwarded": true,
    "news_filter": false
  }
}
```

---

#### `GET /clients/{client_id}/` — Retrieve a client

```bash
curl -X GET http://127.0.0.1:8000/api/v1/clients/1008/ \
  -H "X-API-KEY: your-key"
```

---

#### `PATCH /clients/{client_id}/` — Partial update (client + config)

Send only the fields you want to change. The `config` key is optional — if omitted, only client fields are updated. If supplied, only the provided config keys are updated (always partial for config).

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/clients/1008/ \
  -H "X-API-KEY: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "is_active": true,
    "config": {
      "kw_buy": "LONG",
      "kw_sell": "SHORT",
      "kw_sl": "STOP LOSS",
      "kw_tp": "TAKE PROFIT",
      "prefer_entry": 2,
      "read_forwarded": true
    }
  }'
```

**Response `200`** — full client object with updated nested config.

---

#### `PUT /clients/{client_id}/` — Full update

Same as PATCH but all client fields are required. `config` remains optional and partial.

---

#### `DELETE /clients/{client_id}/` — Delete a client

Cascades to WebhookMessages and ChannelConfig.

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/clients/1008/ \
  -H "X-API-KEY: your-key"
```

**Response `204 No Content`**

---

### Webhook Receiver

Called by the Telegram listener microservice whenever a message arrives in a monitored channel. The webhook endpoint is **public** (no API key required) so it can be called by external services without sharing the key.

#### `POST /webhook/receiver/` — Store a raw Telegram message

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhook/receiver/ \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "1008",
    "telegram_number": "+19876543210",
    "channel_id": "888333444",
    "broker_account_number": "52785001",
    "broker_server": "MetaQuotes-Demo",
    "message_id": "2004",
    "text": "XAUUSD LONG 3350.0\nSL 3300.0\nTP1 3400.0\nTP2 3450.0",
    "replied_message_id": "",
    "replied_text": "",
    "is_forwarded": false,
    "is_edited": false
  }'
```

| Field | Required | Description |
|---|---|---|
| `client_id` | ✅ | Must match an active `ClientConfig.client_id` |
| `telegram_number` | ✅ | Must match the client's registered number |
| `channel_id` | ✅ | Must match the client's registered channel ID |
| `broker_account_number` | ✅ | Must match the client's registered broker account |
| `broker_server` | ✅ | Must match the client's registered broker server |
| `message_id` | ✅ | Telegram message ID (string) |
| `text` | ✅ | Raw message text |
| `replied_message_id` | ❌ | If a reply: the original message ID |
| `replied_text` | ❌ | If a reply: the original message text |
| `is_forwarded` | ❌ | Whether forwarded (default: `false`) |
| `is_edited` | ❌ | Whether edited (default: `false`) |

**Response `201`**:
```json
{
  "detail": "Webhook payload received.",
  "id": 42
}
```

**Response `400`** if client identity fields don't match the stored client.

---

### Signal Parser

#### `POST /parser/parse/` — Parse a stored message

Triggers the full parsing pipeline for a previously stored `WebhookMessage`. The parser reads the client's `ChannelConfig`, pre-processes text using keyword aliases, then routes the signal to the appropriate handler.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/parser/parse/ \
  -H "X-API-KEY: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "1008",
    "message_id": "2004",
    "force_reparse": false
  }'
```

| Field | Required | Description |
|---|---|---|
| `client_id` | ✅ | Client identifier |
| `message_id` | ✅ | Telegram message ID (must exist in webhook store) |
| `force_reparse` | ❌ | `true` → delete existing results and re-parse (default: `false`) |

**Response `201`** — list of parsed signal objects:
```json
[
  {
    "id": 7,
    "kind": "open",
    "command": "/open XAUUSD,BUY,3350.0,3300.0,3400.0,3450.0,2004,888333444,1008",
    "symbol": "XAUUSD",
    "direction": "BUY",
    "entry_price": "3350.0",
    "sl": "3300.0",
    "tps": [
      { "order": 1, "value": "3400.0", "label": "TP1", "hit_at": null, "is_edit_target": false },
      { "order": 2, "value": "3450.0", "label": "TP2", "hit_at": null, "is_edit_target": false }
    ],
    "msg_id": "2004",
    "channel_id": "888333444",
    "channel": "1008",
    "close_tp": "",
    "new_sl": "",
    "new_tps": [],
    "status": "PENDING",
    "blocked_by_news_filter": false,
    "parsed_at": "2026-03-16T17:22:10.123456Z"
  }
]
```

**Response `400`** scenarios:

| Error | Cause |
|---|---|
| `client_id not found` | No `ClientConfig` with this ID |
| `no ChannelConfig` | Client exists but config was never created (shouldn't happen if client was created via API) |
| `message not found` | No `WebhookMessage` for this client + message_id pair |
| `already parsed` | Message was already parsed; use `force_reparse: true` |
| `symbol not resolved` | Parser could not extract a valid trading symbol from the message text — trade cannot be opened |

---

### Parsed Signals

#### `GET /parser/signals/` — List all signals

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/parser/signals/?client_id=1008&kind=open" \
  -H "X-API-KEY: your-key"
```

**Query parameters (all optional):**

| Param | Description | Example |
|---|---|---|
| `client_id` | Filter by client | `1008` |
| `symbol` | Filter by instrument (case-insensitive) | `XAUUSD` |
| `kind` | Filter by command type | `open`, `close`, `closeall`, `update` |
| `status` | Filter by signal status | `PENDING`, `OPEN`, `CLOSED`, `CANCELLED`, `ERROR` |

---

#### `GET /parser/signals/{id}/` — Retrieve one signal

```bash
curl -X GET http://127.0.0.1:8000/api/v1/parser/signals/7/ \
  -H "X-API-KEY: your-key"
```

---

#### `PATCH /parser/signals/{id}/update/` — Update signal status

Only `status` and `blocked_by_news_filter` are writable after creation (all parser output fields are immutable).

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/parser/signals/7/update/ \
  -H "X-API-KEY: your-key" \
  -H "Content-Type: application/json" \
  -d '{"status": "OPEN"}'
```

| Writable field | Values |
|---|---|
| `status` | `PENDING`, `OPEN`, `CLOSED`, `CANCELLED`, `ERROR` |
| `blocked_by_news_filter` | `true` / `false` |

---

#### `GET /parser/signals/{id}/tps/` — List TPs for a signal

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/parser/signals/7/tps/?edit=false" \
  -H "X-API-KEY: your-key"
```

**Query params:**

| Param | Description |
|---|---|
| `edit=false` | Only original TPs (from the open signal) |
| `edit=true` | Only edit-target TPs (from update commands) |
| *(omit)* | All TPs |

---

## Signal Parsing — How It Works

The parser is a direct Python port of the TSC 5.4.4 desktop app's signal routing logic, free of all GUI, Telethon, and file system dependencies.

### Processing Pipeline

```
1. Raw text arrives via POST /webhook/receiver/
   → stored as WebhookMessage

2. POST /parser/parse/ is called
   → ChannelConfig is loaded for the client

3. Pre-processing (preprocess_text):
   a. Uppercase + Unicode normalization
   b. Strip delimiter-enclosed sections (if DELIMITERS configured)
   c. Apply keyword aliases (e.g. LONG → BUY, SHORT → SELL, STOP LOSS → SL)

4. Signal routing (route_signal):
   ┌─ No replied text (fresh message):
   │   · BUY/SELL keyword found  → channel_open()     → /open
   │   · CLZP keyword found      → channel_close_all()→ /closeall
   │   · DZD keyword found       → channel_delete_all()→ /deleteall
   │
   └─ Has replied text (reply to an existing signal):
       · TP1–4 HIT   → channel_close(tp=TPn)  → /close SYMBOL,MSG_ID,TP1
       · CLFL         → channel_close()        → /close SYMBOL,MSG_ID
       · CLHF         → channel_close_half()   → /closehalf
       · CLPT         → channel_close_partial()→ /closepartial
       · MSENTRY      → channel_breakeven()    → /breakeven
       · SET SP/PP    → channel_update()       → /update or /edit
       · DZF          → channel_delete()       → /delete
       · AGAINENTER   → re-opens the original  → /open

5. Persist results as ParsedSignal + TakeProfit rows
6. Return list of ParsedSignal objects
```

### Signal Output Formats

| Kind | Command Format |
|---|---|
| `open` | `/open SYMBOL,DIR,PRICE,SL,TP1,TP2,...,MSG_ID,CHANNEL_ID,CHANNEL` |
| `edit` | `/edit SYMBOL,DIR,SL,TP1,TP2,...,MSG_ID` |
| `close` | `/close SYMBOL,MSG_ID[,TPn]` |
| `closeall` | `/closeall` |
| `deleteall` | `/deleteall` |
| `closehalf` | `/closehalf SYMBOL,MSG_ID` |
| `closehalfbe` | `/closehalfbe SYMBOL,MSG_ID` |
| `closepartial` | `/closepartial SYMBOL,MSG_ID` |
| `closepartialbe` | `/closepartialbe SYMBOL,MSG_ID` |
| `update` | `/update SYMBOL,DIR,SL\|TP,PRICE,MSG_ID` |
| `breakeven` | `/breakeven SYMBOL,MSG_ID` |
| `delete` | `/delete SYMBOL,MSG_ID` |

### Special Modes

| Feature | Config Field | Behaviour |
|---|---|---|
| Price range — average | `prefer_entry = 2` (default) | `2330/2335` → uses `2332.5` |
| Price range — first | `prefer_entry = 0` | `2330/2335` → uses `2330` |
| Price range — all signals | `prefer_entry = 3` | Emits one signal per price in the range |
| ALLORDER / multi-signal | `all_order = true` | Each BUY/SELL line becomes a separate signal |
| SL in pips | `sl_in_pips = true` | Appends `" pips"` suffix to SL value |
| TP in pips | `tp_in_pips = true` | Appends `" pips"` suffix to all TP values |
| Market order | `"MKO"` in text | Clears entry price (forces market execution) |
| Ignore message | `kw_ignore` keyword in text | Silently skips the entire message |
| Skip section | `kw_skip` pair | Strips enclosed text before parsing |
| Delimiter removal | `delimiters = "[]"` | Strips `[…]` from text before parsing |
| News filter | `news_filter = true` | Blocks new signals during high-impact news windows |
| Forwarded messages | `read_forwarded = false` | Ignores forwarded messages entirely |

---

## ChannelConfig — Keyword System

Each `ChannelConfig` maps the signal provider's language to internal parser tokens via comma-separated alias lists.

**Example:** Provider writes `"COMPRAR"` instead of `"BUY"`:
```
kw_buy = "COMPRAR,LONG"  →  replaces COMPRAR or LONG with  BUY  before parsing
kw_sell = "VENDER,SHORT" →  replaces VENDER  or SHORT with  SELL before parsing
```

### Keyword Fields Reference

| Field | Tab | Default | Purpose |
|---|---|---|---|
| `kw_entry_point` | Signal Keywords | `ENTRY` | Entry price label |
| `kw_buy` | Signal Keywords | `LONG` | BUY direction aliases |
| `kw_sell` | Signal Keywords | `SHORT` | SELL direction aliases |
| `kw_sl` | Signal Keywords | `SL` | Stop-loss label aliases |
| `kw_tp` | Signal Keywords | `TP` | Take-profit label aliases |
| `kw_market_order` | Signal Keywords | `""` | Forces market execution |
| `kw_close_tp1` | Update Keywords | `""` | Trigger close at TP1 |
| `kw_close_tp2` | Update Keywords | `""` | Trigger close at TP2 |
| `kw_close_tp3` | Update Keywords | `""` | Trigger close at TP3 |
| `kw_close_tp4` | Update Keywords | `""` | Trigger close at TP4 |
| `kw_close_full` | Update Keywords | `""` | Close full position |
| `kw_close_half` | Update Keywords | `""` | Close half position |
| `kw_close_partial` | Update Keywords | `""` | Close partial position |
| `kw_breakeven` | Update Keywords | `""` | Move SL to entry price |
| `kw_set_tp1`…`kw_set_tp5` | Update Keywords | `""` | Set individual TP levels |
| `kw_set_all_tp` | Update Keywords | `""` | Set all TPs at once |
| `kw_set_sl` | Update Keywords | `""` | Set a new SL value |
| `kw_delete_pending` | Update Keywords | `""` | Delete pending order |
| `kw_layer` | Additional | `""` | Re-entry / layer signal |
| `kw_close_all` | Additional | `""` | Close all positions |
| `kw_delete_all` | Additional | `""` | Delete all pending orders |
| `kw_ignore` | Additional | `""` | Skip this message entirely |
| `kw_skip` | Additional | `""` | Strip section before parsing |
| `kw_remove_sl` | Additional | `""` | Remove stop-loss |

### Behaviour Fields Reference

| Field | Default | Description |
|---|---|---|
| `use_ai` | `false` | GPT-based parsing (requires subscription) |
| `read_image` | `false` | OCR image extraction (requires subscription) |
| `delay_ms` | `0` | Milliseconds to wait before dispatching |
| `prefer_entry` | `2` (Average) | `0`=First `1`=Second `2`=Average `3`=All |
| `sl_in_pips` | `false` | Interpret SL as pips |
| `tp_in_pips` | `false` | Interpret TPs as pips |
| `delimiters` | `""` | 2-char pair to strip (e.g. `"[]"`) |
| `all_order` | `false` | Emit one signal per BUY/SELL line |
| `read_forwarded` | `true` | Process forwarded messages |
| `news_filter` | `false` | Block signals during news windows |

---

## Default Config Values

When a client is created, `ChannelConfig` is auto-provisioned with these shipping defaults — enough to parse a standard signal out of the box:

```json
{
  "kw_entry_point": "ENTRY",
  "kw_buy": "LONG",
  "kw_sell": "SHORT",
  "kw_sl": "SL",
  "kw_tp": "TP",
  "kw_market_order": "",
  "use_ai": false,
  "read_image": false,
  "kw_close_tp1": "",
  "kw_close_tp2": "",
  "kw_close_tp3": "",
  "kw_close_tp4": "",
  "kw_close_full": "",
  "kw_close_half": "",
  "kw_close_partial": "",
  "kw_breakeven": "",
  "kw_set_tp1": "",
  "kw_set_tp2": "",
  "kw_set_tp3": "",
  "kw_set_tp4": "",
  "kw_set_tp5": "",
  "kw_set_all_tp": "",
  "kw_set_sl": "",
  "kw_delete_pending": "",
  "kw_layer": "",
  "kw_close_all": "",
  "kw_delete_all": "",
  "kw_ignore": "",
  "kw_skip": "",
  "kw_remove_sl": "",
  "delay_ms": 0,
  "prefer_entry": 2,
  "sl_in_pips": false,
  "tp_in_pips": false,
  "delimiters": "",
  "all_order": false,
  "read_forwarded": true,
  "news_filter": false
}
```

The `kw_close_tp1`–`kw_close_tp4` fields are blank by default because they depend entirely on what your specific signal provider sends (e.g. `"TP1 HIT"`, `"TP1 REACHED"`, etc.).

---

## Interactive Docs

| Interface | URL |
|---|---|
| Swagger UI | http://127.0.0.1:8000/api/docs/ |
| ReDoc | http://127.0.0.1:8000/api/redoc/ |
| Django Admin | http://127.0.0.1:8000/admin/ |

The Swagger UI requires the `X-API-KEY` header — click **Authorize** and enter your key.

---

## Complete Test Flow

Here is the end-to-end sequence to test the full copier/parser/config setup:

```bash
API="http://127.0.0.1:8000/api/v1"
KEY="9f3b2c6e1a7d4f8b5c0e2a9d6f1b3c7e8a4d0f5c2b9e6a1d7c3f8b4e0a2d6c1"

# 1. Create a client (ChannelConfig auto-created with defaults)
curl -X POST "$API/clients/" \
  -H "X-API-KEY: $KEY" -H "Content-Type: application/json" \
  -d '{"client_id":"1008","telegram_number":"+19876543210",
       "channel_id":"888333444","broker_account_number":"52785001",
       "broker_server":"MetaQuotes-Demo","is_active":true}'

# 2. (Optional) Update the config — e.g. override keyword aliases
curl -X PATCH "$API/clients/1008/" \
  -H "X-API-KEY: $KEY" -H "Content-Type: application/json" \
  -d '{"config":{"kw_buy":"LONG","kw_sell":"SHORT","prefer_entry":2}}'

# 3. Listener microservice posts a raw message
curl -X POST "$API/webhook/receiver/" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"1008","telegram_number":"+19876543210",
       "channel_id":"888333444","broker_account_number":"52785001",
       "broker_server":"MetaQuotes-Demo","message_id":"2004",
       "text":"XAUUSD LONG 3350.0\nStop loss 3300.0\nTP1 3400.0\nTP2 3450.0",
       "is_forwarded":false,"is_edited":false}'

# 4. Parse the stored message
curl -X POST "$API/parser/parse/" \
  -H "X-API-KEY: $KEY" -H "Content-Type: application/json" \
  -d '{"client_id":"1008","message_id":"2004","force_reparse":false}'

# 5. List all signals for this client
curl "$API/parser/signals/?client_id=1008" -H "X-API-KEY: $KEY"

# 6. Update signal status (e.g. after MT4/MT5 executes the trade)
curl -X PATCH "$API/parser/signals/1/update/" \
  -H "X-API-KEY: $KEY" -H "Content-Type: application/json" \
  -d '{"status":"OPEN"}'
```
