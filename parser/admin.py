from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(ChannelConfig)
admin.site.register(SystemSettings)
admin.site.register(ParsedSignal)
admin.site.register(TakeProfit)
