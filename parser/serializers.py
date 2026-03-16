from rest_framework import serializers

from .models import WebhookMessage


class WebhookMessageSerializer(serializers.ModelSerializer):
	class Meta:
		model = WebhookMessage
		fields = [
			"id",
			"client_id",
			"telegram_number",
			"channel_id",
			"broker_account_number",
			"broker_server",
			"message_id",
			"text",
			"replied_message_id",
			"replied_text",
			"is_forwarded",
			"is_edited",
			"received_at",
		]
		read_only_fields = ["id", "received_at"]

	def validate(self, attrs):
		for field in [
			"client_id",
			"telegram_number",
			"channel_id",
			"broker_account_number",
			"broker_server",
			"message_id",
			"text",
			"replied_message_id",
			"replied_text",
		]:
			value = attrs.get(field)
			if isinstance(value, str):
				attrs[field] = value.strip()
		return attrs
