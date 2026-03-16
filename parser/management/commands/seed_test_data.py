"""
management/commands/seed_test_data.py
======================================
Creates realistic test data and exercises every API endpoint.

Usage
-----
    # seed only (no API calls)
    python manage.py seed_test_data

    # seed + run full API test suite (requires server running)
    python manage.py seed_test_data --test

    # wipe everything first then seed fresh
    python manage.py seed_test_data --reset

    # wipe + seed + test
    python manage.py seed_test_data --reset --test

    # custom base URL (default: http://127.0.0.1:8000)
    python manage.py seed_test_data --test --base-url http://localhost:8000
"""

import json
import sys
import textwrap

import requests as http
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# ── Model imports ─────────────────────────────────────────────────────────────
from client.models import ClientConfig, WebhookMessage
from parser.models import ChannelConfig, ParsedSignal, TakeProfit


# =============================================================================
# Seed data definitions
# =============================================================================

CLIENTS = [
    {
        "client_id":            "CLIENT_GOLD",
        "telegram_number":      "+19876543210",
        "channel_id":           "999111222",
        "broker_account_number":"52785001",
        "broker_server":        "MetaQuotes-Demo",
    },
    {
        "client_id":            "CLIENT_FX",
        "telegram_number":      "+19876543211",
        "channel_id":           "888333444",
        "broker_account_number":"52785002",
        "broker_server":        "MetaQuotes-Demo",
    },
]

# ChannelConfig per client – mirrors the desktop Config Keyword dialog
CHANNEL_CONFIGS = {
    # Gold signals provider uses "Stop loss" and "Take profit" as keywords
    "CLIENT_GOLD": {
        "kw_sl":            "STOP LOSS",
        "kw_tp":            "TAKE PROFIT",
        "kw_buy":           "BUY,LONG",
        "kw_sell":          "SELL,SHORT",
        "kw_entry_point":   "",
        "kw_market_order":  "NOW",
        "kw_close_full":    "CLOSED",
        "kw_close_tp1":     "TP1 REACHED",
        "kw_close_tp2":     "TP2 REACHED",
        "kw_close_tp3":     "TP3 REACHED",
        "kw_close_tp4":     "TP4 REACHED",
        "kw_breakeven":     "MOVE TO BE",
        "kw_close_all":     "CLOSE ALL",
        "kw_delete_all":    "CANCEL ALL",
        "kw_ignore":        "ANALYSIS",
        "prefer_entry":     0,   # First Price
        "sl_in_pips":       False,
        "tp_in_pips":       False,
        "all_order":        False,
        "read_forwarded":   True,
        "news_filter":      False,
        "delay_ms":         0,
        "delimiters":       "",
    },
    # FX provider uses standard SL/TP keywords but with LONG/SHORT direction
    "CLIENT_FX": {
        "kw_sl":            "SL",
        "kw_tp":            "TP",
        "kw_buy":           "LONG",
        "kw_sell":          "SHORT",
        "kw_entry_point":   "ENTRY",
        "kw_market_order":  "",
        "kw_close_full":    "",
        "kw_close_tp1":     "",
        "kw_close_tp2":     "",
        "kw_close_tp3":     "",
        "kw_close_tp4":     "",
        "kw_breakeven":     "",
        "kw_close_all":     "",
        "kw_delete_all":    "",
        "kw_ignore":        "",
        "prefer_entry":     2,   # Average Price
        "sl_in_pips":       False,
        "tp_in_pips":       False,
        "all_order":        False,
        "read_forwarded":   True,
        "news_filter":      False,
        "delay_ms":         0,
        "delimiters":       "",
    },
}

