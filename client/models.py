from django.db import models


class ClientConfig(models.Model):
	client_id = models.CharField(max_length=100, unique=True)
	telegram_number = models.CharField(max_length=20, db_index=True)
	channel_id = models.CharField(max_length=100, db_index=True)
	broker_account_number = models.CharField(max_length=50, db_index=True)
	broker_server = models.CharField(max_length=100, db_index=True)
	is_active = models.BooleanField(default=True)
	
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		indexes = [
			models.Index(fields=["client_id"]),
			models.Index(fields=["telegram_number"]),
			models.Index(fields=["channel_id"]),
			models.Index(fields=["broker_account_number", "broker_server"]),
			models.Index(fields=["is_active"]),
		]
		ordering = ["client_id"]

	def __str__(self):
		return f"{self.client_id} ({self.telegram_number})"

class WebhookMessage(models.Model):
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE, related_name='webhook_messages')

    message_id = models.CharField(max_length=255, db_index=True)
    text = models.TextField(blank=True)
    replied_message_id = models.CharField(max_length=255, blank=True)
    replied_text = models.TextField(blank=True)
    is_forwarded = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)

    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["client", "message_id"]),
            models.Index(fields=["client", "received_at"]),
        ]
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.client.client_id} - {self.message_id}"