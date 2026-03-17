from rest_framework import serializers

from .models import ClientConfig, WebhookMessage


# ─────────────────────────────────────────────────────────────────────────────
# ClientConfigSerializer
# ─────────────────────────────────────────────────────────────────────────────

class ClientConfigSerializer(serializers.ModelSerializer):
    """
    CRUD serializer for ClientConfig.

    The ``config`` key is a *writable* nested representation of the
    client's ChannelConfig.  This means a single PATCH to
    /clients/{client_id}/ can update both the client identity fields
    AND the parser configuration in one request.

    On creation, a ChannelConfig with all defaults is automatically
    created even if ``config`` is not supplied.

    Example PATCH body (only send the fields you want to change):
    {
      "is_active": false,
      "config": {
        "kw_buy": "LONG",
        "prefer_entry": 2
      }
    }
    """

    # Lazy import inside property to avoid circular deps at module load time.
    # The actual field is injected dynamically below the class.
    configs = serializers.SerializerMethodField()

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
            "configs",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    # ── configs field: read via SerializerMethodField so it always renders ─────

    def get_configs(self, obj: ClientConfig):
        from parser.serializers import ChannelConfigSerializer
        
        cfg_qs = obj.configs.all()
        return ChannelConfigSerializer(cfg_qs, many=True).data

    # ── configs field: writable via to_internal_value override ────────────────

    def to_internal_value(self, data):
        """
        Allow ``configs`` to be passed as a writable list of dicts.
        """
        configs_data = data.pop("configs", None) if isinstance(data, dict) else None
        
        # fallback if they incorrectly sent a single dict as "configs" or "config"
        if not configs_data and isinstance(data, dict) and "config" in data:
            val = data.pop("config")
            if isinstance(val, dict):
                configs_data = [val]
            elif isinstance(val, list):
                configs_data = val

        if isinstance(data, dict) and hasattr(data, "dict"):
            data = data.dict()
        ret = super().to_internal_value(data)
        if configs_data is not None:
            ret["_configs_data"] = configs_data
        return ret

    def validate(self, attrs):
        # Normalize surrounding whitespace on string identity fields.
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

    # ── create ────────────────────────────────────────────────────────────────

    def create(self, validated_data):
        from parser.models import ChannelConfig
        from parser.serializers import ChannelConfigSerializer

        configs_data = validated_data.pop("_configs_data", None)
        instance = super().create(validated_data)

        # Apply any configs supplied at creation time
        if configs_data is not None and isinstance(configs_data, list):
            for config_data in configs_data:
                channel_id = config_data.get("channel_id", instance.channel_id)
                cfg, _ = ChannelConfig.objects.get_or_create(client=instance, channel_id=channel_id)
                cfg_ser = ChannelConfigSerializer(cfg, data=config_data, partial=True)
                if cfg_ser.is_valid(raise_exception=True):
                    cfg_ser.save()
        else:
            # Auto-create one default ChannelConfig
            ChannelConfig.objects.get_or_create(client=instance, channel_id=instance.channel_id)

        return instance

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, instance, validated_data):
        from parser.models import ChannelConfig
        from parser.serializers import ChannelConfigSerializer

        configs_data = validated_data.pop("_configs_data", None)

        # Update client identity fields
        instance = super().update(instance, validated_data)

        # Update ChannelConfigs if configs data was supplied
        if configs_data is not None and isinstance(configs_data, list):
            for config_data in configs_data:
                channel_id = config_data.get("channel_id", instance.channel_id)
                cfg, _ = ChannelConfig.objects.get_or_create(client=instance, channel_id=channel_id)
                cfg_ser = ChannelConfigSerializer(cfg, data=config_data, partial=True)
                if cfg_ser.is_valid(raise_exception=True):
                    cfg_ser.save()

        return instance


# ─────────────────────────────────────────────────────────────────────────────
# WebhookMessageSerializer  (used by WebhookReceiverView)
# ─────────────────────────────────────────────────────────────────────────────

class WebhookMessageSerializer(serializers.ModelSerializer):
    """
    Accepts incoming webhook payloads.

    The five identity fields are write-only: they look up the referenced
    ClientConfig and then the FK ``client`` carries that information on save.
    """

    client_id             = serializers.CharField(write_only=True)
    telegram_number       = serializers.CharField(write_only=True)
    channel_id            = serializers.CharField(write_only=True)
    broker_account_number = serializers.CharField(write_only=True)
    broker_server         = serializers.CharField(write_only=True)

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
        client_id             = attrs.pop("client_id", None)
        telegram_number       = attrs.pop("telegram_number", None)
        channel_id            = attrs.pop("channel_id", None)
        broker_account_number = attrs.pop("broker_account_number", None)
        broker_server         = attrs.pop("broker_server", None)

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
        
        channel_id_val = channel_id.strip() if channel_id else None
        if channel_id_val and not client.configs.filter(channel_id=channel_id_val).exists():
            raise serializers.ValidationError(
                {"channel_id": "channel_id does not match any config for this client."}
            )
            
        if (
            broker_account_number
            and client.broker_account_number != broker_account_number.strip()
        ):
            raise serializers.ValidationError(
                {"broker_account_number": "broker_account_number does not match client config."}
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
        if channel_id_val:
            attrs["channel_id"] = channel_id_val
        return attrs
