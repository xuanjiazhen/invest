#!/usr/bin/env python3
"""
inspect_class_copies.py
-----------------------
For a given class name, print every prototype copy found in the snapshot:
  - copy index, global_env node id
  - method-name set size
  - first 6 method names
  - retainer chain up to the nearest named artifact (file or GlobalHandleRoot)

Usage:
    python scripts/inspect_class_copies.py app.heapsnapshot ClassName [ClassName2 ...]
"""
import json, sys, collections, re

if len(sys.argv) < 3:
    print("Usage: inspect_class_copies.py <snapshot> <ClassName> [...]")
    sys.exit(1)

P = sys.argv[1]
WANT = set(sys.argv[2:])

print(f"Loading {P} ...", file=sys.stderr)
S = json.load(open(P, encoding="utf-8", errors="replace"), strict=False)
sn = S["snapshot"]
NF = sn["meta"]["node_fields"]; EF = sn["meta"]["edge_fields"]
NT = sn["meta"]["node_types"][0]; ET = sn["meta"]["edge_types"][0]
ns, es, strs = S["nodes"], S["edges"], S["strings"]
nst, est = len(NF), len(EF); n = sn["node_count"]
iT, iN, iE, iSz = (NF.index("type"), NF.index("name"),
                   NF.index("edge_count"), NF.index("self_size"))
eT, eN, eTo = EF.index("type"), EF.index("name_or_index"), EF.index("to_node")
off = [0]*(n+1)
for i in range(n): off[i+1] = off[i] + ns[i*nst+iE]
def ty(i): return NT[ns[i*nst+iT]]
def nm(i): return strs[ns[i*nst+iN]]
def szf(i): return ns[i*nst+iSz]
def out(i):
    for k in range(off[i], off[i+1]):
        b = k*est; t = ET[es[b+eT]]
        lb = strs[es[b+eN]] if t in ("property","shortcut","internal") else es[b+eN]
        yield t, lb, es[b+eTo]//nst

print("Building index ...", file=sys.stderr)
rev = collections.defaultdict(list)
proto_objs = set(); hproto = collections.defaultdict(list)
for i in range(n):
    for _, lb, to in out(i):
        rev[to].append((lb, i))
        if lb in ("Proto","ProtoOrHClass"): proto_objs.add(to); hproto[to].append(i)
hci = collections.Counter()
for i in range(n):
    for _, lb, to in out(i):
        if lb == "hclass": hci[to] += 1

def own(i):
    for _, lb, to in out(i):
        if lb == "InlineProperty" and ty(to)=="string" and nm(to): return nm(to)
    return None

def envof(i):
    for _, lb, to in out(i):
        if lb in ("LexicalEnv","GlobalEnv"): return to
    return None

# find prototype copies
cproto = collections.defaultdict(list)   # cname -> [(proto_node, ctor_node)]
for i in range(n):
    if ty(i) != "closure" or own(i) is None: continue
    for lb, h in rev[i]:
        if h in proto_objs and lb in ("InlineProperty","Getter","Setter"):
            if any(hci.get(x,0) > 0 for x in hproto.get(h,())):
                break
            # find cname from proto retainers
            for lb2, h2 in rev.get(h, []):
                if lb2 in ("ProtoOrHClass","HomeObject") and ty(h2)=="closure":
                    cn = own(h2)
                    if cn and cn in WANT:
                        cproto[cn].append((h, h2))  # (proto, ctor)
            break

FILEK = ("/src/main/",)
def filish(s):
    return bool(s) and "/src/main/" in s and "#" in s

def retainer_chain(node, depth=6):
    seen = {node}; frontier = [node]
    for _ in range(depth):
        nxt = []
        for h in frontier:
            for lb, p in rev.get(h, []):
                if p in seen: continue
                seen.add(p)
                s = nm(p)
                if ty(p) == "handle" and "GlobalHandleRoot" in s:
                    return f"→ GlobalHandleRoot: {s}"
                if filish(s):
                    return f"→ JS file: {s[:140]}"
                nxt.append(p)
        frontier = nxt
    return "→ (depth limit)"

M = 1048576
for cname in sorted(WANT):
    copies = cproto.get(cname, [])
    if not copies:
        print(f"\n=== {cname}: NOT FOUND in snapshot ===")
        continue
    # deduplicate by proto node
    seen_p = {}
    for p, ctor in copies:
        seen_p[p] = ctor
    copies = list(seen_p.items())

    # collect method sets per proto
    proto_methods = {}
    for p, ctor in copies:
        mset = set()
        for _, lb, to in out(p):
            if lb in ("InlineProperty","Getter","Setter") and ty(to)=="closure":
                o = own(to)
                if o and o != cname: mset.add(o)
        proto_methods[p] = mset

    envs = collections.Counter(envof(ctor) for _, ctor in copies)
    all_methods = set().union(*proto_methods.values())
    total_mib = sum(sum(szf(c) for c in
                       [ci for ci in range(n)
                        if ty(ci)=="closure" and own(ci) and
                        any(h == p for _, h in rev.get(ci, [])
                            if h in proto_objs)])
                    for p, _ in copies) / M

    print(f"\n{'='*70}")
    print(f"Class: {cname}")
    print(f"  prototype copies : {len(copies)}")
    print(f"  distinct envs    : {len(envs)}  (top count: {envs.most_common(1)[0][1]})")
    print(f"  union method set : {len(all_methods)}  "
          f"first5={sorted(all_methods)[:5]}")
    print()
    for idx, (p, ctor) in enumerate(sorted(copies,
                                           key=lambda x: envof(x[1]) or 0)):
        env = envof(ctor)
        ms = proto_methods[p]
        chain = retainer_chain(ctor)
        print(f"  copy #{idx+1:2d}  proto={p}  env={env}  |methods|={len(ms)}")
        print(f"          {chain}")
