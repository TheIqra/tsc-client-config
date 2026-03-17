from rest_framework import serializers

# Import models from their canonical locations.
# parser.models no longer defines its own WebhookMessage — the canonical
# one lives in client.models (FK → ClientConfig).
from client.models import ClientConfig, WebhookMessage
from .models import ChannelConfig, ParsedSignal, TakeProfit
from .parser import preprocess_text, route_signal


# ─────────────────────────────────────────────────────────────────────────────
# ChannelConfigSerializer  (create / read / update keyword config)
# ─────────────────────────────────────────────────────────────────────────────

class ChannelConfigSerializer(serializers.ModelSerializer):
    """
    Full serializer for ChannelConfig.

    ``client_id`` is exposed as a read-only string sourced from the related
    ClientConfig so the API response is self-contained.

    The ``client`` FK is intentionally excluded from writable fields —
    it is injected by the view's ``perform_create()`` so the client is always
    determined by the URL parameter, never by the request body.
    """

    # Read-only identity field sourced from the FK
    client_id = serializers.CharField(source="client.client_id", read_only=True)

    class Meta:
        model  = ChannelConfig
        fields = [
            "id",
            "client_id",
            "channel_id",
            # Tab 1 – Signal Keywords
            "kw_entry_point",
            "kw_buy",
            "kw_sell",
            "kw_sl",
            "kw_tp",
            "kw_market_order",
            "use_ai",
            "read_image",
            # Tab 2 – Update Keywords
            "kw_close_tp1",
            "kw_close_tp2",
            "kw_close_tp3",
            "kw_close_tp4",
            "kw_close_full",
            "kw_close_half",
            "kw_close_partial",
            "kw_breakeven",
            "kw_set_tp1",
            "kw_set_tp2",
            "kw_set_tp3",
            "kw_set_tp4",
            "kw_set_tp5",
            "kw_set_all_tp",
            "kw_set_sl",
            "kw_delete_pending",
            # Tab 3 – Additional Keywords
            "kw_layer",
            "kw_close_all",
            "kw_delete_all",
            "kw_ignore",
            "kw_skip",
            "kw_remove_sl",
            # Behaviour options
            "delay_ms",
            "prefer_entry",
            "sl_in_pips",
            "tp_in_pips",
            "delimiters",
            "all_order",
            "read_forwarded",
            "news_filter",
        ]
        read_only_fields = ["client_id"]

    def validate_delimiters(self, value: str) -> str:
        """Delimiters must be exactly 2 characters or empty."""
        value = value.strip()
        if value and len(value) != 2:
            raise serializers.ValidationError(
                "Delimiters must be exactly 2 characters (e.g. '[]') or left blank."
            )
        return value

    def validate(self, attrs):
        """Normalise all keyword fields: strip whitespace, uppercase."""
        keyword_fields = [
            "kw_entry_point", "kw_buy", "kw_sell", "kw_sl", "kw_tp",
            "kw_market_order", "kw_close_tp1", "kw_close_tp2", "kw_close_tp3",
            "kw_close_tp4", "kw_close_full", "kw_close_half", "kw_close_partial",
            "kw_breakeven", "kw_set_tp1", "kw_set_tp2", "kw_set_tp3", "kw_set_tp4",
            "kw_set_tp5", "kw_set_all_tp", "kw_set_sl", "kw_delete_pending",
            "kw_layer", "kw_close_all", "kw_delete_all", "kw_ignore",
            "kw_skip", "kw_remove_sl",
        ]
        for field in keyword_fields:
            value = attrs.get(field)
            if isinstance(value, str):
                attrs[field] = value.strip().upper()
        return attrs


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_signal_keywords(cfg: ChannelConfig) -> set[str]:
    """
    Derive the BUY/SELL keyword set from ChannelConfig aliases.

    The canonical internal keywords are always included.  Any extra aliases
    stored in kw_buy / kw_sell (comma-separated) are added on top so that
    a provider spelling like LONG or SHORT is also detected.
    """
    keywords = {"BUY", "SELL"}
    for alias_field in (cfg.kw_buy, cfg.kw_sell):
        for item in alias_field.split(","):
            item = item.strip().upper()
            if item:
                keywords.add(item)
    return keywords


