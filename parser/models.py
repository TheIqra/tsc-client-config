from django.db import models

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

# WebhookMessage is canonical in client.models; import it here for FK references
from client.models import ClientConfig, WebhookMessage  # noqa: F401



"""

Design decisions
----------------
*  ClientConfig   → already holds client identity + channel + broker account.
   We attach ChannelConfig (keyword settings) to it via OneToOne.

*  WebhookMessage → already holds the raw Telegram message.
   ParsedSignal FK-s into it to record what the parser extracted.

*  TakeProfit     → child of ParsedSignal.  Fully dynamic (no tp1…tp5 columns).
   Count cap lives in SystemSettings.max_tp_count (0 = unlimited).

Total new tables : 4
  1. SystemSettings   (singleton – admin controls TP cap)
  2. ChannelConfig    (OneToOne → ClientConfig, all keyword/behaviour settings)
  3. ParsedSignal     (FK → WebhookMessage, parser output)
  4. TakeProfit       (FK → ParsedSignal, one row per TP level)
"""



# ===========================================================================
# 1.  SYSTEM SETTINGS  –  singleton, admin controls global TP cap
# ===========================================================================
 
class SystemSettings(models.Model):
    """
    One row (pk = 1) only.  Superuser changes this in Django Admin.
 
    max_tp_count
        0   → unlimited
        5   → original TSC default
        10  → raised cap (zero migration needed to change at runtime)
    """
 
    max_tp_count = models.PositiveIntegerField(
        default=5,
        help_text=_("Max TPs per signal. 0 = unlimited."),
    )
 
    class Meta:
        verbose_name        = _("System Settings")
        verbose_name_plural = _("System Settings")
 
    def __str__(self):
        cap = self.max_tp_count or "unlimited"
        return f"System Settings — max TPs per signal: {cap}"
 
    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
 
    def delete(self, *args, **kwargs):
        pass  # prevent deletion
 
    @classmethod
    def get(cls) -> "SystemSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
 
 
# ===========================================================================
# 2.  CHANNEL CONFIG  –  keyword + behaviour settings per client
#     OneToOne → ClientConfig  (shares the same primary key)
# ===========================================================================
 