# WebhookMessage payloads – every major signal scenario
MESSAGES = [
    # ── CLIENT_GOLD messages ──────────────────────────────────────────────────
    {
        "label":                  "GOLD open (limit entry, 5 TPs, Stop loss alias)",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1001",
        "text": (
            "XAUUSD BUY 2330.5\n"
            "Stop loss 2310.0\n"
            "Take profit 1: 2345.0\n"
            "Take profit 2: 2360.0\n"
            "Take profit 3: 2380.0\n"
            "Take profit 4: 2400.0\n"
            "Take profit 5: 2420.0"
        ),
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "GOLD open (plain single-line, STOP LOSS alias)",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1002",
        "text": (
            "XAUUSD BUY  instant 5539.0 Stop loss 5000.0 "
            "TP1 6000.0 TP2 6010.0 Tp3 6020.0 Tp4 6030.0 Tp5 6040.0"
        ),
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "GOLD market order (no entry price)",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1003",
        "text": (
            "XAUUSD SELL\n"
            "Stop loss 2360.0\n"
            "TP1 2340.0\n"
            "TP2 2320.0"
        ),
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "GOLD TP1 hit reply",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1004",
        "text":                   "TP1 REACHED",
        "replied_message_id":     "1001",
        "replied_text": (
            "XAUUSD BUY 2330.5\n"
            "Stop loss 2310.0\n"
            "Take profit 1: 2345.0\n"
            "Take profit 2: 2360.0"
        ),
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "GOLD close full reply",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1005",
        "text":                   "CLOSED",
        "replied_message_id":     "1001",
        "replied_text": (
            "XAUUSD BUY 2330.5\n"
            "Stop loss 2310.0\n"
            "TP1 2345.0"
        ),
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "GOLD breakeven reply",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1006",
        "text":                   "MOVE TO BE",
        "replied_message_id":     "1001",
        "replied_text": (
            "XAUUSD BUY 2330.5\n"
            "Stop loss 2310.0\n"
            "TP1 2345.0"
        ),
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "GOLD ignored signal (contains ANALYSIS)",
        "client_id":              "CLIENT_GOLD",
        "message_id":             "1007",
        "text": (
            "ANALYSIS: XAUUSD BUY 2350\n"
            "Stop loss 2330\n"
            "TP1 2370"
        ),
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
    # ── CLIENT_FX messages ────────────────────────────────────────────────────
    {
        "label":                  "FX LONG alias + range entry (prefer average)",
        "client_id":              "CLIENT_FX",
        "message_id":             "2001",
        "text": (
            "USDJPY LONG 152.500/152.600\n"
            "SL 153.200\n"
            "TP1 152.000\n"
            "TP2 151.500\n"
            "TP3 151.000"
        ),
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "FX SHORT alias",
        "client_id":              "CLIENT_FX",
        "message_id":             "2002",
        "text": (
            "EURUSD SHORT 1.0850\n"
            "SL 1.0920\n"
            "TP1 1.0780\n"
            "TP2 1.0700"
        ),
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "FX update SL reply (SET SP)",
        "client_id":              "CLIENT_FX",
        "message_id":             "2003",
        "text":                   "SET SP 152.400",
        "replied_message_id":     "2001",
        "replied_text": (
            "USDJPY LONG 152.550\n"
            "SL 153.200\n"
            "TP1 152.000"
        ),
        "is_forwarded":           False,
        "is_edited":              False,
    },
    {
        "label":                  "FX close all (CLZP)",
        "client_id":              "CLIENT_FX",
        "message_id":             "2004",
        "text":                   "CLZP",
        "replied_message_id":     "",
        "replied_text":           "",
        "is_forwarded":           False,
        "is_edited":              False,
    },
]


# =============================================================================
# Management command
# =============================================================================

class Command(BaseCommand):
    help = (
        "Seed test data (clients, configs, webhook messages) and optionally "
        "run the full API test suite against a running server."
    )

    # ── colour helpers ────────────────────────────────────────────────────────

    def _ok(self, msg):     self.stdout.write(self.style.SUCCESS(f"  ✅  {msg}"))
    def _warn(self, msg):   self.stdout.write(self.style.WARNING(f"  ⚠️   {msg}"))
    def _err(self, msg):    self.stdout.write(self.style.ERROR(f"  ❌  {msg}"))
    def _head(self, msg):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"── {msg} ──"))

    # ── CLI arguments ─────────────────────────────────────────────────────────

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing test data before seeding.",
        )
        parser.add_argument(
            "--test",
            action="store_true",
            help="Run the API test suite after seeding (server must be running).",
        )
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:8000",
            help="Base URL of the running Django server (default: http://127.0.0.1:8000).",
        )

    # ── entry point ───────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/")

        if options["reset"]:
            self._reset()

        self._seed_clients()
        self._seed_configs()
        self._seed_messages()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Seeding complete."))

        if options["test"]:
            self.stdout.write("")
            suite = ApiTestSuite(self, base_url)
            suite.run()

    # ── reset ─────────────────────────────────────────────────────────────────

    def _reset(self):
        self._head("Resetting existing test data")
        client_ids = [c["client_id"] for c in CLIENTS]
        deleted, _ = ClientConfig.objects.filter(client_id__in=client_ids).delete()
        self._ok(f"Deleted {deleted} rows (cascade includes all related data)")

    # ── seed helpers ──────────────────────────────────────────────────────────

    @transaction.atomic
    def _seed_clients(self):
        self._head("Seeding ClientConfig")
        for data in CLIENTS:
            obj, created = ClientConfig.objects.update_or_create(
                client_id=data["client_id"],
                defaults=data,
            )
            verb = "Created" if created else "Updated"
            self._ok(f"{verb} → {obj.client_id}  ({obj.telegram_number})")

    @transaction.atomic
    def _seed_configs(self):
        self._head("Seeding ChannelConfig")
        for client_id, cfg_data in CHANNEL_CONFIGS.items():
            try:
                client = ClientConfig.objects.get(client_id=client_id)
            except ClientConfig.DoesNotExist:
                self._err(f"ClientConfig '{client_id}' not found — skipping config")
                continue

            obj, created = ChannelConfig.objects.update_or_create(
                client=client,
                defaults=cfg_data,
            )
            verb = "Created" if created else "Updated"
            self._ok(
                f"{verb} → {client_id}  "
                f"(kw_sl='{obj.kw_sl}'  kw_buy='{obj.kw_buy}')"
            )

    @transaction.atomic
    def _seed_messages(self):
        self._head("Seeding WebhookMessage")
        for msg in MESSAGES:
            label = msg.pop("label")
            client_id = msg.pop("client_id")

            try:
                client = ClientConfig.objects.get(client_id=client_id)
            except ClientConfig.DoesNotExist:
                self._err(f"Client '{client_id}' not found — skipping '{label}'")
                msg["client_id"] = client_id   # restore for idempotency
                continue

            obj, created = WebhookMessage.objects.update_or_create(
                client=client,
                message_id=msg["message_id"],
                defaults={k: v for k, v in msg.items() if k != "message_id"},
            )
            verb = "Created" if created else "Updated"
            self._ok(f'{verb} → [{client_id}] msg_id={obj.message_id}  "{label}"')

            # Restore for idempotency
            msg["label"]     = label
            msg["client_id"] = client_id


