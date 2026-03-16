from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ParserViewSet

router = DefaultRouter()
router.register("parser", ParserViewSet, basename="parser")

urlpatterns = [
    path("", include(router.urls)),
]
