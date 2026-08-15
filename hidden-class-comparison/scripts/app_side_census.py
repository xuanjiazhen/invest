#!/usr/bin/env python3
"""
app_side_census.py
==================
Single-app census of heap costs that application code can act on without any
VM change.  Complements `measure_lazy_binding_targets.py` (which sizes bucket C
only) by covering the remaining app-addressable populations:

  1. type/name breakdown of heap_self
  2. duplicate strings (identical content held by >1 string node)
  3. dictionary-mode objects (hclass degraded by dynamic keys)
  4. bucket D: native interop closures bound per-instance instead of on the
     prototype, grouped by the host object's own hclass
  5. NARROW codegen families (identical small method sets on many prototypes)
  6. module/context count (global_env nodes) and per-context duplication
  7. largest arrays and native pointers with their retaining edge
  8. HAR attribution: for a given set of nodes, walk reverse edges up to the
     nearest `<bundle>/<har>@<ver>/src/main/...#fn(line:N)` name

Usage:
    python app_side_census.py app.heapsnapshot [--json out.json] [--top N]
"""
import json as _json
import sys
import os
import argparse
import collections

M = 1048576


def load(path):
    d = _json.loads(open(path, encoding="utf-8", errors="replace").read(), strict=False)
    meta = d["snapshot"]["meta"]
    nf = meta["node_fields"]
    ef = meta["edge_fields"]
    st, es = len(nf), len(ef)
    fi = {x: i for i, x in enumerate(nf)}
    efi = {x: i for i, x in enumerate(ef)}
    nodes, edges, strs = d["nodes"], d["edges"], d["strings"]
    n = len(nodes) // st
    starts = [0] * (n + 1)
    a = 0
    for i in range(n):
        starts[i] = a
        a += nodes[i * st + fi["edge_count"]]
    starts[n] = a
    return dict(nodes=nodes, edges=edges, strs=strs, n=n, st=st, fi=fi, es=es,
                efi=efi, et=meta["edge_types"][0], nt=meta["node_types"][0],
                starts=starts)


