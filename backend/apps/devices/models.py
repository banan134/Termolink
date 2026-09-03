"""Devices, feature definitions, latest values and history — docs/03 §Urządzenia i cechy."""

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


class DeviceMode(models.TextChoices):
    READ = "read", "Odczyt"
    CONTROL = "control", "Sterowanie"


class DeviceStatus(models.TextChoices):
    UNKNOWN = "unknown", "Nieznany"
    ONLINE = "online", "Online"
    OFFLINE = "offline", "Offline"
    ERROR = "error", "Błąd"
    RATE_LIMITED = "rate_limited", "Limit API"


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="devices")
    provider_account = models.ForeignKey(
        "providers.ProviderAccount", on_delete=models.PROTECT, related_name="devices"
    )
    provider = models.TextField()
    external_ids = models.JSONField()  # {installationId, gatewaySerial, deviceId}
    model = models.TextField(blank=True, default="")
    serial = models.TextField(null=True, blank=True)  # noqa: DJ001
    display_name = models.TextField()
    description = models.TextField(null=True, blank=True)  # noqa: DJ001
    location_text = models.TextField(null=True, blank=True)  # noqa: DJ001
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    mode = models.TextField(choices=DeviceMode.choices, default=DeviceMode.READ)
    poll_interval_s = models.IntegerField(null=True, blank=True)  # NULL = automatic (budget)
    next_poll_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(choices=DeviceStatus.choices, default=DeviceStatus.UNKNOWN)
    status_since = models.DateTimeField(default=timezone.now)
    status_detail = models.TextField(null=True, blank=True)  # noqa: DJ001
    consecutive_errors = models.IntegerField(default=0)
    commands_per_hour_limit = models.IntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devices"
        ordering = ["display_name"]
        constraints = [
            # docs/03: UNIQUE (provider_account, installationId, gatewaySerial, deviceId)
            models.UniqueConstraint(
                "provider_account",
                models.F("external_ids__installationId"),
                models.F("external_ids__gatewaySerial"),
                models.F("external_ids__deviceId"),
                name="devices_external_ids_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def is_active(self) -> bool:
        return self.archived_at is None


class FeatureDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="feature_definitions")
    feature_name = models.TextField()  # exactly as in the API
    is_enabled = models.BooleanField(default=True)
    is_ready = models.BooleanField(default=True)
    group_key = models.TextField()
    properties_schema = models.JSONField(default=dict)  # {prop: {type, unit}}
    commands_schema = models.JSONField(default=dict)  # {cmd: {isExecutable, params}}
    command_uris = models.JSONField(default=dict)  # {cmd: uri}
    unsupported_commands = ArrayField(models.TextField(), default=list, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "feature_definitions"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "feature_name"], name="feature_definitions_uq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.device_id} {self.feature_name}"


class FeatureLatest(models.Model):
    """Last value per (device, feature, property); every view reads from here (docs/00)."""

    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="latest_values")
    feature_name = models.TextField()
    property_name = models.TextField()
    value_num = models.FloatField(null=True, blank=True)
    value_bool = models.BooleanField(null=True, blank=True)
    value_text = models.TextField(null=True, blank=True)  # noqa: DJ001
    value_json = models.JSONField(null=True, blank=True)
    unit = models.TextField(null=True, blank=True)  # noqa: DJ001
    ts_device = models.DateTimeField(null=True, blank=True)
    ts_polled = models.DateTimeField()
    last_history_at = models.DateTimeField(null=True, blank=True)  # for the "≥ 1 h" rule

    class Meta:
        db_table = "feature_latest"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "feature_name", "property_name"], name="feature_latest_pk"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.feature_name}.{self.property_name}"


class FeatureValue(models.Model):
    """History — TimescaleDB hypertable on ts_polled (docs/03).

    Unmanaged: the table is created by migration 0002 via SQL (a serial PK is not allowed on a
    hypertable, so there is no `id`; `ts_polled` is declared as the ORM pk only so Django can
    instantiate rows — inserts go through bulk_create, single-row updates are never used).
    """

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.DO_NOTHING, related_name="+", db_constraint=False
    )
    device = models.ForeignKey(
        Device, on_delete=models.DO_NOTHING, related_name="+", db_constraint=False
    )
    feature_name = models.TextField()
    property_name = models.TextField()
    ts_polled = models.DateTimeField(primary_key=True)
    ts_device = models.DateTimeField(null=True, blank=True)
    value_num = models.FloatField(null=True, blank=True)
    value_bool = models.BooleanField(null=True, blank=True)
    value_text = models.TextField(null=True, blank=True)  # noqa: DJ001

    class Meta:
        db_table = "feature_values_rls"  # security_barrier view over the hypertable (docs/03)
        managed = False

    def __str__(self) -> str:
        return f"{self.feature_name}.{self.property_name}@{self.ts_polled:%Y-%m-%d %H:%M}"


class FeatureJsonHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="+")
    feature_name = models.TextField()
    property_name = models.TextField()
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    value_json = models.JSONField()
    value_hash = models.TextField()

    class Meta:
        db_table = "feature_json_history"

    def __str__(self) -> str:
        return f"{self.feature_name}.{self.property_name}@{self.ts:%Y-%m-%d %H:%M}"


class DeviceStatusHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="status_history")
    status = models.TextField(choices=DeviceStatus.choices)
    since = models.DateTimeField(default=timezone.now)
    until = models.DateTimeField(null=True, blank=True)
    detail = models.TextField(null=True, blank=True)  # noqa: DJ001

    class Meta:
        db_table = "device_status_history"
        indexes = [models.Index(fields=["device", "-since"], name="device_status_hist_dev")]

    def __str__(self) -> str:
        return f"{self.device_id} {self.status} since {self.since:%Y-%m-%d %H:%M}"


class DiscoveredDevice(models.Model):
    """Cache of the installation tree from `discover` (docs/03)."""

    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    provider_account = models.ForeignKey(
        "providers.ProviderAccount", on_delete=models.CASCADE, related_name="discovered_devices"
    )
    installation_id = models.TextField()
    gateway_serial = models.TextField()
    device_id = models.TextField()
    model = models.TextField(null=True, blank=True)  # noqa: DJ001
    device_type = models.TextField(null=True, blank=True)  # noqa: DJ001
    online = models.BooleanField(null=True, blank=True)
    raw = models.JSONField(default=dict)
    seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "discovered_devices"
        constraints = [
            models.UniqueConstraint(
                fields=["provider_account", "installation_id", "gateway_serial", "device_id"],
                name="discovered_devices_pk",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.installation_id}/{self.gateway_serial}/{self.device_id}"

    @property
    def external_ids(self) -> dict[str, str]:
        return {
            "installationId": self.installation_id,
            "gatewaySerial": self.gateway_serial,
            "deviceId": self.device_id,
        }


class FeatureLabel(models.Model):
    """Global operator dictionary (docs/03 `feature_labels`): labels, grouping, highlights."""

    feature_name_pattern = models.TextField(primary_key=True)
    label_pl = models.TextField(blank=True, default="")
    description_pl = models.TextField(blank=True, default="")
    group_key = models.TextField(null=True, blank=True)  # noqa: DJ001 — NULL = rule from grouping.py
    sort = models.IntegerField(default=100)
    highlight = models.BooleanField(default=False)
    report_default = models.BooleanField(default=False)
    command_property_map = models.JSONField(default=dict, blank=True)  # {cmd: {param: property}}
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "feature_labels"
        ordering = ["feature_name_pattern"]

    def __str__(self) -> str:
        return f"{self.feature_name_pattern} → {self.label_pl}"
