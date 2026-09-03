"""feature_labels dictionary (docs/03): Polish labels, group overrides, highlights, command maps.

Patterns: exact feature names or `*` for one dotted segment (`heating.circuits.*.heating.curve`).
Exact matches win over wildcard ones; among wildcards the most specific (fewest `*`) wins.
The dictionary is global (operator-maintained) and cached per process.
"""

import csv
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.db import transaction

from .models import FeatureLabel

CSV_PATH = Path(__file__).resolve().parent / "data" / "feature_labels.csv"


@dataclass(frozen=True)
class Label:
    pattern: str
    label_pl: str
    description_pl: str
    group_key: str | None
    sort: int
    highlight: bool
    report_default: bool
    command_property_map: dict[str, dict[str, str]]


_lock = threading.Lock()
_cache: list[tuple[re.Pattern[str], int, Label]] | None = None


def _compile(pattern: str) -> re.Pattern[str]:
    parts = [r"[^.]+" if p == "*" else re.escape(p) for p in pattern.split(".")]
    return re.compile("^" + r"\.".join(parts) + "$")


def _load() -> list[tuple[re.Pattern[str], int, Label]]:
    global _cache
    with _lock:
        if _cache is None:
            rows = []
            for row in FeatureLabel.objects.all():
                label = Label(
                    pattern=row.feature_name_pattern,
                    label_pl=row.label_pl,
                    description_pl=row.description_pl,
                    group_key=row.group_key,
                    sort=row.sort,
                    highlight=row.highlight,
                    report_default=row.report_default,
                    command_property_map=dict(row.command_property_map or {}),
                )
                rows.append((_compile(label.pattern), label.pattern.count("*"), label))
            _cache = rows
        return _cache


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def resolve(feature_name: str) -> Label | None:
    best: tuple[int, Label] | None = None
    for regex, wildcards, label in _load():
        if regex.match(feature_name) and (best is None or wildcards < best[0]):
            best = (wildcards, label)
            if wildcards == 0:
                break
    return best[1] if best else None


def resolve_many(names: list[str]) -> dict[str, Label | None]:
    return {name: resolve(name) for name in names}


# --- import / export ---------------------------------------------------------------------------

_COLUMNS = [
    "pattern",
    "label_pl",
    "description_pl",
    "group_key",
    "sort",
    "highlight",
    "report_default",
    "command_property_map",
]


def import_csv(path: Path = CSV_PATH, *, replace: bool = False) -> int:
    """Upsert labels from the bundled CSV (used by the data migration, seed and the command)."""
    import json

    count = 0
    with transaction.atomic():
        if replace:
            FeatureLabel.objects.all().delete()
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                pattern = (row.get("pattern") or "").strip()
                if not pattern:
                    continue
                raw_map = (row.get("command_property_map") or "").strip()
                FeatureLabel.objects.update_or_create(
                    feature_name_pattern=pattern,
                    defaults={
                        "label_pl": (row.get("label_pl") or "").strip(),
                        "description_pl": (row.get("description_pl") or "").strip(),
                        "group_key": (row.get("group_key") or "").strip() or None,
                        "sort": int(row.get("sort") or 100),
                        "highlight": (row.get("highlight") or "0").strip() in ("1", "true", "True"),
                        "report_default": (row.get("report_default") or "0").strip()
                        in ("1", "true", "True"),
                        "command_property_map": json.loads(raw_map) if raw_map else {},
                    },
                )
                count += 1
    invalidate()
    return count


def bulk_replace(items: list[dict[str, Any]]) -> int:
    """PUT /admin/feature-labels: full replacement of the dictionary (docs/04)."""
    with transaction.atomic():
        FeatureLabel.objects.all().delete()
        FeatureLabel.objects.bulk_create(
            [
                FeatureLabel(
                    feature_name_pattern=item["pattern"],
                    label_pl=item.get("label_pl", ""),
                    description_pl=item.get("description_pl", ""),
                    group_key=item.get("group_key") or None,
                    sort=int(item.get("sort", 100)),
                    highlight=bool(item.get("highlight", False)),
                    report_default=bool(item.get("report_default", False)),
                    command_property_map=item.get("command_property_map") or {},
                )
                for item in items
            ]
        )
    invalidate()
    return len(items)


def as_rows() -> list[dict[str, Any]]:
    return [
        {
            "pattern": r.feature_name_pattern,
            "label_pl": r.label_pl,
            "description_pl": r.description_pl,
            "group_key": r.group_key,
            "sort": r.sort,
            "highlight": r.highlight,
            "report_default": r.report_default,
            "command_property_map": r.command_property_map,
        }
        for r in FeatureLabel.objects.order_by("feature_name_pattern")
    ]