def run(path, top=25):
    g = load(path)
    nodes, edges, strs, n = g["nodes"], g["edges"], g["strs"], g["n"]
    st, fi, es, efi = g["st"], g["fi"], g["es"], g["efi"]
    et, nt, starts = g["et"], g["nt"], g["starts"]

    name = lambda i: strs[nodes[i * st + fi["name"]]]
    size = lambda i: nodes[i * st + fi["self_size"]]
    typ = lambda i: nt[nodes[i * st + fi["type"]]]
    nat = lambda i: nodes[i * st + fi["native_size"]] if "native_size" in fi else 0

    def out(i):
        ec = nodes[i * st + fi["edge_count"]]
        b = starts[i] * es
        for k in range(ec):
            o = b + k * es
            e = et[edges[o + efi["type"]]]
            raw = edges[o + efi["name_or_index"]]
            lb = strs[raw] if e != "element" else raw
            yield e, lb, edges[o + efi["to_node"]] // st

    res = {"app": os.path.basename(path).replace(".heapsnapshot", ""), "nodes": n}

    # ---- 1. breakdown -----------------------------------------------------
    by_type = collections.Counter()
    by_type_n = collections.Counter()
    by_name = collections.Counter()
    by_name_n = collections.Counter()
    heap_self = 0
    native_total = 0
    for i in range(n):
        s = size(i)
        heap_self += s
        native_total += nat(i)
        by_type[typ(i)] += s
        by_type_n[typ(i)] += 1
        by_name[name(i)] += s
        by_name_n[name(i)] += 1
    res["heap_self_mib"] = heap_self / M
    res["native_size_mib"] = native_total / M
    res["by_type"] = [(k, v / M, by_type_n[k]) for k, v in by_type.most_common()]
    res["by_name"] = [(k, v / M, by_name_n[k]) for k, v in by_name.most_common(40)]

    # ---- 2. duplicate strings --------------------------------------------
    dup = collections.defaultdict(lambda: [0, 0])   # content -> [count, bytes]
    for i in range(n):
        if typ(i) == "string":
            e = dup[name(i)]
            e[0] += 1
            e[1] += size(i)
    dup_bytes = sum(v[1] - v[1] // v[0] for v in dup.values() if v[0] > 1)
    res["string_total_mib"] = sum(v[1] for v in dup.values()) / M
    res["string_dup_wasted_mib"] = dup_bytes / M
    res["string_dup_top"] = [
        (k[:90], v[0], v[1] / M)
        for k, v in sorted(dup.items(), key=lambda kv: -(kv[1][1] - kv[1][1] // kv[1][0]))[:top]
        if v[0] > 1
    ]

    # ---- 3. dictionary-mode ----------------------------------------------
    dict_nodes = [i for i in range(n) if name(i) == "tagged_dictionary"]
    res["dictionary"] = dict(count=len(dict_nodes),
                             mib=sum(size(i) for i in dict_nodes) / M)

    # reverse index (single pass, reused below)
    rev = collections.defaultdict(list)
    for i in range(n):
        for e, lb, to in out(i):
            rev[to].append((lb, i))

    dict_owner = collections.Counter()
    dict_owner_b = collections.Counter()
    for i in dict_nodes:
        for lb, h in rev.get(i, ()):
            dict_owner[f"{name(h)}.{lb}"] += 1
            dict_owner_b[f"{name(h)}.{lb}"] += size(i)
            break
    res["dictionary_owners"] = [(k, v, dict_owner_b[k] / M)
                                for k, v in dict_owner.most_common(top)]

    # ---- shared native Method stubs --------------------------------------
    mu = collections.defaultdict(list)
    for i in range(n):
        if typ(i) != "closure":
            continue
        for _, lb, to in out(i):
            if lb == "Method":
                mu[to].append(i)
                break
    native_closures = set()
    for v in mu.values():
        if len(v) >= 1000:
            native_closures.update(v)
    res["native_closures"] = dict(
        count=len(native_closures),
        mib=sum(size(i) for i in native_closures) / M)

    def own(i):
        for _, lb, to in out(i):
            if lb == "InlineProperty" and typ(to) == "string" and name(to):
                return name(to)
        return None

    proto_objs = set()
    for i in range(n):
        for _, lb, to in out(i):
            if lb in ("Proto", "ProtoOrHClass"):
                proto_objs.add(to)

    # ---- 4. bucket D: per-instance binding --------------------------------
    # host object -> its own hclass; group closures by (host hclass, method name)
    host_hclass = {}
    for i in range(n):
        for _, lb, to in out(i):
            if lb == "hclass":
                host_hclass[i] = to
                break

    per_inst = collections.defaultdict(lambda: [0, 0])   # (hc, mname) -> [n, bytes]
    for c in native_closures:
        mn = own(c)
        if mn is None:
            continue
        for lb, h in rev.get(c, ()):
            if h in proto_objs:
                break
            if lb in ("InlineProperty", "Getter", "Setter") and h in host_hclass:
                k = (host_hclass[h], mn)
                per_inst[k][0] += 1
                per_inst[k][1] += size(c)
                break
    red_b = sum(v[1] - v[1] // v[0] for v in per_inst.values() if v[0] > 1)
    top_red = sorted(((k, v) for k, v in per_inst.items() if v[0] > 1),
                     key=lambda kv: -(kv[1][1] - kv[1][1] // kv[1][0]))[:top]
    res["bucket_d"] = dict(
        redundant_mib=red_b / M,
        groups=len(per_inst),
        top=[(mn, v[0], (v[1] - v[1] // v[0]) / M) for (hc, mn), v in top_red])

    # ---- 5/6. contexts ----------------------------------------------------
    envs = [i for i in range(n) if name(i) in ("global_env", "GlobalEnv")]
    res["global_envs"] = len(envs)
    res["module_records"] = dict(
        count=by_name_n.get("source_text_module_record", 0),
        mib=by_name.get("source_text_module_record", 0) / M)

    # ---- 7. biggest arrays / native pointers ------------------------------
    big = sorted(range(n), key=lambda i: -size(i))[:top]
    res["biggest_nodes"] = [
        (name(i), typ(i), size(i) / M,
         [(lb, name(h)) for lb, h in rev.get(i, ())][:2])
        for i in big]

    npt = [i for i in range(n) if name(i) == "js_native_pointer"]
    res["native_pointers"] = dict(
        count=len(npt),
        zero=sum(1 for i in npt if nat(i) == 0),
        heap_mib=sum(size(i) for i in npt) / M,
        off_heap_mib=sum(nat(i) for i in npt) / M)

    # ---- 8. HAR attribution for closures ---------------------------------
    har = collections.Counter()
    for i in range(n):
        if typ(i) != "closure":
            continue
        nm = name(i)
        if "/src/main/" in nm and "@" in nm:
            har[nm.split("/src/main/")[0]] += size(i)
    res["har_closures"] = [(k[-90:], v / M) for k, v in har.most_common(top)]

    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    r = run(a.snapshot, a.top)
    txt = _json.dumps(r, indent=2, ensure_ascii=False)
    if a.json:
        open(a.json, "w", encoding="utf-8").write(txt)
        print(f"written: {a.json}")
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