class ChannelConfig(models.Model):
    """
    Full keyword + behaviour configuration for one client's channel.
    Mirrors all three Config-Keyword tabs in the TSC desktop UI.
    """
 
    client = models.ForeignKey(
        ClientConfig,
        on_delete=models.CASCADE,
        related_name="configs",
    )
    
    channel_id = models.CharField(
        max_length=100, 
        blank=True, 
        default="",
        db_index=True,
        verbose_name=_("Channel ID"),
        help_text=_("Telegram channel ID for this configuration.")
    )
 
    # ── Tab 1 · Signal Keywords ─────────────────────────────────────────────
 
    kw_entry_point  = models.CharField(max_length=200, blank=True, default="ENTRY",
        verbose_name=_("Entry Point"),
        help_text=_("Word provider uses for entry price. Default: ENTRY."))
    kw_buy          = models.CharField(max_length=200, blank=True, default="LONG",
        verbose_name=_("BUY aliases"),
        help_text=_("Comma-separated aliases (e.g. LONG,B)."))
    kw_sell         = models.CharField(max_length=200, blank=True, default="SHORT",
        verbose_name=_("SELL aliases"),
        help_text=_("Comma-separated aliases (e.g. SHORT,S)."))
    kw_sl           = models.CharField(max_length=200, blank=True, default="SL",
        verbose_name=_("SL aliases"),
        help_text=_("Comma-separated aliases (e.g. STOP,STOP-LOSS)."))
    kw_tp           = models.CharField(max_length=200, blank=True, default="TP",
        verbose_name=_("TP aliases"),
        help_text=_("Comma-separated aliases (e.g. TARGET,PROFIT)."))
    kw_market_order = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Market Order keyword"),
        help_text=_("Forces market execution even when a limit price is given."))
    use_ai          = models.BooleanField(default=False,
        verbose_name=_("AI parsing"),
        help_text=_("GPT-based signal parsing (requires AI subscription)."))
    read_image      = models.BooleanField(default=False,
        verbose_name=_("Read images"),
        help_text=_("OCR extraction from image messages (requires subscription)."))
 
    # ── Tab 2 · Update Keywords ──────────────────────────────────────────────
 
    kw_close_tp1      = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close TP1"))
    kw_close_tp2      = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close TP2"))
    kw_close_tp3      = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close TP3"))
    kw_close_tp4      = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close TP4"))
    kw_close_full     = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close Full"),
        help_text=_("Reply keyword to close the entire position."))
    kw_close_half     = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close Half"))
    kw_close_partial  = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close Partial"))
    kw_breakeven      = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Break Even"),
        help_text=_("Move SL to entry price."))
    kw_set_tp1        = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set TP1"))
    kw_set_tp2        = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set TP2"))
    kw_set_tp3        = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set TP3"))
    kw_set_tp4        = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set TP4"))
    kw_set_tp5        = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set TP5"))
    kw_set_all_tp     = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set All TPs"))
    kw_set_sl         = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Set SL"))
    kw_delete_pending = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Delete pending order"))
 
    # ── Tab 3 · Additional Keywords ─────────────────────────────────────────
 
    kw_layer      = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Layer / re-entry"))
    kw_close_all  = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Close All"))
    kw_delete_all = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Delete All"))
    kw_ignore     = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Ignore keyword"),
        help_text=_("Messages containing this word are ignored entirely."))
    kw_skip       = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Skip keyword"),
        help_text=_("Text between skip markers is stripped before parsing."))
    kw_remove_sl  = models.CharField(max_length=200, blank=True, default="",
        verbose_name=_("Remove SL"))
 
    # ── Behaviour options ────────────────────────────────────────────────────
 
    delay_ms = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Delay (ms)"),
        help_text=_("Milliseconds to wait before dispatching the signal."),
    )
 
    class PreferEntry(models.IntegerChoices):
        FIRST   = 0, _("First Price")
        SECOND  = 1, _("Second Price")
        AVERAGE = 2, _("Average Price")
        ALL     = 3, _("ALL Price — one signal per entry in range")
 
    prefer_entry   = models.IntegerField(
        choices=PreferEntry.choices,
        default=PreferEntry.AVERAGE,   # default = 2 (average of range)
        verbose_name=_("Prefer Entry"),
        help_text=_("Which price to use when a range is given (e.g. 2330/2335)."),
    )
    sl_in_pips     = models.BooleanField(default=False, verbose_name=_("SL in Pips"))
    tp_in_pips     = models.BooleanField(default=False, verbose_name=_("TP in Pips"))
    delimiters     = models.CharField(
        max_length=10, blank=True, default="",
        verbose_name=_("Delimiters"),
        help_text=_("Two-char pair; enclosed text stripped before parsing (e.g. '[]')."),
    )
    all_order      = models.BooleanField(
        default=False,
        verbose_name=_("ALL Order"),
        help_text=_("Execute both market AND pending orders."),
    )
    read_forwarded = models.BooleanField(
        default=True,
        verbose_name=_("Read Forwarded"),
        help_text=_("False → ignore forwarded Telegram messages."),
    )
    news_filter    = models.BooleanField(
        default=False,
        verbose_name=_("News Filter"),
        help_text=_("Block new signals during high-impact news windows."),
    )
 
    class Meta:
        verbose_name        = _("Channel Config")
        verbose_name_plural = _("Channel Configs")
        unique_together     = (("client", "channel_id"),)
 
    def __str__(self):
        return f"Config {self.channel_id} → {self.client}"
    
    @staticmethod                                   # ← Fix 1: was missing, cfg != self
    def channel_config_to_msg_items(cfg: "ChannelConfig") -> list[tuple]:
        """
        Convert a ChannelConfig instance into the msg_items list that
        preprocess_text() and route_signal() expect.

        Index layout (only the indices the parser actually reads matter):
        0-4   → signal keyword substitutions  (preprocess_text og_text_indices)
        22-26 → reply keyword substitutions   (preprocess_text og_text_indices)  ← Fix 2
        29-37 → routing flags                 (route_signal)
        5-21, 27-28 → unused padding
        """
        return [
            (" BUY",         cfg.kw_buy),           # 0  signal keyword
            (" SELL",        cfg.kw_sell),           # 1  signal keyword
            (" SELL",        ""),                    # 2  placeholder
            ("SL",           cfg.kw_sl),             # 3  signal keyword
            ("TP",           cfg.kw_tp),             # 4  signal keyword
            *[("", "")] * 17,                        # 5-21  unused (never read)
            ("TP1 HIT",      cfg.kw_close_tp1),      # 22  reply keyword ← now readable
            ("TP2 HIT",      cfg.kw_close_tp2),      # 23  reply keyword
            ("TP3 HIT",      cfg.kw_close_tp3),      # 24  reply keyword
            ("TP4 HIT",      cfg.kw_close_tp4),      # 25  reply keyword
            ("CLFL",         cfg.kw_close_full),     # 26  reply keyword
            *[("", "")] * 2,                         # 27-28  unused
            ("PREFERENTRY",  str(cfg.prefer_entry)), # 29
            ("SLINPIPS",     cfg.sl_in_pips),        # 30
            ("TPINPIPS",     cfg.tp_in_pips),        # 31
            ("READIMAGE",    cfg.read_image),        # 32
            ("DELIMITERS",   cfg.delimiters),        # 33
            ("ALLORDER",     cfg.all_order),         # 34
            ("AI",           cfg.use_ai),            # 35
            ("READFORWARDED",cfg.read_forwarded),    # 36
            ("NEWSFILTER",   cfg.news_filter),       # 37
        ]
 
 
