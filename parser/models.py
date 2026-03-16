from django.db import models


class WebhookMessage(models.Model):
	client_id = models.CharField(max_length=100, db_index=True)
	telegram_number = models.CharField(max_length=20, db_index=True)
	channel_id = models.CharField(max_length=100, db_index=True)
	broker_account_number = models.CharField(max_length=50, db_index=True)
	broker_server = models.CharField(max_length=100, db_index=True)

	message_id = models.CharField(max_length=255, db_index=True)
	text = models.TextField(blank=True)
	replied_message_id = models.CharField(max_length=255, blank=True)
	replied_text = models.TextField(blank=True)
	is_forwarded = models.BooleanField(default=False)
	is_edited = models.BooleanField(default=False)

	received_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		indexes = [
			models.Index(fields=["client_id", "message_id"]),
			models.Index(fields=["channel_id", "message_id"]),
			models.Index(fields=["received_at"]),
		]
		ordering = ["-received_at"]

	def __str__(self):
		return f"{self.client_id} - {self.message_id}"