# =============================================================================
# API test suite
# =============================================================================

class ApiTestSuite:
    """
    Runs a series of HTTP requests against the running server and reports
    pass / fail for each scenario.
    """

    PASS = 0
    FAIL = 0

    def __init__(self, cmd: Command, base_url: str):
        self.cmd      = cmd
        self.base_url = base_url
        self.session  = http.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ok(self, msg):    self.PASS += 1; self.cmd._ok(msg)
    def _fail(self, msg):  self.FAIL += 1; self.cmd._err(msg)
    def _head(self, msg):  self.cmd._head(msg)

    def _request(self, method: str, path: str, **kwargs) -> http.Response:
        url = self.base_url + path
        try:
            resp = self.session.request(method, url, **kwargs)
            return resp
        except http.exceptions.ConnectionError:
            raise CommandError(
                f"Could not connect to {self.base_url}. "
                "Make sure the server is running before using --test."
            )

    def _check(self, label: str, resp: http.Response, expected_status: int,
               body_checks: dict | None = None):
        """Assert status code and optionally check response body fields."""
        if resp.status_code != expected_status:
            self._fail(
                f"{label}  →  HTTP {resp.status_code} (expected {expected_status})\n"
                f"         {resp.text[:300]}"
            )
            return False

        if body_checks:
            try:
                data = resp.json()
            except Exception:
                self._fail(f"{label}  →  response is not valid JSON")
                return False

            # Handle both list and dict responses
            item = data[0] if isinstance(data, list) and data else data
            for key, expected in body_checks.items():
                actual = item.get(key) if isinstance(item, dict) else None
                if actual != expected:
                    self._fail(
                        f"{label}  →  [{key}] expected {expected!r} got {actual!r}"
                    )
                    return False

        self._ok(f"{label}  →  HTTP {resp.status_code}")
        return True

    # ── test sections ─────────────────────────────────────────────────────────

    def run(self):
        self._head("Running API test suite")
        self.cmd.stdout.write(f"  Base URL: {self.base_url}")
        self.cmd.stdout.write("")

        self._test_client_crud()
        self._test_channel_config_crud()
        self._test_webhook_receiver()
        self._test_parse_open_signals()
        self._test_parse_reply_signals()
        self._test_parse_edge_cases()
        self._test_signal_list_and_filters()
        self._test_signal_status_update()
        self._test_tp_endpoint()
        self._test_force_reparse()
        self._test_error_cases()

        self.cmd.stdout.write("")
        total = self.PASS + self.FAIL
        if self.FAIL == 0:
            self.cmd.stdout.write(
                self.cmd.style.SUCCESS(
                    f"  All {total} API tests passed ✅"
                )
            )
        else:
            self.cmd.stdout.write(
                self.cmd.style.ERROR(
                    f"  {self.FAIL} / {total} tests FAILED ❌"
                )
            )

    def _test_client_crud(self):
        self._head("1. ClientConfig CRUD")

        # List
        resp = self._request("GET", "/api/clients/")
        self._check("GET /api/clients/  list", resp, 200)

        # Retrieve
        resp = self._request("GET", "/api/clients/CLIENT_GOLD/")
        self._check("GET /api/clients/CLIENT_GOLD/  retrieve",
                    resp, 200, {"client_id": "CLIENT_GOLD"})

        # 404 on unknown
        resp = self._request("GET", "/api/clients/UNKNOWN_CLIENT/")
        self._check("GET /api/clients/UNKNOWN_CLIENT/  404", resp, 404)

        # Partial update
        resp = self._request("PATCH", "/api/clients/CLIENT_GOLD/",
                             json={"is_active": True})
        self._check("PATCH /api/clients/CLIENT_GOLD/  partial update", resp, 200)

    def _test_channel_config_crud(self):
        self._head("2. ChannelConfig CRUD")

        # Retrieve existing
        resp = self._request("GET", "/api/clients/CLIENT_GOLD/config/")
        self._check("GET  config  CLIENT_GOLD", resp, 200,
                    {"kw_sl": "STOP LOSS"})

        resp = self._request("GET", "/api/clients/CLIENT_FX/config/")
        self._check("GET  config  CLIENT_FX", resp, 200,
                    {"kw_buy": "LONG"})

        # Partial update keyword
        resp = self._request("PATCH", "/api/clients/CLIENT_GOLD/config/",
                             json={"kw_market_order": "INSTANT"})
        self._check("PATCH config  update kw_market_order", resp, 200)

        # Invalid delimiter
        resp = self._request("PATCH", "/api/clients/CLIENT_GOLD/config/",
                             json={"delimiters": "abc"})
        self._check("PATCH config  invalid delimiter → 400", resp, 400)

    def _test_webhook_receiver(self):
        self._head("3. Webhook receiver")

        # Valid payload that matches CLIENT_GOLD
        resp = self._request("POST", "/api/webhook/", json={
            "client_id":            "CLIENT_GOLD",
            "telegram_number":      "+19876543210",
            "channel_id":           "999111222",
            "broker_account_number":"52785001",
            "broker_server":        "MetaQuotes-Demo",
            "message_id":           "9001",
            "text":                 "XAUUSD BUY 2330\nStop loss 2310\nTP1 2350",
            "replied_message_id":   "",
            "replied_text":         "",
            "is_forwarded":         False,
            "is_edited":            False,
        })
        self._check("POST /webhook/  valid payload", resp, 201)

        # Mismatched telegram_number
        resp = self._request("POST", "/api/webhook/", json={
            "client_id":            "CLIENT_GOLD",
            "telegram_number":      "+10000000000",   # wrong
            "channel_id":           "999111222",
            "broker_account_number":"52785001",
            "broker_server":        "MetaQuotes-Demo",
            "message_id":           "9002",
            "text":                 "anything",
            "replied_message_id":   "",
            "replied_text":         "",
        })
        self._check("POST /webhook/  mismatched telegram_number → 400", resp, 400)

        # Unknown client_id
        resp = self._request("POST", "/api/webhook/", json={
            "client_id":            "NO_SUCH_CLIENT",
            "telegram_number":      "+10000000000",
            "channel_id":           "000",
            "broker_account_number":"000",
            "broker_server":        "none",
            "message_id":           "9003",
            "text":                 "test",
        })
        self._check("POST /webhook/  unknown client_id → 400", resp, 400)

    def _test_parse_open_signals(self):
        self._head("4. Parsing — open signals")

        cases = [
            ("1001", "CLIENT_GOLD", "open",  "XAUUSD", "BUY",  "2330.5"),
            ("1002", "CLIENT_GOLD", "open",  "XAUUSD", "BUY",  "5539.0"),
            ("1003", "CLIENT_GOLD", "open",  "XAUUSD", "SELL", ""),       # market order
            ("2001", "CLIENT_FX",   "open",  "USDJPY", "BUY",  "152.55"), # average of range
            ("2002", "CLIENT_FX",   "open",  "EURUSD", "SELL", "1.085"),
        ]

        for msg_id, client_id, exp_kind, exp_sym, exp_dir, exp_entry in cases:
            resp = self._request("POST", "/api/parser/parse/",
                                 json={"client_id": client_id, "message_id": msg_id})
            ok = self._check(
                f"parse  {client_id}  msg={msg_id}  ({exp_sym} {exp_dir})",
                resp, 201,
                {"kind": exp_kind, "symbol": exp_sym, "direction": exp_dir},
            )
            if ok and exp_entry:
                data = resp.json()
                actual_entry = data[0].get("entry_price", "") if data else ""
                # Allow for floating point rounding (152.55 vs 152.55000...)
                if not actual_entry.startswith(exp_entry.rstrip("0").rstrip(".")):
                    self._fail(
                        f"  entry_price  expected ~{exp_entry!r}  got {actual_entry!r}"
                    )

    def _test_parse_reply_signals(self):
        self._head("5. Parsing — reply signals")

        cases = [
            ("1004", "CLIENT_GOLD", "close",     "XAUUSD", "TP1"),
            ("1005", "CLIENT_GOLD", "close",     "XAUUSD", ""),
            ("1006", "CLIENT_GOLD", "breakeven", "XAUUSD", ""),
            ("2003", "CLIENT_FX",   "update",    "USDJPY", ""),
        ]

        for msg_id, client_id, exp_kind, exp_sym, exp_close_tp in cases:
            resp = self._request("POST", "/api/parser/parse/",
                                 json={"client_id": client_id, "message_id": msg_id})
            checks = {"kind": exp_kind, "symbol": exp_sym}
            if exp_close_tp:
                checks["close_tp"] = exp_close_tp
            self._check(
                f"parse  {client_id}  msg={msg_id}  (kind={exp_kind})",
                resp, 201, checks,
            )

    def _test_parse_edge_cases(self):
        self._head("6. Parsing — edge cases")

        # Message containing TIGNORE should parse but produce 0 signals
        resp = self._request("POST", "/api/parser/parse/",
                             json={"client_id": "CLIENT_GOLD", "message_id": "1007"})
        if resp.status_code == 201:
            data = resp.json()
            if len(data) == 0:
                self._ok("parse  TIGNORE  → 201, 0 signals produced")
            else:
                self._fail(
                    f"parse  TIGNORE  → expected 0 signals, got {len(data)}"
                )
        else:
            self._check("parse  TIGNORE", resp, 201)

        # CLZP (close-all) produces a closeall signal
        resp = self._request("POST", "/api/parser/parse/",
                             json={"client_id": "CLIENT_FX", "message_id": "2004"})
        self._check("parse  CLZP  → closeall", resp, 201,
                    {"kind": "closeall"})

        # Already parsed guard
        resp = self._request("POST", "/api/parser/parse/",
                             json={"client_id": "CLIENT_GOLD", "message_id": "1001"})
        self._check("parse  duplicate  → 400 already parsed", resp, 400)

    def _test_signal_list_and_filters(self):
        self._head("7. Signal list + filters")

        resp = self._request("GET", "/api/parser/signals/")
        self._check("GET  /signals/  list all", resp, 200)
        if resp.status_code == 200:
            count = len(resp.json())
            self.cmd.stdout.write(f"       total signals in DB: {count}")

        resp = self._request("GET", "/api/parser/signals/?client_id=CLIENT_GOLD")
        self._check("GET  /signals/?client_id=CLIENT_GOLD", resp, 200)

        resp = self._request("GET", "/api/parser/signals/?symbol=XAUUSD")
        self._check("GET  /signals/?symbol=XAUUSD", resp, 200)

        resp = self._request("GET", "/api/parser/signals/?kind=open")
        self._check("GET  /signals/?kind=open", resp, 200)

        resp = self._request("GET", "/api/parser/signals/?status=PENDING")
        self._check("GET  /signals/?status=PENDING", resp, 200)

        # Combined filters
        resp = self._request(
            "GET",
            "/api/parser/signals/?client_id=CLIENT_GOLD&symbol=XAUUSD&kind=open",
        )
        self._check(
            "GET  /signals/?client_id=CLIENT_GOLD&symbol=XAUUSD&kind=open", resp, 200
        )

    def _test_signal_status_update(self):
        self._head("8. Signal status update")

        # Get the first XAUUSD BUY signal
        resp = self._request(
            "GET", "/api/parser/signals/?client_id=CLIENT_GOLD&kind=open"
        )
        if resp.status_code != 200 or not resp.json():
            self._fail("status update — could not find a signal to update")
            return

        signal_id = resp.json()[0]["id"]

        # Update status to OPEN
        resp = self._request(
            "PATCH",
            f"/api/parser/signals/{signal_id}/update/",
            json={"status": "OPEN"},
        )
        self._check(
            f"PATCH  /signals/{signal_id}/update/  status→OPEN", resp, 200,
            {"status": "OPEN"},
        )

        # Update blocked_by_news_filter
        resp = self._request(
            "PATCH",
            f"/api/parser/signals/{signal_id}/update/",
            json={"blocked_by_news_filter": True},
        )
        self._check(
            f"PATCH  /signals/{signal_id}/update/  blocked→True", resp, 200,
            {"blocked_by_news_filter": True},
        )

        # Reject non-allowlist field
        resp = self._request(
            "PATCH",
            f"/api/parser/signals/{signal_id}/update/",
            json={"symbol": "HACKED"},
        )
        self._check(
            f"PATCH  /signals/{signal_id}/update/  non-allowlist field → 400",
            resp, 400,
        )

    def _test_tp_endpoint(self):
        self._head("9. TakeProfit endpoint")

        # Find signal with most TPs (msg 1001 has 5 TPs)
        resp = self._request(
            "GET", "/api/parser/signals/?client_id=CLIENT_GOLD&symbol=XAUUSD&kind=open"
        )
        if resp.status_code != 200 or not resp.json():
            self._fail("tps test — could not find a GOLD open signal")
            return

        signal_id = resp.json()[0]["id"]

        # All TPs
        resp = self._request("GET", f"/api/parser/signals/{signal_id}/tps/")
        self._check(f"GET  /signals/{signal_id}/tps/  all", resp, 200)
        if resp.status_code == 200:
            tps = resp.json()
            self.cmd.stdout.write(f"       TP count: {len(tps)}")
            if tps:
                labels = [tp["label"] for tp in tps]
                self.cmd.stdout.write(f"       Labels:   {labels}")

        # Original TPs only
        resp = self._request(
            "GET", f"/api/parser/signals/{signal_id}/tps/?edit=false"
        )
        self._check(f"GET  /signals/{signal_id}/tps/?edit=false  originals", resp, 200)

        # Edit-target TPs (should be empty for a fresh open signal)
        resp = self._request(
            "GET", f"/api/parser/signals/{signal_id}/tps/?edit=true"
        )
        self._check(f"GET  /signals/{signal_id}/tps/?edit=true  edit targets", resp, 200)

        # 404 on nonexistent signal
        resp = self._request("GET", "/api/parser/signals/999999/tps/")
        self._check("GET  /signals/999999/tps/  → 404", resp, 404)

    def _test_force_reparse(self):
        self._head("10. Force reparse")

        # First ensure msg 1001 has been parsed already
        # (done in _test_parse_open_signals)

        # Reparse with force_reparse=true
        resp = self._request("POST", "/api/parser/parse/", json={
            "client_id":    "CLIENT_GOLD",
            "message_id":   "1001",
            "force_reparse": True,
        })
        self._check(
            "POST  parse  force_reparse=true  → 201", resp, 201,
            {"kind": "open", "symbol": "XAUUSD"},
        )

    def _test_error_cases(self):
        self._head("11. Error cases")

        # Parse unknown message_id
        resp = self._request("POST", "/api/parser/parse/", json={
            "client_id":  "CLIENT_GOLD",
            "message_id": "9999999",
        })
        self._check("parse  unknown message_id → 400", resp, 400)

        # Parse client with no ChannelConfig
        # Create a bare client without config to test this
        ClientConfig.objects.get_or_create(
            client_id="CLIENT_NOCONFIG",
            defaults={
                "telegram_number":       "+10000000001",
                "channel_id":            "111",
                "broker_account_number": "111",
                "broker_server":         "none",
            },
        )
        # Insert a raw webhook message for this client
        client = ClientConfig.objects.get(client_id="CLIENT_NOCONFIG")
        WebhookMessage.objects.get_or_create(
            client=client, message_id="X001",
            defaults={"text": "XAUUSD BUY 2330", "is_forwarded": False, "is_edited": False},
        )
        resp = self._request("POST", "/api/parser/parse/", json={
            "client_id":  "CLIENT_NOCONFIG",
            "message_id": "X001",
        })
        self._check("parse  no ChannelConfig → 400", resp, 400)

        # Retrieve nonexistent signal
        resp = self._request("GET", "/api/parser/signals/999999/")
        self._check("GET  /signals/999999/  → 404", resp, 404)

        # Update nonexistent signal
        resp = self._request(
            "PATCH", "/api/parser/signals/999999/update/",
            json={"status": "OPEN"},
        )
        self._check("PATCH  /signals/999999/update/  → 404", resp, 404)