# ===========================================================================
# 3.  PARSED SIGNAL  –  result of route_signal() for one WebhookMessage
# ===========================================================================
 
class ParsedSignal(models.Model):
    """
    One parsed trade action produced from a WebhookMessage.
 
    ``command_text`` holds the exact command string sent to MT4/MT5:
        /open  USDJPY,SELL,1.54,0,1111,3333,4444,6666,-1,4,3810826194,copier
        /open  USDJPY,SELL,,0,1111,3333,4444,6666,-1,5,3810826194,copier
        /close USDJPY,5,TP1
 
    TPs are stored in child ``TakeProfit`` rows — no tp1/tp2/… columns.
    """
 
    class Direction(models.TextChoices):
        BUY  = "BUY",  _("Buy")
        SELL = "SELL", _("Sell")
 
    class Kind(models.TextChoices):
        OPEN             = "open",           _("Open")
        EDIT             = "edit",           _("Edit")
        CLOSE            = "close",          _("Close")
        CLOSE_ALL        = "closeall",       _("Close All")
        DELETE_ALL       = "deleteall",      _("Delete All")
        CLOSE_HALF       = "closehalf",      _("Close Half")
        CLOSE_HALF_BE    = "closehalfbe",    _("Close Half + BE")
        CLOSE_PARTIAL    = "closepartial",   _("Close Partial")
        CLOSE_PARTIAL_BE = "closepartialbe", _("Close Partial + BE")
        UPDATE           = "update",         _("Update SL/TP")
        BREAKEVEN        = "breakeven",      _("Breakeven")
        DELETE           = "delete",         _("Delete Pending")
 
    class Status(models.TextChoices):
        PENDING   = "PENDING",   _("Pending")
        OPEN      = "OPEN",      _("Open")
        CLOSED    = "CLOSED",    _("Closed")
        CANCELLED = "CANCELLED", _("Cancelled")
        ERROR     = "ERROR",     _("Parse Error")
 
    # ── relations ─────────────────────────────────────────────────────────────
    message = models.ForeignKey(
        WebhookMessage,
        on_delete=models.CASCADE,
        related_name="parsed_signals",
        help_text=_("Source webhook message."),
    )
 
    # ── parser output (mirrors route_signal result dict keys) ─────────────────
    kind        = models.CharField(max_length=20, choices=Kind.choices,
                    default=Kind.OPEN, db_index=True)
    symbol      = models.CharField(max_length=32, blank=True, default="",
                    help_text=_("Instrument symbol (e.g. XAUUSD, USDJPY)."))
    direction   = models.CharField(max_length=4,  blank=True, default="",
                    choices=Direction.choices,
                    help_text=_("BUY or SELL. Blank for non-open kinds."))
    entry_price = models.CharField(max_length=32, blank=True, default="",
                    help_text=_("Entry price string. Empty = market order."))
    sl          = models.CharField(max_length=32, blank=True, default="0",
                    verbose_name=_("Stop-Loss"),
                    help_text=_("'0' = no SL. May carry ' pips' suffix."))
 
    # For update/edit kinds: the new SL/TP values requested
    new_sl  = models.CharField(max_length=32, blank=True, default="",
                help_text=_("New SL requested by update/edit. Empty if unchanged."))
 
    # Which TP label was hit/closed (e.g. 'TP1', 'TP2')
    close_tp = models.CharField(max_length=8, blank=True, default="",
                 help_text=_("TP label targeted by a close command (e.g. TP1)."))
 
    # Full command string exactly as sent to MT4/MT5
    command_text = models.TextField(
        blank=True, default="",
        help_text=_("Full command string  e.g. /open USDJPY,SELL,1.54,0,1111,…"),
    )
 
    # ── state ─────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    blocked_by_news_filter = models.BooleanField(
        default=False,
        help_text=_("True → suppressed by news-window filter; command not dispatched."),
    )
 
    parsed_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-parsed_at"]
        verbose_name        = _("Parsed Signal")
        verbose_name_plural = _("Parsed Signals")
        indexes = [
            models.Index(fields=["symbol", "direction"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["parsed_at"]),
        ]
 
    def __str__(self):
        loc = self.entry_price or "MARKET"
        return f"[{self.kind.upper()}] {self.symbol} {self.direction} @ {loc}"
 
    # ── TP management ─────────────────────────────────────────────────────────
 
    def add_tp(self, value: str, order: int | None = None) -> "TakeProfit":
        """
        Append a TP row, honouring the global SystemSettings.max_tp_count cap.
 
        Parameters
        ----------
        value : price string or '<N> pips'
        order : 1-based index; auto-incremented if None.
 
        Raises
        ------
        ValidationError when the cap is exceeded.
        """
        cap   = SystemSettings.get().max_tp_count
        count = self.take_profits.count()
 
        if cap and count >= cap:
            raise ValidationError(
                _(
                    f"TP cap ({cap}) reached for signal #{self.pk}. "
                    "Raise SystemSettings.max_tp_count or set to 0 for unlimited."
                )
            )
 
        if order is None:
            last  = self.take_profits.order_by("-order").first()
            order = (last.order + 1) if last else 1
 
        return TakeProfit.objects.create(signal=self, order=order, value=value)
 
    def get_tp_list(self) -> list[str]:
        """Return TP values in ascending order as plain strings."""
        return list(
            self.take_profits.order_by("order").values_list("value", flat=True)
        )
 
    def to_json(self) -> dict:
        """
        Return a JSON-serialisable dict that mirrors the route_signal()
        result schema exactly.  Suitable for API responses.
 
        Example output
        --------------
        {
          "kind":        "open",
          "command":     "/open USDJPY,SELL,1.54,0,1111,3333,4444,6666,4,3810826194,copier",
          "symbol":      "USDJPY",
          "direction":   "SELL",
          "entry_price": "1.54",
          "sl":          "0",
          "tps":         ["1111", "3333", "4444", "6666"],
          "msg_id":      "4",
          "channel_id":  "3810826194",
          "channel":     "copier",
          "close_tp":    "",
          "new_sl":      "",
          "new_tps":     [],
          "status":      "OPEN",
          "blocked_by_news_filter": false,
          "parsed_at":   "2026-03-11T15:12:10Z"
        }
        """
        return {
            "kind":                    self.kind,
            "command":                 self.command_text,
            "symbol":                  self.symbol,
            "direction":               self.direction,
            "entry_price":             self.entry_price,
            "sl":                      self.sl,
            "tps":                     self.get_tp_list(),
            "msg_id":                  self.message.message_id,
            "channel_id":              self.message.client.channel_id,
            "channel":                 self.message.client.client_id,
            "close_tp":                self.close_tp,
            "new_sl":                  self.new_sl,
            "new_tps":                 [tp.value for tp in
                                        self.take_profits.filter(is_edit_target=True)
                                        .order_by("order")],
            "status":                  self.status,
            "blocked_by_news_filter":  self.blocked_by_news_filter,
            "parsed_at":               self.parsed_at.isoformat() if self.parsed_at else None,
        }
 
 
# ===========================================================================
# 4.  TAKE PROFIT  –  dynamic TP rows, child of ParsedSignal
# ===========================================================================
 
class TakeProfit(models.Model):
    """
    One TP level belonging to a ParsedSignal.
 
    ``order`` is 1-based:  TP1 → order=1,  TP2 → order=2, …
 
    No hard DB-level cap — cap is enforced by ParsedSignal.add_tp() reading
    SystemSettings.max_tp_count.  Change the cap at runtime: zero migration.
 
    ``is_edit_target``
        False (default) → original TP from the open signal
        True            → new TP value set by an update/edit command
    """
 
    signal = models.ForeignKey(
        ParsedSignal,
        on_delete=models.CASCADE,
        related_name="take_profits",
    )
    order = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
        help_text=_("TP sequence number (1-based)."),
    )
    value = models.CharField(
        max_length=32,
        help_text=_("Price level or '<N> pips'. '-1' = not set / unchanged."),
    )
    hit_at = models.DateTimeField(
        null=True, blank=True,
        help_text=_("When this TP was hit and the position partially closed."),
    )
    is_edit_target = models.BooleanField(
        default=False,
        help_text=_("True → this TP was set/changed by an update command, "
                    "not from the original open signal."),
    )
 
    class Meta:
        unique_together     = [("signal", "order", "is_edit_target")]
        ordering            = ["signal", "order"]
        verbose_name        = _("Take Profit")
        verbose_name_plural = _("Take Profits")
 
    def __str__(self):
        tag = " [edit]" if self.is_edit_target else ""
        return f"TP{self.order}{tag} = {self.value}  (signal #{self.signal_id})"
 
    @property
    def label(self) -> str:
        return f"TP{self.order}"