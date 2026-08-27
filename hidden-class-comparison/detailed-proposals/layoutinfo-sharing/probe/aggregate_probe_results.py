#!/usr/bin/env python3
"""Phase 3: aggregate layout_probe_out.json call stacks into source method rankings.

Usage:
    python aggregate_probe_results.py \\
        --probe   layout_probe_out.json \\
        --whitelist evidence/meituanzhongbao-layout-whitelist.json \\
        --disasm  /path/to/ark_disasm          # optional; enables bytecode→line fallback
        --output  top20_source_methods.txt

Output format (one line per method):
    rank  total_bytes_attributed  abc_record  method_name  line_or_offset

Frame string format emitted by layout_probe.cpp:
    "<record>#<method>@<bytecodeOffset>"
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_probe(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_whitelist(path: Path) -> dict[str, int]:
    """Return fingerprint → total_bytes from the whitelist."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    result: dict[str, int] = {}
    for entry in data.get("entries", []):
        # Reconstruct the fingerprint string as layout_probe.cpp does:
        # capacity:key1:attr1:key2:attr2:...
        parts = [str(entry["capacity"])]
        for slot in entry.get("slots", []):
            parts.append(str(slot.get("key") or ""))
            parts.append(str(slot.get("attr", 0)))
        result[":".join(parts)] = entry["total_bytes"]
    return result


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------

_FRAME_RE = re.compile(r"^(?P<record>.+)#(?P<method>[^@]+)@(?P<offset>\d+)$")


def parse_frame(frame: str) -> Optional[tuple[str, str, int]]:
    """Return (record, method, offset) or None if unparseable."""
    m = _FRAME_RE.match(frame)
    if not m:
        return None
    return m.group("record"), m.group("method"), int(m.group("offset"))


# ---------------------------------------------------------------------------
# Line number resolution via ark_disasm
# ---------------------------------------------------------------------------

_disasm_cache: dict[str, dict[tuple[str, int], int]] = {}


def _run_disasm(abc_path: str, disasm_bin: str) -> dict[tuple[str, int], int]:
    """Run ark_disasm --debug-info on abc_path; return (method, offset) → line."""
    if abc_path in _disasm_cache:
        return _disasm_cache[abc_path]

    result: dict[tuple[str, int], int] = {}
    try:
        proc = subprocess.run(
            [disasm_bin, "--debug-info", abc_path],
            capture_output=True, text=True, timeout=60
        )
        lines = proc.stdout.splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  [warn] ark_disasm failed for {abc_path}: {e}", file=sys.stderr)
        _disasm_cache[abc_path] = result
        return result

    current_method: Optional[str] = None
    # Disassembly lines of interest:
    #   .function <rettype> <record>.<method>(...)  ← method header
    #   v0 = mov ...  : <offset>                    ← instruction with offset
    #   .line <lineno>                               ← line directive
    pending_offset: Optional[int] = None
    method_re = re.compile(r"\.function\s+\S+\s+(\S+)\(")
    line_re   = re.compile(r"\.line\s+(\d+)")
    offset_re = re.compile(r"#(\d+)")  # offset annotations vary; try a generic match

    for raw in lines:
        stripped = raw.strip()
        m = method_re.search(stripped)
        if m:
            current_method = m.group(1).split(".")[-1]  # strip record prefix
            pending_offset = None
            continue
        m = line_re.match(stripped)
        if m and current_method is not None:
            if pending_offset is not None:
                result[(current_method, pending_offset)] = int(m.group(1))
            continue
        m = offset_re.search(stripped)
        if m:
            pending_offset = int(m.group(1))

    _disasm_cache[abc_path] = result
    return result


def resolve_line(record: str, method: str, offset: int,
                 disasm_bin: Optional[str]) -> Optional[int]:
    if disasm_bin is None:
        return None
    table = _run_disasm(record, disasm_bin)
    return table.get((method, offset))


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(probe_entries: list[dict],
              whitelist: dict[str, int],
              disasm_bin: Optional[str]) -> list[dict]:
    """Return list of {record, method, offset, total_bytes, line} sorted desc."""

    # method key → attributed bytes
    method_bytes: dict[tuple[str, str, int], int] = defaultdict(int)

    for entry in probe_entries:
        fingerprint = entry.get("fingerprint", "")
        bytes_for_fp = whitelist.get(fingerprint, 0)
        stacks = entry.get("stacks", [])
        if not stacks:
            continue
        # Attribute bytes equally across distinct caller frames in this fingerprint.
        # Use only the first (deepest-in-stack = direct caller) JS frame per stack.
        caller_frames: list[tuple[str, str, int]] = []
        for stack in stacks:
            for frame_str in stack:
                parsed = parse_frame(frame_str)
                if parsed:
                    caller_frames.append(parsed)
                    break  # first JS frame only
        if not caller_frames:
            continue
        per_frame = bytes_for_fp / len(caller_frames)
        for frame in caller_frames:
            method_bytes[frame] += int(per_frame)

    rows = []
    for (record, method, offset), total in method_bytes.items():
        line = resolve_line(record, method, offset, disasm_bin)
        rows.append({
            "record": record,
            "method": method,
            "offset": offset,
            "total_bytes": total,
            "line": line,
        })

    rows.sort(key=lambda r: r["total_bytes"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_results(rows: list[dict], out_path: Path, top_n: int = 20) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"{'rank':>4}  {'bytes':>12}  {'record':<50}  {'method':<40}  location\n")
        f.write("-" * 130 + "\n")
        for rank, row in enumerate(rows[:top_n], 1):
            loc = f"line {row['line']}" if row["line"] is not None else f"offset {row['offset']}"
            f.write(
                f"{rank:>4}  {row['total_bytes']:>12,}  "
                f"{row['record']:<50}  {row['method']:<40}  {loc}\n"
            )
    print(f"Wrote {min(len(rows), top_n)} entries to {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--probe",     required=True,  help="layout_probe_out.json")
    parser.add_argument("--whitelist", required=True,  help="*-layout-whitelist.json from Phase 1")
    parser.add_argument("--disasm",    default=None,   help="path to ark_disasm binary (optional)")
    parser.add_argument("--output",    default="top20_source_methods.txt")
    parser.add_argument("--top",       type=int, default=20, help="number of methods to emit")
    args = parser.parse_args()

    probe_path     = Path(args.probe)
    whitelist_path = Path(args.whitelist)
    out_path       = Path(args.output)

    if not probe_path.exists():
        sys.exit(f"probe file not found: {probe_path}")
    if not whitelist_path.exists():
        sys.exit(f"whitelist not found: {whitelist_path}")

    print(f"Loading probe results from {probe_path} ...")
    probe_entries = load_probe(probe_path)
    print(f"  {len(probe_entries)} fingerprint entries")

    print(f"Loading whitelist from {whitelist_path} ...")
    whitelist = load_whitelist(whitelist_path)
    print(f"  {len(whitelist)} fingerprints in whitelist")

    if args.disasm:
        print(f"Line resolution via ark_disasm: {args.disasm}")
    else:
        print("No --disasm provided; byte offsets will be used instead of line numbers")

    print("Aggregating ...")
    rows = aggregate(probe_entries, whitelist, args.disasm)
    print(f"  {len(rows)} distinct caller frames found")

    write_results(rows, out_path, top_n=args.top)


if __name__ == "__main__":
    main()
