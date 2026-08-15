#!/usr/bin/env python3
"""
class_copy_census.py
====================
For every zero-instance native class prototype in a snapshot, report how many
copies exist, how many distinct global_env (module-resolution context) they map
to, and the nearest retaining JS file.

copies > envs  ==>  the class registration runs more than once per context,
                    which is an application-side defect fixable with an
                    idempotence guard (no VM change needed).
copies == envs ==>  one registration per context; the lever is lazy import so
                    contexts that never use the class never materialize it.

Usage:
    python class_copy_census.py app.heapsnapshot [--min-copies 2] [--json out]
"""
import json as _json
import sys
import os
import argparse
import collections

M = 1048576


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--min-copies", type=int, default=2)
    ap.add_argument("--threshold", type=int, default=1000)
    ap.add_argument("--json")
    a = ap.parse_args()

    d = _json.loads(open(a.snapshot, encoding="utf-8", errors="replace").read(),
                    strict=False)
    meta = d["snapshot"]["meta"]
    nf, ef = meta["node_fields"], meta["edge_fields"]
    st, es = len(nf), len(ef)
    fi = {x: i for i, x in enumerate(nf)}
    efi = {x: i for i, x in enumerate(ef)}
    et, nt = meta["edge_types"][0], meta["node_types"][0]
    nodes, edges, strs = d["nodes"], d["edges"], d["strings"]
    n = len(nodes) // st
    starts = [0] * (n + 1)
    acc = 0
    for i in range(n):
        starts[i] = acc
        acc += nodes[i * st + fi["edge_count"]]
    starts[n] = acc

    name = lambda i: strs[nodes[i * st + fi["name"]]]
    size = lambda i: nodes[i * st + fi["self_size"]]
    typ = lambda i: nt[nodes[i * st + fi["type"]]]

    def out(i):
        ec = nodes[i * st + fi["edge_count"]]
        b = starts[i] * es
        for k in range(ec):
            o = b + k * es
            e = et[edges[o + efi["type"]]]
            raw = edges[o + efi["name_or_index"]]
            lb = strs[raw] if e != "element" else raw
            yield lb, edges[o + efi["to_node"]] // st

    # native interop closures: many closures share one native Method stub
    mu = collections.defaultdict(list)
    for i in range(n):
        if typ(i) != "closure":
            continue
        for lb, to in out(i):
            if lb == "Method":
                mu[to].append(i)
                break
    target = set()
    for v in mu.values():
        if len(v) >= a.threshold:
            target.update(v)

    proto_objs = set()
    hproto = collections.defaultdict(list)
    rev = collections.defaultdict(list)
    for i in range(n):
        for lb, to in out(i):
            if lb in ("Proto", "ProtoOrHClass"):
                proto_objs.add(to)
                hproto[to].append(i)
            rev[to].append((lb, i))
    hci = collections.Counter()
    for i in range(n):
        for lb, to in out(i):
            if lb == "hclass":
                hci[to] += 1

    def own(i):
        for lb, to in out(i):
            if lb == "InlineProperty" and typ(to) == "string" and name(to):
                return name(to)
        return None

    envs = [i for i in range(n) if name(i) in ("global_env", "GlobalEnv")]
    env_idx = {e: k for k, e in enumerate(envs)}

    def env_of(i, depth=12):
        """walk LexicalEnv/ParentEnv chain up to a global_env"""
        cur, seen = i, set()
        for _ in range(depth):
            if cur in env_idx:
                return env_idx[cur]
            nxt = None
            for lb, to in out(cur):
                if lb in ("LexicalEnv", "ParentEnv", "GlobalEnv"):
                    nxt = to
                    break
            if nxt is None or nxt in seen:
                return None
            seen.add(nxt)
            cur = nxt
        return None

    # zero-instance prototypes carrying native closures
    cproto = collections.defaultdict(list)
    for ci in target:
        if own(ci) is None:
            continue
        ph = None
        for lb, h in rev[ci]:
            if h in proto_objs and lb in ("InlineProperty", "Getter", "Setter"):
                ph = h
                break
        if ph is None or any(hci.get(h, 0) > 0 for h in hproto.get(ph, ())):
            continue
        cproto[ph].append(ci)

    def retainer_file(node, depth=7):
        seen = {node}
        frontier = [node]
        for _ in range(depth):
            nxt = []
            for h in frontier:
                for lb, p in rev.get(h, ()):
                    if p in seen:
                        continue
                    seen.add(p)
                    s = name(p)
                    if "/src/main/" in s and "#" in s:
                        return s
                    if typ(p) == "handle" and "GlobalHandleRoot" in s:
                        return "GlobalHandleRoot(native napi_create_reference)"
                    nxt.append(p)
            frontier = nxt
        return ""

    agg = collections.defaultdict(
        lambda: dict(protos=0, closures=0, b=0, methods=0, envs=set(), files=set()))
    for p, cl in cproto.items():
        cname, ctor = None, None
        for lb, h in rev.get(p, ()):
            if lb in ("ProtoOrHClass", "HomeObject") and typ(h) == "closure" and own(h):
                cname, ctor = own(h), h
                break
        key = cname or f"<proto#{p}>"
        e = agg[key]
        e["protos"] += 1
        e["closures"] += len(cl)
        e["b"] += sum(size(c) for c in cl)
        e["methods"] = max(e["methods"], len({own(c) for c in cl if own(c)} - {cname}))
        ev = env_of(ctor) if ctor is not None else None
        if ev is not None:
            e["envs"].add(ev)
        if len(e["files"]) < 3:
            f = retainer_file(ctor if ctor is not None else p)
            if f:
                e["files"].add(f)

    rows = []
    for k, e in agg.items():
        if e["protos"] < a.min_copies:
            continue
        ne = len(e["envs"]) or None
        rows.append(dict(cls=k, protos=e["protos"], envs=ne, methods=e["methods"],
                         closures=e["closures"], mib=e["b"] / M,
                         dup_mib=e["b"] / M * (e["protos"] - (ne or 1)) / e["protos"],
                         files=sorted(e["files"])))
    rows.sort(key=lambda r: -r["mib"])

    print(f"snapshot={os.path.basename(a.snapshot)} global_env={len(envs)} "
          f"zero-instance prototypes={len(cproto)} classes={len(agg)}")
    print(f"{'class':<38}{'protos':>7}{'envs':>6}{'meth':>6}{'MiB':>9}{'dupMiB':>9}  file")
    for r in rows[:60]:
        print(f"{r['cls'][:37]:<38}{r['protos']:>7}{str(r['envs']):>6}"
              f"{r['methods']:>6}{r['mib']:>9.4f}{r['dup_mib']:>9.4f}  "
              f"{(r['files'][0][-70:] if r['files'] else '')}")
    over = [r for r in rows if r["envs"] and r["protos"] > r["envs"]]
    print(f"\nclasses with protos > envs (per-context duplicate registration): "
          f"{len(over)}, redundant {sum(r['dup_mib'] for r in over):.3f} MiB")
    if a.json:
        open(a.json, "w", encoding="utf-8").write(
            _json.dumps(dict(envs=len(envs), rows=rows), indent=2, ensure_ascii=False))
        print(f"written {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
