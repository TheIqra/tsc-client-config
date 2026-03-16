import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import WebhookMessageSerializer


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
