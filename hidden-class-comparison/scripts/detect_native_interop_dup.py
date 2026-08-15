#!/usr/bin/env python3
"""
detect_native_interop_dup.py
============================
Detect over-allocated native interop JSFunction closures in ArkTS heap snapshots.

Groups closures that share a single native Method stub, then classifies each by
retention pattern:

  A  anonymous accessor bindings (getter/setter)
  B  named, prototype-held, class HAS live instances (legitimate, not reclaimable)
  C  named, prototype-held, class has ZERO live instances (lazy-binding opportunity)
  D  named, non-prototype held (check for per-instance duplication)

Usage:
    python detect_native_interop_dup.py [--json] [--threshold N] *.heapsnapshot

Output:
    Per-app bucketed statistics and an aggregate summary.
    With --json, output machine-readable JSON to stdout.
"""
import json as _json
import sys
import os
import argparse
from collections import defaultdict, Counter

__version__ = "1.0.0"
M = 1048576


def load_snapshot(path):
    """Parse heapsnapshot and return graph accessors."""
    d = _json.loads(open(path, encoding="utf-8", errors="replace").read(), strict=False)
    m = d["snapshot"]["meta"]
    nf = m["node_fields"]; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = m["edge_fields"]; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    et = m["edge_types"][0]; nt = m["node_types"][0]
    nodes = d["nodes"]; edges = d["edges"]; strs = d["strings"]
    n = len(nodes) // st

    # prefix-sum edge starts
    starts = [0] * (n + 1); a = 0
    for i in range(n):
        starts[i] = a; a += nodes[i * st + fi["edge_count"]]
    starts[n] = a

    return dict(
        nodes=nodes, edges=edges, strs=strs, n=n,
        st=st, fi=fi, es=es, efi=efi, et=et, nt=nt, starts=starts
    )


def analyze(path, threshold=1000):
    """Analyze one snapshot. Returns a result dict."""
    app = os.path.basename(path).replace(".heapsnapshot", "")
    g = load_snapshot(path)
    nodes, edges, strs, n = g["nodes"], g["edges"], g["strs"], g["n"]
    st, fi, es, efi = g["st"], g["fi"], g["es"], g["efi"]
    et, nt, starts = g["et"], g["nt"], g["starts"]

    name_of = lambda i: strs[nodes[i * st + fi["name"]]]
    size_of = lambda i: nodes[i * st + fi["self_size"]]
    type_of = lambda i: nt[nodes[i * st + fi["type"]]]

    def out_edges(i):
        """Yield (edge_type, label_or_index, target_index) for node i."""
        ec = nodes[i * st + fi["edge_count"]]
        b = starts[i] * es
        for k in range(ec):
            o = b + k * es
            ety = et[edges[o + efi["type"]]]
            raw = edges[o + efi["name_or_index"]]
            label = strs[raw] if ety != "element" else None
            yield ety, label, edges[o + efi["to_node"]] // st

    # ---- pass 1: find closures grouped by shared native Method stub ----
    # A native interop stub is a Method referenced by a large number of closures.
    method_users = defaultdict(list)
    for i in range(n):
        if type_of(i) != "closure":
            continue
        for _, label, to in out_edges(i):
            if label == "Method":
                method_users[to].append(i)
                break

    shared_methods = {mi: us for mi, us in method_users.items() if len(us) >= threshold}
    if not shared_methods:
        return dict(app=app, total=0, total_mib=0.0, buckets={}, shared_methods=0)

    target = set()
    for us in shared_methods.values():
        target.update(us)

    # ---- pass 2: reverse edges into target closures; find prototype objects ----
    # `proto_objs` = nodes reachable as the prototype of some hclass
    proto_objs = set()
    incoming = defaultdict(list)   # closure -> [(label, holder)]
    hclass_protos = defaultdict(list)  # proto_obj -> [hclass...]
    # host_of: Properties-array node -> the js_object that owns it.
    # Used in bucket-D grouping to avoid keying on the generic array hclass
    # instead of the actual host object's hclass.
    host_of = {}
    for i in range(n):
        for ety, label, to in out_edges(i):
            if label in ("Proto", "ProtoOrHClass"):
                proto_objs.add(to)
                hclass_protos[to].append(i)
            if to in target:
                incoming[to].append((label, i))
            if label == "Properties":
                host_of[to] = i

    # instance count per hclass: how many nodes declare `hclass -> h`
    hclass_instances = Counter()
    for i in range(n):
        for _, label, to in out_edges(i):
            if label == "hclass":
                hclass_instances[to] += 1

    # ---- pass 3: classify ----
    buckets = {k: dict(n=0, bytes=0) for k in "ABCD"}
    d_combo = Counter()          # (own_name, holder_hclass) -> count
    a_holders = Counter()
    c_protos = set()

    for ci in sorted(target):
        sz = size_of(ci)
        # own `name`: the first string-valued InlineProperty
        own = None
        for ety, label, to in out_edges(ci):
            if label == "InlineProperty" and type_of(to) == "string":
                s = name_of(to)
                if s:
                    own = s
                    break

        holders = incoming.get(ci, [])
        if own is None:
            buckets["A"]["n"] += 1; buckets["A"]["bytes"] += sz
            for label, h in holders:
                a_holders[f"{label}<-{name_of(h)}"] += 1
            continue

        # is it held by a prototype object?
        proto_holder = None
        for label, h in holders:
            if h in proto_objs and label in ("InlineProperty", "Getter", "Setter"):
                proto_holder = h
                break

        if proto_holder is not None:
            # does any hclass whose proto is this object have live instances?
            live = any(hclass_instances.get(h, 0) > 0
                       for h in hclass_protos.get(proto_holder, ()))
            key = "B" if live else "C"
            buckets[key]["n"] += 1; buckets[key]["bytes"] += sz
            if key == "C":
                c_protos.add(proto_holder)
        else:
            buckets["D"]["n"] += 1; buckets["D"]["bytes"] += sz
            hh = None
            for label, h in holders:
                # Unwrap Properties array: when a closure is stored in a tagged_array
                # Properties store, h's hclass is a generic array hclass shared by
                # every Properties array in the snapshot, which collapses closures from
                # many different host classes into one d_combo bucket.  Walk up one hop
                # to the actual host js_object so the key reflects the host's shape.
                host = host_of.get(h, h)
                for _, l2, t2 in out_edges(host):
                    if l2 == "hclass":
                        hh = t2
                        break
                break
            d_combo[(own, hh)] += 1

    # duplication within bucket D: copies beyond 1 per (name, holder-hclass)
    d_redundant = sum(c - 1 for c in d_combo.values() if c > 1)
    avg_d = buckets["D"]["bytes"] // max(1, buckets["D"]["n"])

    total_n = sum(b["n"] for b in buckets.values())
    total_b = sum(b["bytes"] for b in buckets.values())

    return dict(
        app=app, total=total_n, total_mib=total_b / M,
        shared_methods=len(shared_methods),
        buckets={k: dict(n=v["n"], mib=v["bytes"] / M) for k, v in buckets.items()},
        d_redundant_n=d_redundant, d_redundant_mib=d_redundant * avg_d / M,
        c_protos=len(c_protos),
        a_top_holders=a_holders.most_common(3),
    )


