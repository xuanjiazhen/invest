#!/usr/bin/env python3
"""Recompute the FunctionTemplate compact-recipe shallow-byte model.

The input is an ArkVM heap snapshot in Chrome JSON form. The model admits only
ClassLiteral objects that directly own at least MIN_TEMPLATES_PER_CLASS distinct
FunctionTemplate objects through their Array. The proposal uses the same-sized
recipe representation in LocalHeap and SharedHeap while prohibiting cross-domain
references, so heap-domain metadata is not needed for this shallow-byte model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

MIB = 1024 * 1024
FUNCTION_TEMPLATE_SIZE = 40
TAGGED_ARRAY_HEADER_SIZE = 16
RECIPE_SLOTS_PER_TEMPLATE = 3
TAGGED_SLOT_SIZE = 8
CLASS_LITERAL_GROWTH = 8
MIN_TEMPLATES_PER_CLASS = 2
FUNCTION_TEMPLATE_NAMES = {
    "ArkInternalFunctionTemplate",
    "function_template",
}
CLASS_LITERAL_NAMES = {
    "ClassLiteral",
    "class_literal",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def edge_name(strings: list[str], raw_name: int) -> str:
    if 0 <= raw_name < len(strings):
        return strings[raw_name]
    return str(raw_name)


def analyze_snapshot(path: Path, label: str) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        # Legacy rawheap translations may contain literal control characters
        # inside strings. They do not affect the numeric node/edge tables used
        # by this census, so accept them while retaining all structural checks.
        data = json.load(stream, strict=False)

    metadata = data["snapshot"]["meta"]
    node_fields = metadata["node_fields"]
    edge_fields = metadata["edge_fields"]
    node_width = len(node_fields)
    edge_width = len(edge_fields)
    node_index = {name: index for index, name in enumerate(node_fields)}
    edge_index = {name: index for index, name in enumerate(edge_fields)}
    nodes = data["nodes"]
    edges = data["edges"]
    strings = data["strings"]

    names = [
        strings[nodes[offset + node_index["name"]]]
        for offset in range(0, len(nodes), node_width)
    ]
    self_sizes = [
        nodes[offset + node_index["self_size"]]
        for offset in range(0, len(nodes), node_width)
    ]
    edge_counts = [
        nodes[offset + node_index["edge_count"]]
        for offset in range(0, len(nodes), node_width)
    ]

    edge_starts: list[int] = []
    cursor = 0
    for count in edge_counts:
        edge_starts.append(cursor)
        cursor += count * edge_width

    template_aliases = sorted(set(names) & FUNCTION_TEMPLATE_NAMES)
    class_literal_aliases = sorted(set(names) & CLASS_LITERAL_NAMES)
    template_nodes = {
        index for index, name in enumerate(names)
        if name in FUNCTION_TEMPLATE_NAMES
    }
    template_size_histogram = Counter(self_sizes[index] for index in template_nodes)

    template_owner_counts = Counter()
    templates_per_class: list[int] = []
    class_literal_count = 0
    for class_index, name in enumerate(names):
        if name not in CLASS_LITERAL_NAMES:
            continue
        class_literal_count += 1
        arrays: list[int] = []
        start = edge_starts[class_index]
        end = start + edge_counts[class_index] * edge_width
        for edge_offset in range(start, end, edge_width):
            name_or_index = edges[edge_offset + edge_index["name_or_index"]]
            if edge_name(strings, name_or_index) == "Array":
                arrays.append(edges[edge_offset + edge_index["to_node"]] // node_width)

        owned_templates: set[int] = set()
        for array_index in arrays:
            array_start = edge_starts[array_index]
            array_end = array_start + edge_counts[array_index] * edge_width
            for edge_offset in range(array_start, array_end, edge_width):
                target = edges[edge_offset + edge_index["to_node"]] // node_width
                if target in template_nodes:
                    owned_templates.add(target)

        if owned_templates:
            templates_per_class.append(len(owned_templates))
            for template_index in owned_templates:
                template_owner_counts[template_index] += 1

    eligible_counts = [
        count for count in templates_per_class
        if count >= MIN_TEMPLATES_PER_CLASS
    ]
    eligible_templates = sum(eligible_counts)
    eligible_classes = len(eligible_counts)
    eligible_current_bytes = eligible_templates * FUNCTION_TEMPLATE_SIZE
    recipe_bytes = (
        eligible_classes * (TAGGED_ARRAY_HEADER_SIZE + CLASS_LITERAL_GROWTH)
        + eligible_templates * RECIPE_SLOTS_PER_TEMPLATE * TAGGED_SLOT_SIZE
    )
    conditional_net_bytes = eligible_current_bytes - recipe_bytes

    unowned_templates = len(template_nodes - set(template_owner_counts))
    multiply_owned_templates = sum(
        1 for count in template_owner_counts.values() if count != 1
    )

    return {
        "label": label,
        "path": str(path),
        "sha256": sha256_file(path),
        "json_nodes": len(names),
        "node_schema_width": node_width,
        "edge_schema_width": edge_width,
        "json_strict": False,
        "has_is_shared_field": "is_shared" in node_fields,
        "function_template_aliases": template_aliases,
        "class_literal_aliases": class_literal_aliases,
        "class_literal_count": class_literal_count,
        "function_template_count": len(template_nodes),
        "function_template_size_histogram": dict(sorted(template_size_histogram.items())),
        "function_template_shallow_bytes": sum(
            self_sizes[index] for index in template_nodes
        ),
        "owned_template_count": len(template_owner_counts),
        "unowned_template_count": unowned_templates,
        "multiply_owned_template_count": multiply_owned_templates,
        "classes_with_templates": len(templates_per_class),
        "templates_per_class_histogram": dict(
            sorted(Counter(templates_per_class).items())
        ),
        "eligible_min_templates_per_class": MIN_TEMPLATES_PER_CLASS,
        "eligible_class_count": eligible_classes,
        "eligible_template_count": eligible_templates,
        "excluded_single_template_count": sum(
            count for count in templates_per_class
            if count < MIN_TEMPLATES_PER_CLASS
        ),
        "eligible_current_bytes": eligible_current_bytes,
        "conditional_recipe_bytes": recipe_bytes,
        "conditional_net_shallow_bytes": conditional_net_bytes,
        "conditional_net_shallow_mib": conditional_net_bytes / MIB,
        "evidence_grade": "conditional_net_complete_ownership",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot",
        action="append",
        nargs=2,
        metavar=("LABEL", "PATH"),
        required=True,
        help="Snapshot label and path; may be repeated.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()

    samples = [
        analyze_snapshot(Path(path), label)
        for label, path in args.snapshot
    ]
    output = {
        "schema_version": 1,
        "source_revision": args.revision,
        "model": {
            "function_template_size": FUNCTION_TEMPLATE_SIZE,
            "tagged_array_header_size": TAGGED_ARRAY_HEADER_SIZE,
            "recipe_slots_per_template": RECIPE_SLOTS_PER_TEMPLATE,
            "tagged_slot_size": TAGGED_SLOT_SIZE,
            "class_literal_growth": CLASS_LITERAL_GROWTH,
            "minimum_templates_per_converted_class": MIN_TEMPLATES_PER_CLASS,
            "recipe_slots": ["Module", "Length(Smi)", "RawProfileTypeInfoCell"],
            "literal_slot_replacement": "FunctionTemplate -> Method",
            "eligible_current_formula": "40 * N",
            "recipe_cost_formula": "24 * N + 24 * C",
            "conditional_net_formula": "16 * N - 24 * C",
            "scope_limit": (
                "Translated inputs do not expose heap-domain metadata. The model "
                "covers both LocalHeap and SharedHeap using equal-sized, domain-local "
                "recipe arrays; it does not model cross-domain sharing."
            ),
        },
        "samples": samples,
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
