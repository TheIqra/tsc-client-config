import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import mixins, viewsets

from .serializers import (
    ParsedSignalSerializer,
    ParseSignalInputSerializer,
    TakeProfitSerializer,
)
from .models import ParsedSignal


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Parser ViewSet
# ─────────────────────────────────────────────────────────────────────────────

class ParserViewSet(viewsets.GenericViewSet):
    """
    Signal parsing endpoints.

    POST  /parser/parse/                         → parse a WebhookMessage
    GET   /parser/signals/                       → list all ParsedSignal records
    GET   /parser/signals/{id}/                  → retrieve one record
    PATCH /parser/signals/{id}/update/           → update status / news filter flag
    GET   /parser/signals/{id}/tps/              → list TPs for one signal

    ChannelConfig CRUD is handled under /clients/{client_id}/config/ in the
    client app (nested resource, auto-created with defaults on client creation).
    """

    # Default serializer — overridden per action below
    serializer_class = ParsedSignalSerializer

    def get_queryset(self):
        """
        Base queryset used by all signal-reading actions.
        Prefetch related data in one query to avoid N+1 on take_profits.
        """
        return (
            ParsedSignal.objects
            .select_related("message", "message__client")
            .prefetch_related("take_profits")
            .order_by("-parsed_at")
        )

    def get_serializer_class(self):
        if self.action == "parse":
            return ParseSignalInputSerializer
        if self.action in ("signals", "retrieve_signal", "update_signal"):
            return ParsedSignalSerializer
        if self.action == "tps":
            return TakeProfitSerializer
        return ParsedSignalSerializer

    # ── POST /parser/parse/ ───────────────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="parse")
    def parse(self, request):
        """
        Trigger the parser pipeline for one WebhookMessage.

        Request body
        ------------
        {
            "client_id":    "1008",
            "message_id":   "2004",
            "force_reparse": false        // optional, default false
        }

        Response  201
        ------------
        List of ParsedSignal records created.  May be empty when the message
        contained no actionable signal (pure text, no BUY/SELL keyword).

        Response  400
        ------------
        Validation errors — message not found, no ChannelConfig, already
        parsed (unless force_reparse=true), or unresolvable symbol for an
        open signal.
        """
        inp = ParseSignalInputSerializer(data=request.data)
        if not inp.is_valid():
            logger.warning("Parse request validation failed errors=%s", inp.errors)
            return Response(inp.errors, status=status.HTTP_400_BAD_REQUEST)

        signals = inp.save()

        logger.info(
            "Parsed message client_id=%s message_id=%s signals_created=%d",
            request.data.get("client_id"),
            request.data.get("message_id"),
            len(signals),
        )

        out = ParsedSignalSerializer(signals, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)

    # ── GET /parser/signals/ ──────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="signals")
    def signals(self, request):
        """
        List all ParsedSignal records, newest first.

        Query params (all optional)
        ---------------------------
        client_id   – filter by client
        symbol      – filter by instrument (e.g. XAUUSD)
        kind        – filter by command kind (open | close | update | …)
        status      – filter by status (PENDING | OPEN | CLOSED | …)
        """
        qs = self.get_queryset()

        client_id  = request.query_params.get("client_id")
        symbol     = request.query_params.get("symbol")
        kind       = request.query_params.get("kind")
        sig_status = request.query_params.get("status")

        if client_id:
            qs = qs.filter(message__client__client_id=client_id)
        if symbol:
            qs = qs.filter(symbol__iexact=symbol)
        if kind:
            qs = qs.filter(kind=kind)
        if sig_status:
            qs = qs.filter(status=sig_status)

        serializer = ParsedSignalSerializer(qs, many=True)
        return Response(serializer.data)

    # ── GET /parser/signals/{id}/ ─────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="signals/(?P<signal_id>[^/.]+)")
    def retrieve_signal(self, request, signal_id=None, **kwargs):
        """Retrieve a single ParsedSignal by its database ID."""
        try:
            signal = self.get_queryset().get(pk=signal_id)
        except ParsedSignal.DoesNotExist:
            return Response(
                {"detail": f"ParsedSignal {signal_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ParsedSignalSerializer(signal)
        return Response(serializer.data)

    # ── PATCH /parser/signals/{id}/update/ ───────────────────────────────────

    @action(detail=True, methods=["patch"], url_path="signals/(?P<signal_id>[^/.]+)/update")
    def update_signal(self, request, signal_id=None, **kwargs):
        """
        Partially update a ParsedSignal.

        Only ``status`` and ``blocked_by_news_filter`` are writable via
        this endpoint — all parser-output fields are immutable after creation.

        Request body (all optional)
        ---------------------------
        { "status": "OPEN", "blocked_by_news_filter": false }
        """
        try:
            signal = self.get_queryset().get(pk=signal_id)
        except ParsedSignal.DoesNotExist:
            return Response(
                {"detail": f"ParsedSignal {signal_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        allowed = {"status", "blocked_by_news_filter"}
        payload = {k: v for k, v in request.data.items() if k in allowed}

        if not payload:
            return Response(
                {"detail": f"Only these fields are updatable: {sorted(allowed)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for field, value in payload.items():
            setattr(signal, field, value)

        try:
            signal.full_clean()
            signal.save(update_fields=list(payload.keys()))
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            "ParsedSignal updated id=%s fields=%s",
            signal_id,
            list(payload.keys()),
        )
        return Response(ParsedSignalSerializer(signal).data)

    # ── GET /parser/signals/{id}/tps/ ────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="signals/(?P<signal_id>[^/.]+)/tps")
    def tps(self, request, signal_id=None, **kwargs):
        """
        List all TakeProfit rows for one ParsedSignal.

        Query params
        ------------
        edit  – "true"  → only edit-target TPs (from update commands)
                "false" → only original TPs (from the open signal)
                omitted → all TPs
        """
        try:
            signal = self.get_queryset().get(pk=signal_id)
        except ParsedSignal.DoesNotExist:
            return Response(
                {"detail": f"ParsedSignal {signal_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = signal.take_profits.order_by("order")
        edit_param = request.query_params.get("edit")
        if edit_param == "true":
            qs = qs.filter(is_edit_target=True)
        elif edit_param == "false":
            qs = qs.filter(is_edit_target=False)

        serializer = TakeProfitSerializer(qs, many=True)
        return Response(serializer.data)