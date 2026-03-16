from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()

router.register("parser", ParserViewSet, basename="parser")

urlpatterns = [
    path("", include(router.urls)),
    path("clients/<client_id>/config/",ChannelConfigViewSet.as_view({
        "get":   "retrieve",
        "post":  "create",
        "put":   "update",
        "patch": "partial_update",
    }), name="channel-config"),
    # path("webhook/receiver/", WebhookReceiverView.as_view(), name="webhook-receiver"),
]
