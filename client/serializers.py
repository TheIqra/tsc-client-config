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
    config = serializers.SerializerMethodField()

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
            "config",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    # ── config field: read via SerializerMethodField so it always renders ─────

    def get_config(self, obj: ClientConfig):
        from parser.serializers import ChannelConfigSerializer
        from parser.models import ChannelConfig

        cfg, _ = ChannelConfig.objects.get_or_create(client=obj)
        return ChannelConfigSerializer(cfg).data

    # ── config field: writable via to_internal_value override ────────────────

    def to_internal_value(self, data):
        """
        Allow ``config`` to be passed as a writable dict.
        We pop it out before the standard field validation (which treats it
        as read-only via SerializerMethodField) and stash it for use in
        update()/create().
        """
        config_data = data.pop("config", None) if isinstance(data, dict) else None
        # data may be a QueryDict (immutable) — work on a plain dict copy
        if hasattr(data, "dict"):
            data = data.dict()
        ret = super().to_internal_value(data)
        if config_data is not None:
            ret["_config_data"] = config_data
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

        config_data = validated_data.pop("_config_data", None)
        instance = super().create(validated_data)

        # Auto-create ChannelConfig (with defaults)
        cfg, _ = ChannelConfig.objects.get_or_create(client=instance)

        # Apply any config fields supplied at creation time
        if config_data:
            cfg_ser = ChannelConfigSerializer(cfg, data=config_data, partial=True)
            if cfg_ser.is_valid(raise_exception=True):
                cfg_ser.save()

        return instance

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, instance, validated_data):
        from parser.models import ChannelConfig
        from parser.serializers import ChannelConfigSerializer

        config_data = validated_data.pop("_config_data", None)

        # Update client identity fields
        instance = super().update(instance, validated_data)

        # Update ChannelConfig if config data was supplied
        if config_data is not None:
            cfg, _ = ChannelConfig.objects.get_or_create(client=instance)
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
        if channel_id and client.channel_id != channel_id.strip():
            raise serializers.ValidationError(
                {"channel_id": "channel_id does not match client config."}
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
        return attrs