def _persist_parsed_results(
    results: list[dict],
    message,              # client.models.WebhookMessage instance
) -> list[ParsedSignal]:
    """
    Persist every result dict returned by route_signal() as a
    ParsedSignal row with its child TakeProfit rows.

    Returns the list of created ParsedSignal instances.
    """
    created: list[ParsedSignal] = []

    for res in results:
        # Create the ParsedSignal row
        signal = ParsedSignal.objects.create(
            message      = message,
            kind         = res["kind"],
            symbol       = res["symbol"],
            direction    = res["direction"],
            entry_price  = res["entry_price"],
            sl           = res["sl"],
            new_sl       = res["new_sl"],
            close_tp     = res["close_tp"],
            command_text = res["command"],
            status       = ParsedSignal.Status.PENDING,
        )

        # Create original TP rows (from open/edit signals)
        for order, value in enumerate(res.get("tps", []), start=1):
            signal.add_tp(value=value, order=order)

        # Create edit-target TP rows (from update commands)
        for order, value in enumerate(res.get("new_tps", []), start=1):
            TakeProfit.objects.create(
                signal         = signal,
                order          = order,
                value          = value,
                is_edit_target = True,
            )

        created.append(signal)

    return created


# ─────────────────────────────────────────────────────────────────────────────
# 1.  TakeProfitSerializer  (read-only)
# ─────────────────────────────────────────────────────────────────────────────

class TakeProfitSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a single TP level.

    ``label`` is a computed property (TP1, TP2, …) exposed as a read-only
    field so API consumers can display it without computing it themselves.
    """

    label = serializers.CharField(read_only=True)

    class Meta:
        model  = TakeProfit
        fields = ["order", "value", "label", "hit_at", "is_edit_target"]


# ─────────────────────────────────────────────────────────────────────────────
# 2.  ParsedSignalSerializer  (read-only)
# ─────────────────────────────────────────────────────────────────────────────

class ParsedSignalSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for a ParsedSignal row.

    Schema mirrors the route_signal() result dict exactly so that API
    consumers see the same shape regardless of whether they call to_json()
    or this serializer.

    ``tps``      – original TP rows (is_edit_target=False), ordered by order
    ``new_tps``  – edit-target TP rows (is_edit_target=True), ordered by order
    ``msg_id``   – sourced from the related WebhookMessage (client.models)
    ``channel_id``, ``channel`` – sourced from WebhookMessage → ClientConfig
    """

    # Nested TPs split by purpose
    tps = serializers.SerializerMethodField()
    new_tps = serializers.SerializerMethodField()

    # Flatten FK traversals into flat fields (mirrors to_json() keys)
    # WebhookMessage now has a FK `client` → ClientConfig
    msg_id     = serializers.CharField(source="message.message_id",           read_only=True)
    channel_id = serializers.CharField(source="message.client.channel_id",    read_only=True)
    channel    = serializers.CharField(source="message.client.client_id",     read_only=True)

    # command is stored in command_text on the model; expose as "command"
    command = serializers.CharField(source="command_text", read_only=True)

    class Meta:
        model  = ParsedSignal
        fields = [
            "id",
            "kind",
            "command",
            "symbol",
            "direction",
            "entry_price",
            "sl",
            "tps",
            "msg_id",
            "channel_id",
            "channel",
            "close_tp",
            "new_sl",
            "new_tps",
            "status",
            "blocked_by_news_filter",
            "parsed_at",
        ]
        read_only_fields = fields  # entire serializer is read-only

    def get_tps(self, obj: ParsedSignal) -> list[dict]:
        qs = obj.take_profits.filter(is_edit_target=False).order_by("order")
        return TakeProfitSerializer(qs, many=True).data

    def get_new_tps(self, obj: ParsedSignal) -> list[dict]:
        qs = obj.take_profits.filter(is_edit_target=True).order_by("order")
        return TakeProfitSerializer(qs, many=True).data


# ─────────────────────────────────────────────────────────────────────────────
# 3.  ParseSignalInputSerializer  (write — triggers parsing)
# ─────────────────────────────────────────────────────────────────────────────

