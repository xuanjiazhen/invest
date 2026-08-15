#!/usr/bin/env python3
"""Census ConstantPool physical slots and visible object edges.

This script is intentionally conservative. It supports the V1-like Top13
heapsnapshots whose ConstantPool nodes are named ``constant_pool`` and whose
element edge indexes preserve physical TaggedArray positions. Missing edges
are not classified as Hole because primitive tagged values may also be absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CONSTANT_POOL_NAME = "constant_pool"
TAGGED_ARRAY_HEADER_BYTES = 16
TAGGED_SLOT_BYTES = 8
TAIL_SLOTS = 9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def census(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"), strict=False)
    meta = data["snapshot"]["meta"]
    node_fields = meta["node_fields"]
    node_index = {name: index for index, name in enumerate(node_fields)}
    node_stride = len(node_fields)
    edge_fields = meta["edge_fields"]
    edge_index = {name: index for index, name in enumerate(edge_fields)}
    edge_stride = len(edge_fields)
    edge_types = meta["edge_types"][0]
    nodes = data["nodes"]
    edges = data["edges"]
    strings = data["strings"]

    result = {
        "pool_count": 0,
        "self_size_bytes": 0,
        "physical_slots": 0,
        "user_slots": 0,
        "visible_user_object_edges": 0,
        "visible_tail_object_edges": 0,
        "other_element_edges": 0,
        "property_edges": 0,
        "pools_with_invalid_size": 0,
        "pools_with_out_of_range_element_index": 0,
    }

    edge_cursor = 0
    for node_offset in range(0, len(nodes), node_stride):
        edge_count = nodes[node_offset + node_index["edge_count"]]
        name = strings[nodes[node_offset + node_index["name"]]]
        if name == CONSTANT_POOL_NAME:
            self_size = nodes[node_offset + node_index["self_size"]]
            payload_bytes = self_size - TAGGED_ARRAY_HEADER_BYTES
            if payload_bytes < TAIL_SLOTS * TAGGED_SLOT_BYTES or payload_bytes % TAGGED_SLOT_BYTES != 0:
                result["pools_with_invalid_size"] += 1
            else:
                physical_slots = payload_bytes // TAGGED_SLOT_BYTES
                user_slots = physical_slots - TAIL_SLOTS
                result["pool_count"] += 1
                result["self_size_bytes"] += self_size
                result["physical_slots"] += physical_slots
                result["user_slots"] += user_slots

                out_of_range = False
                for edge_number in range(edge_cursor, edge_cursor + edge_count):
                    offset = edge_number * edge_stride
                    edge_type = edge_types[edges[offset + edge_index["type"]]]
                    if edge_type == "property":
                        result["property_edges"] += 1
                        continue
                    if edge_type != "element":
                        continue
                    physical_index = edges[offset + edge_index["name_or_index"]]
                    if physical_index < user_slots:
                        result["visible_user_object_edges"] += 1
                    elif physical_index < physical_slots:
                        result["visible_tail_object_edges"] += 1
                    else:
                        result["other_element_edges"] += 1
                        out_of_range = True
                if out_of_range:
                    result["pools_with_out_of_range_element_index"] += 1
        edge_cursor += edge_count

    result["user_bytes"] = result["user_slots"] * TAGGED_SLOT_BYTES
    result["visible_user_object_edge_rate"] = (
        result["visible_user_object_edges"] / result["user_slots"]
        if result["user_slots"]
        else 0.0
    )
    return result


def sum_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    integer_keys = [
        "pool_count",
        "self_size_bytes",
        "physical_slots",
        "user_slots",
        "visible_user_object_edges",
        "visible_tail_object_edges",
        "other_element_edges",
        "property_edges",
        "pools_with_invalid_size",
        "pools_with_out_of_range_element_index",
        "user_bytes",
    ]
    total = {key: sum(result[key] for result in results) for key in integer_keys}
    total["visible_user_object_edge_rate"] = (
        total["visible_user_object_edges"] / total["user_slots"]
        if total["user_slots"]
        else 0.0
    )
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ets-runtime-commit", default="unknown")
    parser.add_argument("--runtime-core-commit", default="unknown")
    args = parser.parse_args()

    apps: dict[str, dict[str, Any]] = {}
    inputs = []
    for path in sorted(args.snapshots):
        app = path.name.removesuffix(".heapsnapshot")
        apps[app] = census(path)
        inputs.append({"file": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})

    output = {
        "scope": {
            "node_name": CONSTANT_POOL_NAME,
            "translator_semantics": "V1-like physical element indexes",
            "missing_edge_interpretation": "unknown; not classified as Hole",
            "shared_unshared_classification": "not available from these snapshots",
            "ets_runtime_commit": args.ets_runtime_commit,
            "runtime_core_commit": args.runtime_core_commit,
        },
        "inputs": inputs,
        "apps": apps,
        "total": sum_results(list(apps.values())),
    }

    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
