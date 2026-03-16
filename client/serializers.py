from rest_framework import serializers

from .models import ClientConfig, WebhookMessage


class ClientConfigSerializer(serializers.ModelSerializer):
	class Meta:
		model = ClientConfig
		fields = [
			"id",
			"client_id",
			"telegram_number",
			"channel_id",
			"broker_account_number",
			"broker_server",
			"is_active",
			"created_at",
			"updated_at",
		]
		read_only_fields = ["id", "created_at", "updated_at"]

	def validate(self, attrs):
		# Normalize surrounding whitespace on string inputs before save.
		for field in [
			"client_id",
			"telegram_number",
			"channel_id",
			"broker_account_number",
			"broker_server",
		]:
			value = attrs.get(field)
			if isinstance(value, str):
				attrs[field] = value.strip()
		return attrs


class WebhookMessageSerializer(serializers.ModelSerializer):
	client_id = serializers.CharField(write_only=True)
	telegram_number = serializers.CharField(write_only=True)
	channel_id = serializers.CharField(write_only=True)
	broker_account_number = serializers.CharField(write_only=True)
	broker_server = serializers.CharField(write_only=True)

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
		client_id = attrs.pop("client_id", None)
		telegram_number = attrs.pop("telegram_number", None)
		channel_id = attrs.pop("channel_id", None)
		broker_account_number = attrs.pop("broker_account_number", None)
		broker_server = attrs.pop("broker_server", None)

		if not client_id:
			raise serializers.ValidationError({"client_id": "This field is required."})

		try:
			client = ClientConfig.objects.get(client_id=client_id, is_active=True)
		except ClientConfig.DoesNotExist:
			raise serializers.ValidationError(
				{"client_id": "Active client config not found for this client_id."}
			)

		if telegram_number and client.telegram_number != telegram_number.strip():
			raise serializers.ValidationError(
				{"telegram_number": "telegram_number does not match client config."}
			)
		if channel_id and client.channel_id != channel_id.strip():
			raise serializers.ValidationError(
				{"channel_id": "channel_id does not match client config."}
			)
		if (
			broker_account_number
			and client.broker_account_number != broker_account_number.strip()
		):
			raise serializers.ValidationError(
				{
					"broker_account_number": (
						"broker_account_number does not match client config."
					)
				}
			)
		if broker_server and client.broker_server != broker_server.strip():
			raise serializers.ValidationError(
				{"broker_server": "broker_server does not match client config."}
			)

		for field in ["message_id", "text", "replied_message_id", "replied_text"]:
			value = attrs.get(field)
			if isinstance(value, str):
				attrs[field] = value.strip()

		attrs["client"] = client
		return attrs