class ParseSignalInputSerializer(serializers.Serializer):
    """
    Accepts a reference to an existing WebhookMessage and triggers the
    full parser pipeline, persisting the results as ParsedSignal rows.

    Input fields
    ------------
    client_id   : ClientConfig.client_id
    message_id  : Telegram message ID string  (from WebhookMessage.message_id)

    Both fields together uniquely identify the WebhookMessage to parse
    (via the FK client__client_id + message_id lookup).

    Optional overrides
    ------------------
    force_reparse : bool (default False)
        When True, delete any existing ParsedSignal rows for this message
        before parsing.  Useful for re-processing after a config change.

    Output
    ------
    Call .save() after .is_valid().  Returns a list of ParsedSignal instances.
    """

    message_id    = serializers.CharField()
    client_id     = serializers.CharField()
    force_reparse = serializers.BooleanField(default=False, required=False)

    # Set by validate(); consumed by save()
    _message         = None
    _channel_config  = None

    def validate(self, attrs):
        client_id  = attrs["client_id"].strip()
        message_id = attrs["message_id"].strip()

        # ── Resolve ClientConfig ──────────────────────────────────────────────
        try:
            client_cfg = ClientConfig.objects.get(client_id=client_id)
        except ClientConfig.DoesNotExist:
            raise serializers.ValidationError(
                {
                    "client_id": (
                        f"ClientConfig '{client_id}' does not exist. "
                        "Create one before parsing."
                    )
                }
            )

        # ── Resolve WebhookMessage (FK lookup — no MultipleObjectsReturned) ───
        # client.models.WebhookMessage uses a FK to ClientConfig, so the
        # lookup is client__client_id + message_id which is always unique.
        try:
            message = WebhookMessage.objects.select_related("client").get(
                client__client_id=client_id,
                message_id=message_id,
            )
        except WebhookMessage.DoesNotExist:
            raise serializers.ValidationError(
                {
                    "message_id": (
                        f"No WebhookMessage found for client_id='{client_id}' "
                        f"and message_id='{message_id}'."
                    )
                }
            )
        except WebhookMessage.MultipleObjectsReturned:
            # Safety net: if duplicates somehow exist, use the latest one.
            message = (
                WebhookMessage.objects
                .select_related("client")
                .filter(client__client_id=client_id, message_id=message_id)
                .order_by("-received_at")
                .first()
            )

        # ── Resolve ChannelConfig ─────────────────────────────────────────────
        try:
            if message.channel_id:
                channel_config = client_cfg.configs.get(channel_id=message.channel_id)
            else:
                channel_config = client_cfg.configs.first()
                if not channel_config:
                    raise ChannelConfig.DoesNotExist()
        except ChannelConfig.DoesNotExist:
            raise serializers.ValidationError(
                {
                    "client_id": (
                        f"Client '{client_id}' has no ChannelConfig for channel '{message.channel_id}'. "
                        "Create one before parsing."
                    )
                }
            )

        # ── Guard: already parsed? ────────────────────────────────────────────
        if not attrs.get("force_reparse"):
            existing = message.parsed_signals.exists()
            if existing:
                raise serializers.ValidationError(
                    {
                        "message_id": (
                            "This message has already been parsed. "
                            "Pass force_reparse=true to re-parse."
                        )
                    }
                )

        self._message        = message
        self._channel_config = channel_config
        return attrs

    def save(self, **kwargs) -> list[ParsedSignal]:
        """
        Run the parser pipeline and persist results.

        Returns a list of ParsedSignal instances (may be empty if the
        message contains no actionable signal — e.g. pure text with no
        BUY/SELL keyword).

        Raises ValidationError if an 'open' signal produces no valid symbol.
        """
        message = self._message
        cfg     = self._channel_config

        # Delete previous results if force_reparse was requested
        if self.validated_data.get("force_reparse"):
            message.parsed_signals.all().delete()

        # ── Build parser inputs from ChannelConfig ────────────────────────────
        msg_items       = ChannelConfig.channel_config_to_msg_items(cfg)
        signal_keywords = _build_signal_keywords(cfg)

        raw_text    = message.text or ""
        replied_raw = message.replied_text or None

        # ── Pre-process: keyword substitution + delimiter removal ─────────────
        processed_text = preprocess_text(raw_text, msg_items)
        processed_replied = (
            preprocess_text(replied_raw, msg_items)
            if replied_raw
            else None
        )

        # ── Route and dispatch ────────────────────────────────────────────────
        results = route_signal(
            text            = processed_text,
            msg_id          = message.message_id,
            channel_id      = message.client.channel_id,
            channel_name    = message.client.client_id,
            msg_items       = msg_items,
            signal_keywords = signal_keywords,
            replied_text    = processed_replied,
        )

        # ── Validate: 'open' signals must have a resolved symbol ──────────────
        for res in results:
            if res["kind"] == "open":
                symbol = (res.get("symbol") or "").strip()
                if not symbol or symbol == "no_pair":
                    raise serializers.ValidationError(
                        {
                            "symbol": (
                                "Could not resolve a trading symbol from the message text. "
                                "Ensure the message contains a valid instrument symbol "
                                "(e.g. XAUUSD, EURUSD) before opening a trade."
                            )
                        }
                    )

        # ── Persist results ───────────────────────────────────────────────────
        self.parsed_signals = _persist_parsed_results(results, message)
        return self.parsed_signals