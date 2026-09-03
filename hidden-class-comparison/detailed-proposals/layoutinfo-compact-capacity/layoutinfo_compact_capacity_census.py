#!/usr/bin/env python3
"""Measure LayoutInfo physical-capacity slack from ArkVM snapshots.

The output is a structural upper bound only. It answers how many bytes would be
removed if each observed LayoutInfo were rebuilt with physical capacity equal
to the contiguous live key/Attr prefix. It does not prove creation origin,
future immutability, safe compaction eligibility, Region/RSS/PSS savings, or
PGO-family correctness.

Supported schemas:
* legacy: HiddenClass/hclass Layout targets where live keys are visible but Attr
  primitive nodes may be omitted;
* translated-v2: full physical key/Attr slots. These are admitted only when all
  live and slack Attr nodes can be reconstructed by the imported census module.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CENSUS = HERE.parent / "layoutinfo-sharing" / "layoutinfo_sharing_census.py"
HEADER_BYTES = 16
BYTES_PER_PROPERTY_CAPACITY = 16


def load_census(path: Path):
    spec = importlib.util.spec_from_file_location("layoutinfo_census_base", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def effective_property_count(schema: str, fingerprint: tuple[Any, ...]) -> int:
    if schema == "translated-v2":
        return sum(1 for key, _attr in fingerprint[1] if key is not None)
    return len(fingerprint[1])


def inspect(snapshot_path: Path, census_module) -> dict[str, Any]:
    snapshot = census_module.Snapshot(snapshot_path)
    schema = census_module.detect_schema(snapshot)
    owners, hclass_count = census_module.layout_owners(snapshot, schema)

    excluded = Counter()
    pairs = Counter()
    current_bytes = 0
    compact_bytes = 0
    positive_slack_objects = 0

    for layout_node in owners:
        size = snapshot.node_field(layout_node, "self_size")
        capacity = census_module.capacity_from_size(size)
        if capacity is None:
            excluded["invalid_size"] += 1
            continue
        if schema == "translated-v2":
            fingerprint, reason = census_module.strict_v2_fingerprint(snapshot, layout_node)
        else:
            fingerprint, reason = census_module.legacy_fingerprint(snapshot, layout_node)
        if fingerprint is None:
            excluded[reason] += 1
            continue

        properties = effective_property_count(schema, fingerprint)
        if properties > capacity:
            excluded["properties_gt_capacity"] += 1
            continue

        pairs[(properties, capacity)] += 1
        current_bytes += size
        compact_bytes += HEADER_BYTES + properties * BYTES_PER_PROPERTY_CAPACITY
        if capacity > properties:
            positive_slack_objects += 1

    slack_bytes = current_bytes - compact_bytes
    property_buckets = []
    for properties in sorted({properties for properties, _capacity in pairs}):
        bucket_objects = sum(
            count for (prop_count, _capacity), count in pairs.items() if prop_count == properties
        )
        bucket_current = sum(
            (HEADER_BYTES + capacity * BYTES_PER_PROPERTY_CAPACITY) * count
            for (prop_count, capacity), count in pairs.items()
            if prop_count == properties
        )
        bucket_compact = bucket_objects * (
            HEADER_BYTES + properties * BYTES_PER_PROPERTY_CAPACITY
        )
        property_buckets.append({
            "effective_properties": properties,
            "objects": bucket_objects,
            "current_shallow_bytes": bucket_current,
            "compact_shallow_bytes": bucket_compact,
            "slack_upper_bound_bytes": bucket_current - bucket_compact,
        })

    return {
        "application": snapshot_path.name.removesuffix(".heapsnapshot"),
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": census_module.sha256(snapshot_path),
        "schema": schema,
        "hclass_objects": hclass_count,
        "distinct_layout_targets": len(owners),
        "admitted_layouts": sum(pairs.values()),
        "excluded_layouts": dict(sorted(excluded.items())),
        "positive_slack_layouts": positive_slack_objects,
        "current_shallow_bytes": current_bytes,
        "compact_to_effective_count_bytes": compact_bytes,
        "slack_upper_bound_bytes": slack_bytes,
        "property_buckets": property_buckets,
        "capacity_pairs": [
            {
                "effective_properties": properties,
                "physical_capacity": capacity,
                "objects": count,
                "slack_upper_bound_bytes":
                    (capacity - properties) * BYTES_PER_PROPERTY_CAPACITY * count,
            }
            for (properties, capacity), count in sorted(pairs.items())
        ],
    }


def aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_keys = [
        "hclass_objects",
        "distinct_layout_targets",
        "admitted_layouts",
        "positive_slack_layouts",
        "current_shallow_bytes",
        "compact_to_effective_count_bytes",
        "slack_upper_bound_bytes",
    ]
    return {
        "sample_count": len(samples),
        **{key: sum(sample[key] for sample in samples) for key in numeric_keys},
    }


def write_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "application",
            "schema",
            "effective_properties",
            "objects",
            "current_shallow_bytes",
            "compact_shallow_bytes",
            "slack_upper_bound_bytes",
        ])
        for sample in samples:
            for bucket in sample["property_buckets"]:
                writer.writerow([
                    sample["application"],
                    sample["schema"],
                    bucket["effective_properties"],
                    bucket["objects"],
                    bucket["current_shallow_bytes"],
                    bucket["compact_shallow_bytes"],
                    bucket["slack_upper_bound_bytes"],
                ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--census-module", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()

    module = load_census(args.census_module)
    samples = [inspect(path, module) for path in args.snapshots]
    result = {
        "schema_version": 1,
        "units": "bytes unless stated otherwise",
        "model": {
            "self_size": "16 + 16 * physical_capacity",
            "compact_size": "16 + 16 * effective_property_count",
            "slack_upper_bound": "observed_self_size - compact_size",
        },
        "limits": [
            "This is a terminal-snapshot structural upper bound, not a creation-path-attributed benefit.",
            "Legacy snapshots can recover key prefixes and capacity but omit Attr primitive values.",
            "The result does not prove that capacity can be reduced safely for every observed LayoutInfo.",
            "PGO root/child family capacity, HClass inline capacity, fallback copies, Region committed, RSS, and PSS require runtime instrumentation and clean A/B.",
            "No LayoutInfo sharing, canonical table, weak registry, or COW benefit is included.",
        ],
        "samples": samples,
        "aggregate": aggregate(samples),
    }

    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.csv:
        write_csv(args.csv, samples)


if __name__ == "__main__":
    main()
