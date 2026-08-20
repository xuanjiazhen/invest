#!/usr/bin/env python3
"""Reproducible LayoutInfo sharing census for ArkVM heap snapshots.

Two snapshot schemas are supported:

* legacy: hclass --Layout--> tagged_array; primitive Attr slots are omitted.
  The result is a conservative key-identity/capacity grouping upper bound, not
  proof that PropertyAttributes are equal.
* translated-v2: HiddenClass(...) --Layout--> ArkInternalArray; primitive Attr
  slots are materialized as number nodes.  Only arrays whose key and Attr slots
  can be reconstructed completely are admitted to the strict-content model.

The script never interprets a missing edge as a Hole for a live property.  It
reports excluded arrays separately and retains physical self_size/capacity in
all fingerprints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

MIB = 1024 * 1024
HEADER_BYTES = 16
TAGGED_BYTES = 8
DEFAULT_ENTRY_BYTES = 16
DEFAULT_LOAD_FACTOR = 0.75


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * MIB), b""):
            digest.update(block)
    return digest.hexdigest()


class Snapshot:
    def __init__(self, path: Path) -> None:
        self.path = path
        with path.open(encoding="utf-8", errors="replace") as source:
            self.data = json.load(source, strict=False)
        snapshot = self.data["snapshot"]
        self.node_fields = snapshot["meta"]["node_fields"]
        self.edge_fields = snapshot["meta"]["edge_fields"]
        self.node_stride = len(self.node_fields)
        self.edge_stride = len(self.edge_fields)
        self.node_index = {name: i for i, name in enumerate(self.node_fields)}
        self.edge_index = {name: i for i, name in enumerate(self.edge_fields)}
        self.node_types = snapshot["meta"]["node_types"][0]
        self.edge_types = snapshot["meta"]["edge_types"][0]
        self.nodes = self.data["nodes"]
        self.edges = self.data["edges"]
        self.strings = self.data["strings"]
        self.node_count = len(self.nodes) // self.node_stride
        self.edge_starts: List[int] = []
        edge_count = 0
        for node in range(self.node_count):
            self.edge_starts.append(edge_count)
            edge_count += self.node_field(node, "edge_count")
        self.edge_count = edge_count

    def node_field(self, node: int, field: str) -> int:
        return self.nodes[node * self.node_stride + self.node_index[field]]

    def node_name(self, node: int) -> str:
        return self.strings[self.node_field(node, "name")]

    def node_type(self, node: int) -> str:
        return self.node_types[self.node_field(node, "type")]

    def outgoing(self, node: int) -> Iterable[Tuple[str, Any, int]]:
        base = self.edge_starts[node] * self.edge_stride
        count = self.node_field(node, "edge_count")
        for edge in range(count):
            offset = base + edge * self.edge_stride
            edge_type = self.edge_types[self.edges[offset + self.edge_index["type"]]]
            raw_name = self.edges[offset + self.edge_index["name_or_index"]]
            name = raw_name if edge_type == "element" else self.strings[raw_name]
            target = self.edges[offset + self.edge_index["to_node"]] // self.node_stride
            yield edge_type, name, target


def table_cost(entries: int, entry_bytes: int, load_factor: float) -> int:
    if entries == 0:
        return 0
    return math.ceil(entries / load_factor) * entry_bytes


def group_summary(groups: Dict[Tuple[Any, ...], List[Tuple[int, int]]],
                  entry_bytes: int, load_factor: float) -> Dict[str, Any]:
    duplicate_groups = [members for members in groups.values() if len(members) > 1]
    canonical_bytes = sum(members[0][1] for members in groups.values())
    observed_bytes = sum(size for members in groups.values() for _, size in members)
    gross = observed_bytes - canonical_bytes
    cost_all = table_cost(len(groups), entry_bytes, load_factor)
    cost_duplicates_only = table_cost(len(duplicate_groups), entry_bytes, load_factor)
    return {
        "observed_objects": sum(len(members) for members in groups.values()),
        "observed_bytes": observed_bytes,
        "unique_contents": len(groups),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_objects": sum(len(members) - 1 for members in duplicate_groups),
        "canonical_bytes": canonical_bytes,
        "gross_shareable_bytes": gross,
        "table_model": {
            "entry_bytes": entry_bytes,
            "load_factor": load_factor,
            "cost_index_all_unique_contents": cost_all,
            "conditional_net_index_all_unique_contents": gross - cost_all,
            "cost_index_duplicate_groups_only": cost_duplicates_only,
            "conditional_net_index_duplicate_groups_only": gross - cost_duplicates_only,
        },
    }


def detect_schema(snapshot: Snapshot) -> str:
    names = Counter(snapshot.node_name(node) for node in range(snapshot.node_count))
    if names["HiddenClass(NonMovable)"] and names["ArkInternalArray"]:
        return "translated-v2"
    if names["hclass"] and names["tagged_array"]:
        return "legacy"
    raise ValueError(f"unsupported snapshot schema: {snapshot.path}")


def layout_owners(snapshot: Snapshot, schema: str) -> Tuple[Dict[int, List[int]], int]:
    owners: Dict[int, List[int]] = defaultdict(list)
    hclass_count = 0
    for node in range(snapshot.node_count):
        name = snapshot.node_name(node)
        is_hclass = name.startswith("HiddenClass(") if schema == "translated-v2" else name == "hclass"
        if not is_hclass:
            continue
        hclass_count += 1
        for edge_type, edge_name, target in snapshot.outgoing(node):
            del edge_type
            if edge_name == "Layout":
                owners[target].append(node)
    return owners, hclass_count


def capacity_from_size(size: int) -> int | None:
    payload = size - HEADER_BYTES
    if payload < 0 or payload % (2 * TAGGED_BYTES) != 0:
        return None
    return payload // (2 * TAGGED_BYTES)


def strict_v2_fingerprint(snapshot: Snapshot, layout: int) -> Tuple[Tuple[Any, ...] | None, str]:
    size = snapshot.node_field(layout, "self_size")
    capacity = capacity_from_size(size)
    if capacity is None:
        return None, "invalid_size"
    elements: Dict[int, int] = {}
    for edge_type, edge_name, target in snapshot.outgoing(layout):
        if edge_type != "element":
            continue
        try:
            slot = int(edge_name)
        except (TypeError, ValueError):
            return None, "invalid_element_index"
        if slot < 0 or slot >= capacity * 2 or slot in elements:
            return None, "invalid_or_duplicate_slot"
        elements[slot] = target

    key_slots = sorted(slot for slot in elements if slot % 2 == 0)
    property_count = 0
    while property_count * 2 in elements:
        property_count += 1
    expected_key_slots = list(range(0, property_count * 2, 2))
    if key_slots != expected_key_slots:
        return None, "non_contiguous_keys"

    slots: List[Tuple[int | None, int]] = []
    for prop in range(property_count):
        key_slot = prop * 2
        attr_slot = key_slot + 1
        if attr_slot not in elements:
            return None, "missing_live_attr"
        key_target = elements[key_slot]
        attr_target = elements[attr_slot]
        if snapshot.node_type(key_target) not in {"string", "symbol", "slicedstring", "concatenated string"}:
            return None, "unsupported_key_type"
        if snapshot.node_type(attr_target) != "number" or snapshot.node_name(attr_target) != "Int":
            return None, "unsupported_attr_type"
        slots.append((key_target, attr_target))

    # Include every physical slack Attr in the fingerprint.  Missing key edges
    # are recorded as None only after proving that no later key exists.
    for prop in range(property_count, capacity):
        if prop * 2 in elements:
            return None, "key_after_logical_end"
        attr_slot = prop * 2 + 1
        if attr_slot not in elements:
            return None, "missing_slack_attr"
        target = elements[attr_slot]
        if snapshot.node_type(target) != "number" or snapshot.node_name(target) != "Int":
            return None, "unsupported_slack_attr_type"
        slots.append((None, target))
    return (capacity, tuple(slots)), "ok"


def legacy_fingerprint(snapshot: Snapshot, layout: int) -> Tuple[Tuple[Any, ...] | None, str]:
    size = snapshot.node_field(layout, "self_size")
    capacity = capacity_from_size(size)
    if capacity is None:
        return None, "invalid_size"
    keys: Dict[int, int] = {}
    for edge_type, edge_name, target in snapshot.outgoing(layout):
        if edge_type != "element":
            continue
        try:
            slot = int(edge_name)
        except (TypeError, ValueError):
            return None, "invalid_element_index"
        if slot < 0 or slot >= capacity * 2 or slot % 2 != 0 or slot in keys:
            return None, "unexpected_or_duplicate_slot"
        keys[slot] = target
    property_count = 0
    while property_count * 2 in keys:
        property_count += 1
    if sorted(keys) != list(range(0, property_count * 2, 2)):
        return None, "non_contiguous_keys"
    return (capacity, tuple(keys[prop * 2] for prop in range(property_count))), "ok"


def census(path: Path, entry_bytes: int, load_factor: float) -> Dict[str, Any]:
    snapshot = Snapshot(path)
    schema = detect_schema(snapshot)
    owners, hclass_count = layout_owners(snapshot, schema)
    groups: Dict[Tuple[Any, ...], List[Tuple[int, int]]] = defaultdict(list)
    excluded = Counter()
    admitted_bytes = 0
    all_layout_bytes = 0
    multi_owner_layouts = 0
    multi_owner_refs = 0

    for layout, layout_owners_list in owners.items():
        size = snapshot.node_field(layout, "self_size")
        all_layout_bytes += size
        if len(layout_owners_list) > 1:
            multi_owner_layouts += 1
            multi_owner_refs += len(layout_owners_list)
        if schema == "translated-v2":
            fingerprint, reason = strict_v2_fingerprint(snapshot, layout)
        else:
            fingerprint, reason = legacy_fingerprint(snapshot, layout)
        if fingerprint is None:
            excluded[reason] += 1
            continue
        admitted_bytes += size
        groups[fingerprint].append((layout, size))

    model = group_summary(groups, entry_bytes, load_factor)
    model["interpretation"] = (
        "strict same-snapshot object-identity plus complete Attr tagged-word identity"
        if schema == "translated-v2" else
        "upper bound: same capacity and key object identity; Attr primitive values are absent"
    )
    return {
        "application": path.name.removesuffix(".heapsnapshot"),
        "input": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "collection_time": None,
            "collection_time_note": "not encoded in the heap snapshot; file mtime is not treated as collection time",
        },
        "schema": schema,
        "snapshot": {
            "node_count": snapshot.node_count,
            "edge_count": snapshot.edge_count,
            "heap_self_size_bytes": sum(snapshot.node_field(node, "self_size") for node in range(snapshot.node_count)),
            "vm_count": None,
            "vm_count_note": "the snapshot does not expose a proven VM/Realm ownership field for each LayoutInfo",
        },
        "population": {
            "hclass_objects": hclass_count,
            "distinct_layout_targets": len(owners),
            "layout_shallow_bytes": all_layout_bytes,
            "multi_owner_layout_targets": multi_owner_layouts,
            "multi_owner_hclass_refs": multi_owner_refs,
            "model_admitted_layouts": model["observed_objects"],
            "model_admitted_bytes": admitted_bytes,
            "model_coverage_by_count": model["observed_objects"] / len(owners) if owners else 0.0,
            "model_coverage_by_bytes": admitted_bytes / all_layout_bytes if all_layout_bytes else 0.0,
            "excluded_layouts_by_reason": dict(sorted(excluded.items())),
        },
        "content_model": model,
    }


def aggregate(apps: Sequence[Dict[str, Any]], entry_bytes: int, load_factor: float) -> Dict[str, Any]:
    gross_values = [app["content_model"]["gross_shareable_bytes"] for app in apps]
    net_values = [app["content_model"]["table_model"]["conditional_net_index_all_unique_contents"] for app in apps]
    no_benefit = [app["application"] for app in apps if app["content_model"]["gross_shareable_bytes"] <= 0]
    totals = Counter()
    for app in apps:
        pop = app["population"]
        model = app["content_model"]
        totals.update({
            "hclass_objects": pop["hclass_objects"],
            "distinct_layout_targets": pop["distinct_layout_targets"],
            "layout_shallow_bytes": pop["layout_shallow_bytes"],
            "model_admitted_layouts": pop["model_admitted_layouts"],
            "model_admitted_bytes": pop["model_admitted_bytes"],
            "unique_contents": model["unique_contents"],
            "duplicate_groups": model["duplicate_groups"],
            "duplicate_objects": model["duplicate_objects"],
            "canonical_bytes": model["canonical_bytes"],
            "gross_shareable_bytes": model["gross_shareable_bytes"],
        })
    # Applications are separate processes.  Sum their independent table costs;
    # never model one canonical table spanning multiple applications.
    totals["table_cost_index_all_unique_contents"] = sum(
        app["content_model"]["table_model"]["cost_index_all_unique_contents"] for app in apps
    )
    totals["conditional_net_index_all_unique_contents"] = sum(net_values)
    return {
        "application_count": len(apps),
        "totals": dict(totals),
        "per_application_distribution_bytes": {
            "gross_shareable": {
                "p25": percentile(gross_values, 0.25),
                "median": statistics.median(gross_values) if gross_values else 0.0,
                "p75": percentile(gross_values, 0.75),
                "maximum": max(gross_values, default=0),
            },
            "conditional_net_index_all_unique_contents": {
                "p25": percentile(net_values, 0.25),
                "median": statistics.median(net_values) if net_values else 0.0,
                "p75": percentile(net_values, 0.75),
                "maximum": max(net_values, default=0),
            },
        },
        "no_gross_benefit_applications": no_benefit,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--entry-bytes", type=int, default=DEFAULT_ENTRY_BYTES)
    parser.add_argument("--load-factor", type=float, default=DEFAULT_LOAD_FACTOR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.entry_bytes <= 0 or not 0 < args.load_factor <= 1:
        parser.error("entry bytes must be positive and load factor must be in (0, 1]")
    apps = [census(path, args.entry_bytes, args.load_factor) for path in args.snapshots]
    result = {
        "schema_version": 1,
        "units": "bytes unless stated otherwise",
        "table_assumption": {"entry_bytes": args.entry_bytes, "load_factor": args.load_factor},
        "limits": [
            "Results describe one GC terminal heap snapshot, not allocation counts or access heat.",
            "Legacy content groups omit PropertyAttributes and are upper bounds only.",
            "Same content does not prove VM/Realm/GC sharing eligibility.",
            "Gross or conditional net shallow bytes do not predict Region committed, RSS, or PSS.",
        ],
        "applications": apps,
        "aggregate": aggregate(apps, args.entry_bytes, args.load_factor),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
