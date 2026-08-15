#!/usr/bin/env python3
"""Count mutually exclusive JSHClass aux-field populations in heap snapshots.

The matching rawheap translator emits a named edge only when a tagged slot holds
an object reference. This script therefore measures the live non-default
population of EnumCache, ProtoChangeMarker, ProtoChangeDetails, and
DependentInfos per HClass. A named edge is sufficient for the four fields in
the translated snapshots because every non-default value is a heap object.
"""

import argparse
import gc
import json
from pathlib import Path

FIELD_BITS = {
    "EnumCache": 1,
    "ProtoChangeMarker": 2,
    "ProtoChangeDetails": 4,
    "DependentInfos": 8,
}


def mask_name(mask: int) -> str:
    if mask == 0:
        return "none"
    names = [name for name, bit in FIELD_BITS.items() if mask & bit]
    return "+".join(names)


def census(path: Path) -> dict[str, int]:
    # Some translated snapshots contain raw control characters in strings.
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"), strict=False)
    snapshot = data["snapshot"]
    meta = snapshot["meta"]
    node_fields = meta["node_fields"]
    edge_fields = meta["edge_fields"]
    node_stride = len(node_fields)
    edge_stride = len(edge_fields)
    node_index = {name: index for index, name in enumerate(node_fields)}
    edge_index = {name: index for index, name in enumerate(edge_fields)}
    edge_types = meta["edge_types"][0]
    nodes = data["nodes"]
    edges = data["edges"]
    strings = data["strings"]

    populations = [0] * (1 << len(FIELD_BITS))
    hclass_masks = {}
    edge_offset = 0
    for node_number, offset in enumerate(range(0, len(nodes), node_stride)):
        edge_count = nodes[offset + node_index["edge_count"]]
        name = strings[nodes[offset + node_index["name"]]]
        if name == "hclass":
            mask = 0
            for edge_number in range(edge_count):
                edge_offset_flat = (edge_offset + edge_number) * edge_stride
                edge_type = edge_types[edges[edge_offset_flat + edge_index["type"]]]
                if edge_type == "element":
                    continue
                edge_name = strings[edges[edge_offset_flat + edge_index["name_or_index"]]]
                mask |= FIELD_BITS.get(edge_name, 0)
            populations[mask] += 1
            hclass_masks[node_number] = mask
        edge_offset += edge_count

    shared_hclasses = set()
    edge_offset = 0
    for offset in range(0, len(nodes), node_stride):
        edge_count = nodes[offset + node_index["edge_count"]]
        name = strings[nodes[offset + node_index["name"]]]
        if name.startswith("js_shared_") or name.startswith("shared_"):
            for edge_number in range(edge_count):
                edge_offset_flat = (edge_offset + edge_number) * edge_stride
                edge_type = edge_types[edges[edge_offset_flat + edge_index["type"]]]
                if edge_type == "element":
                    continue
                edge_name = strings[edges[edge_offset_flat + edge_index["name_or_index"]]]
                if edge_name == "hclass":
                    target = edges[edge_offset_flat + edge_index["to_node"]] // node_stride
                    if target in hclass_masks:
                        shared_hclasses.add(target)
        edge_offset += edge_count

    result = {mask_name(mask): count for mask, count in enumerate(populations)}
    result["hclass"] = sum(populations)
    result["union_nonempty"] = result["hclass"] - result["none"]
    result["enum_total"] = sum(count for mask, count in enumerate(populations) if mask & 1)
    result["marker_total"] = sum(count for mask, count in enumerate(populations) if mask & 2)
    result["details_total"] = sum(count for mask, count in enumerate(populations) if mask & 4)
    result["dependent_total"] = sum(count for mask, count in enumerate(populations) if mask & 8)
    result["shared_hclass"] = len(shared_hclasses)
    result["shared_union_nonempty"] = sum(hclass_masks[node] != 0 for node in shared_hclasses)

    del data, nodes, edges, strings
    gc.collect()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    apps = {}
    for path in args.snapshots:
        apps[path.stem] = census(path)
        print(f"{path.name}: {apps[path.stem]}", flush=True)

    keys = next(iter(apps.values())).keys()
    total = {key: sum(app[key] for app in apps.values()) for key in keys}
    output = {"apps": apps, "total": total}
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    print("---TOTAL---")
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
