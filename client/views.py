import logging

from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ClientConfig
from .serializers import ClientConfigSerializer, WebhookMessageSerializer


logger = logging.getLogger(__name__)


class ClientConfigViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Full CRUD for ClientConfig.

    Every response includes a nested ``config`` object with the client's
    ChannelConfig (auto-created with defaults on first client creation).

    The ``config`` key is also *writable* on PATCH/PUT — you can update
    client identity fields and parser configuration in a single request.

    Endpoints
    ---------
    GET    /clients/          → list all clients (with nested config)
    POST   /clients/          → create client   (config auto-created with defaults)
    GET    /clients/{id}/     → retrieve one    (with nested config)
    PUT    /clients/{id}/     → full update     (client + optional config)
    PATCH  /clients/{id}/     → partial update  (client fields and/or config fields)
    DELETE /clients/{id}/     → delete client   (cascades to config)
    """

    queryset         = ClientConfig.objects.all().order_by("client_id")
    serializer_class = ClientConfigSerializer
    lookup_field     = "client_id"


class WebhookReceiverView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        serializer = WebhookMessageSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Webhook payload validation failed errors=%s", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        instance = serializer.save()
        logger.info(
            "Client webhook stored client_id=%s message_id=%s",
            instance.client.client_id,
            instance.message_id,
        )
        return Response(
            {
                "detail": "Webhook payload received.",
                "id": instance.id,
            },
            status=status.HTTP_201_CREATED,
        )