def report_text(results):
    for r in results:
        if not r["total"]:
            print(f"=== {r['app']} === no shared-Method closure group above threshold")
            continue
        b = r["buckets"]
        print(f"=== {r['app']} === n={r['total']} {r['total_mib']:.2f} MiB  "
              f"sharedMethodStubs={r['shared_methods']}")
        print(f"   A anonymous accessor      n={b['A']['n']:7d} {b['A']['mib']:7.2f} MiB  "
              f"top={r['a_top_holders']}")
        print(f"   B named proto, live cls   n={b['B']['n']:7d} {b['B']['mib']:7.2f} MiB  (legitimate)")
        print(f"   C named proto, 0-instance n={b['C']['n']:7d} {b['C']['mib']:7.2f} MiB  "
              f"protos={r['c_protos']}   <== lazy-binding candidate")
        print(f"   D named non-proto         n={b['D']['n']:7d} {b['D']['mib']:7.2f} MiB  "
              f"redundant={r['d_redundant_n']} {r['d_redundant_mib']:.2f} MiB")

    print("\n=== SUMMARY ===")
    agg = Counter(); aggn = Counter()
    for r in results:
        for k, v in r.get("buckets", {}).items():
            agg[k] += v["mib"]; aggn[k] += v["n"]
        agg["dup"] += r.get("d_redundant_mib", 0.0)
        aggn["dup"] += r.get("d_redundant_n", 0)
        if r["total"]:
            b = r["buckets"]
            print(f"  {r['app']:<18} n={r['total']:7d} {r['total_mib']:7.2f}MiB | "
                  f"A={b['A']['mib']:6.2f} B={b['B']['mib']:5.2f} "
                  f"C={b['C']['mib']:6.2f} D={b['D']['mib']:5.2f} "
                  f"dup={r['d_redundant_mib']:5.2f}")
    print(f"  TOTAL  n={sum(r['total'] for r in results)}  "
          f"{sum(r['total_mib'] for r in results):.2f} MiB")
    print(f"    A anonymous accessor   {agg['A']:8.2f} MiB n={aggn['A']}")
    print(f"    B named proto live     {agg['B']:8.2f} MiB n={aggn['B']}  (not reclaimable)")
    print(f"    C named proto 0-inst   {agg['C']:8.2f} MiB n={aggn['C']}  <== lazy binding")
    print(f"    D named non-proto      {agg['D']:8.2f} MiB n={aggn['D']}")
    print(f"      of which redundant   {agg['dup']:8.2f} MiB n={aggn['dup']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshots", nargs="+", help=".heapsnapshot files")
    ap.add_argument("--threshold", type=int, default=1000,
                    help="min closures sharing one Method to treat it as a native stub "
                         "(default 1000)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    results = []
    for p in args.snapshots:
        if not os.path.exists(p):
            print(f"skip (missing): {p}", file=sys.stderr)
            continue
        try:
            results.append(analyze(p, args.threshold))
        except Exception as e:  # keep going across a batch
            print(f"error on {p}: {e}", file=sys.stderr)

    if not results:
        return 1
    if args.json:
        print(_json.dumps(results, indent=2, ensure_ascii=False))
    else:
        report_text(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
