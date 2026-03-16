from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ClientConfigViewSet, WebhookReceiverView


router = DefaultRouter()
router.register(r"clients", ClientConfigViewSet, basename="client-config")

urlpatterns = [
	path("", include(router.urls)),
	path("webhook/receiver/", WebhookReceiverView.as_view(), name="client-webhook-receiver"),
]