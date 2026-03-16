import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import action


from rest_framework import mixins, status, viewsets
from .serializers import *


logger = logging.getLogger(__name__)


# class WebhookReceiverView(APIView):
# 	authentication_classes = []
# 	permission_classes = []

# 	def post(self, request, *args, **kwargs):
# 		serializer = WebhookMessageSerializer(data=request.data)
# 		if not serializer.is_valid():
# 			logger.warning("Webhook payload validation failed errors=%s", serializer.errors)
# 			return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# 		instance = serializer.save()
# 		logger.info(
# 			"Webhook payload stored client_id=%s message_id=%s",
# 			instance.client_id,
# 			instance.message_id,
# 		)
# 		return Response(
# 			{
# 				"detail": "Webhook payload received.",
# 				"id": instance.id,
# 			},
# 			status=status.HTTP_201_CREATED,
# 		)


# ─────────────────────────────────────────────────────────────────────────────
# ChannelConfig CRUD  (OneToOne on ClientConfig, looked up by client_id)
# ─────────────────────────────────────────────────────────────────────────────
 
class ChannelConfigViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Create / read / update the keyword + behaviour config for one client.
 
    All routes are scoped by client_id:
        POST   /clients/{client_id}/config/      → create
        GET    /clients/{client_id}/config/      → retrieve
        PUT    /clients/{client_id}/config/      → full update
        PATCH  /clients/{client_id}/config/      → partial update
    """
 
    serializer_class = ChannelConfigSerializer
    lookup_field     = "client__client_id"
 
    def get_queryset(self):
        return ChannelConfig.objects.select_related("client").all()
 
    def get_object(self):
        client_id = self.kwargs.get("client_id") or self.kwargs.get(self.lookup_field)
        try:
            return ChannelConfig.objects.select_related("client").get(
                client__client_id=client_id
            )
        except ChannelConfig.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound(
                detail=f"No ChannelConfig found for client_id='{client_id}'."
            )
 
    def perform_create(self, serializer):
        from .models import ClientConfig
        client_id = self.kwargs.get("client_id")
        try:
            client = ClientConfig.objects.get(client_id=client_id)
        except ClientConfig.DoesNotExist:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"client_id": f"ClientConfig '{client_id}' does not exist."}
            )
        serializer.save(client=client)
        logger.info("ChannelConfig created client_id=%s", client_id)
 
    def perform_update(self, serializer):
        serializer.save()
        logger.info(
            "ChannelConfig updated client_id=%s",
            self.kwargs.get("client_id"),
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Parser ViewSet
# ─────────────────────────────────────────────────────────────────────────────
 
class ParserViewSet(viewsets.GenericViewSet):
    """
    Signal parsing endpoints.
 
    POST  /parse/               → parse a WebhookMessage, persist results
    GET   /parse/signals/       → list all ParsedSignal records
    GET   /parse/signals/{id}/  → retrieve one ParsedSignal record
    PATCH /parse/signals/{id}/  → update status / blocked_by_news_filter
    GET   /parse/signals/{id}/tps/  → list TPs for one signal
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
            .select_related("message__client")
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
 
    # ── POST /parse/ ──────────────────────────────────────────────────────────
 
    @action(detail=False, methods=["post"], url_path="parse")
    def parse(self, request):
        """
        Trigger the parser pipeline for one WebhookMessage.
 
        Request body
        ------------
        {
            "client_id":    "CLIENT_ABC",
            "message_id":   "101",
            "force_reparse": false        // optional, default false
        }
 
        Response  201
        ------------
        List of ParsedSignal records created (may be empty if the message
        contained no actionable signal).
 
        Response  400
        ------------
        Validation errors — message not found, no ChannelConfig, already
        parsed (unless force_reparse=true).
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
 
    # ── GET /parse/signals/ ───────────────────────────────────────────────────
 
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
 
        client_id = request.query_params.get("client_id")
        symbol    = request.query_params.get("symbol")
        kind      = request.query_params.get("kind")
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
 
    # ── GET /parse/signals/{id}/ ──────────────────────────────────────────────
 
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
 
    # ── PATCH /parse/signals/{id}/ ────────────────────────────────────────────
 
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
 
    # ── GET /parse/signals/{id}/tps/ ─────────────────────────────────────────
 
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