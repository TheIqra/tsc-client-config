from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(ClientConfig)
admin.site.register(WebhookMessage)

admin.site.site_header = "Client Config Admin"
admin.site.site_title = "Client Config Admin Portal"