"""Ingest: normalised features → feature_definitions / feature_latest / history (docs/03).

History rule: a numeric/bool/string property is written to `feature_values` when its value
changed versus `feature_latest` OR at least 1 h passed since the last history row (so charts of
constant values have no gaps). JSON/schedule/array values only update `feature_latest` and go to
`feature_json_history` when their hash changes.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.adapters.base import Feature
from apps.devices.grouping import group_key
from apps.devices.models import (
    Device,
    FeatureDefinition,
    FeatureJsonHistory,
    FeatureLatest,
    FeatureValue,
)

HISTORY_HEARTBEAT = timedelta(hours=1)


@dataclass
class IngestStats:
    definitions_created: int = 0
    definitions_updated: int = 0
    latest_upserted: int = 0
    history_rows: int = 0
    json_history_rows: int = 0


def _ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, UTC)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _split_value(value: Any, value_type: str) -> tuple[float | None, bool | None, str | None, Any]:
    """→ (value_num, value_bool, value_text, value_json) by normalised type + actual value."""
    if value is None:
        return None, None, None, None
    if value_type == "boolean" or isinstance(value, bool):
        return None, bool(value), None, None
    if value_type == "number" and isinstance(value, int | float):
        return float(value), None, None, None
    if value_type == "string" and isinstance(value, str):
        return None, None, value, None
    if isinstance(value, int | float):
        return float(value), None, None, None
    if isinstance(value, str):
        return None, None, value, None
    return None, None, None, value


def ingest(
    device: Device, features: list[Feature], polled_at: datetime | None = None
) -> IngestStats:
    """Persist one poll result. Runs in one transaction (caller sets the RLS context)."""
    now = polled_at or timezone.now()
    stats = IngestStats()
    with transaction.atomic():
        existing_defs = {d.feature_name: d for d in FeatureDefinition.objects.filter(device=device)}
        latest_rows = {
            (r.feature_name, r.property_name): r
            for r in FeatureLatest.objects.filter(device=device)
        }
        history: list[FeatureValue] = []
        json_history: list[FeatureJsonHistory] = []

        for feature in features:
            _upsert_definition(device, feature, existing_defs, now, stats)
            if not feature.enabled:
                continue  # docs/01 §4 rule 2: definition only, no values/history
            for prop in feature.properties.values():
                num, boolean, text, js = _split_value(prop.value, prop.type)
                key = (feature.name, prop.name)
                row = latest_rows.get(key)
                ts_device = _ts(prop.ts_device)
                is_scalar = js is None
                changed = (
                    row is None
                    or row.value_num != num
                    or row.value_bool != boolean
                    or row.value_text != text
                    or (not is_scalar and _json_hash(row.value_json) != _json_hash(js))
                )
                heartbeat_due = (
                    row is None
                    or row.last_history_at is None
                    or (now - row.last_history_at >= HISTORY_HEARTBEAT)
                )
                write_history = is_scalar and prop.value is not None and (changed or heartbeat_due)

                if row is None:
                    row = FeatureLatest(
                        tenant=device.tenant,
                        device=device,
                        feature_name=feature.name,
                        property_name=prop.name,
                    )
                    latest_rows[key] = row
                row.value_num, row.value_bool, row.value_text, row.value_json = (
                    num,
                    boolean,
                    text,
                    js,
                )
                row.unit = prop.unit
                row.ts_device = ts_device
                row.ts_polled = now
                if write_history:
                    row.last_history_at = now
                    history.append(
                        FeatureValue(
                            tenant=device.tenant,
                            device=device,
                            feature_name=feature.name,
                            property_name=prop.name,
                            ts_polled=now,
                            ts_device=ts_device,
                            value_num=num,
                            value_bool=boolean,
                            value_text=text,
                        )
                    )
                if not is_scalar and changed:
                    json_history.append(
                        FeatureJsonHistory(
                            tenant=device.tenant,
                            device=device,
                            feature_name=feature.name,
                            property_name=prop.name,
                            ts=now,
                            value_json=js,
                            value_hash=_json_hash(js),
                        )
                    )
                row.save()
                stats.latest_upserted += 1

        if history:
            FeatureValue.objects.bulk_create(history)
            stats.history_rows = len(history)
        if json_history:
            FeatureJsonHistory.objects.bulk_create(json_history)
            stats.json_history_rows = len(json_history)
    return stats


def _upsert_definition(
    device: Device,
    feature: Feature,
    existing: dict[str, FeatureDefinition],
    now: datetime,
    stats: IngestStats,
) -> None:
    properties_schema = {
        p.name: {"type": p.type, "unit": p.unit} for p in feature.properties.values()
    }
    commands_schema = {
        c.name: {
            "isExecutable": c.executable,
            "params": {
                p.name: {"type": p.type, "required": p.required, "constraints": p.constraints}
                for p in c.params.values()
            },
        }
        for c in feature.commands.values()
    }
    command_uris = {c.name: c.uri for c in feature.commands.values() if c.uri}
    definition = existing.get(feature.name)
    if definition is None:
        FeatureDefinition.objects.create(
            tenant=device.tenant,
            device=device,
            feature_name=feature.name,
            is_enabled=feature.enabled,
            is_ready=feature.ready,
            group_key=group_key(feature.name),
            properties_schema=properties_schema,
            commands_schema=commands_schema,
            command_uris=command_uris,
            last_seen_at=now,
        )
        stats.definitions_created += 1
        return
    definition.is_enabled = feature.enabled
    definition.is_ready = feature.ready
    definition.properties_schema = properties_schema
    definition.commands_schema = commands_schema
    definition.command_uris = command_uris
    definition.last_seen_at = now
    definition.save(
        update_fields=[
            "is_enabled",
            "is_ready",
            "properties_schema",
            "commands_schema",
            "command_uris",
            "last_seen_at",
        ]
    )
    stats.definitions_updated += 1
