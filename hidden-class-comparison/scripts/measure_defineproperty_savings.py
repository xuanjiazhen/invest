#!/usr/bin/env python3
"""Savings from ONLY: native binding via defineProperty on prototype
instead of per-instance `this.m = napi_bind()`.

Grouping key = (owner_hclass, edge_label, slot_ordinal).
Inline property NAMES are absent from the snapshot, but for objects that share
an hclass, the k-th InlineProperty edge is always the same property. So the
ordinal is an exact substitute for the name -- no over/under-grouping.

A group of size N  ==  N same-shaped instances each holding their own stub for
the same property  ==>  promoting to the prototype keeps 1, frees N-1.
"""
import json, sys, os, collections

SLOT = 8

def analyze(path):
    d = json.loads(open(path, encoding='utf-8', errors='replace').read(), strict=False)
    m = d['snapshot']['meta']
    nf = m['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = m['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    nt = m['node_types'][0]; et = m['edge_types'][0]
    nodes, edges, strs = d['nodes'], d['edges'], d['strings']
    n = len(nodes) // st
    starts = [0] * (n + 1); a = 0
    for i in range(n):
        starts[i] = a; a += nodes[i * st + fi['edge_count']]
    starts[n] = a
    nm = lambda i: strs[nodes[i * st + fi['name']]]
    ty = lambda i: nt[nodes[i * st + fi['type']]]
    sz = lambda i: nodes[i * st + fi['self_size']]

    def out(i):
        """yield (edge_type, label, target, ordinal_within_same_label)"""
        ec = nodes[i * st + fi['edge_count']]; b = starts[i] * es
        seen = collections.Counter()
        for k in range(ec):
            o = b + k * es
            e = et[edges[o + efi['type']]]
            raw = edges[o + efi['name_or_index']]
            lb = raw if e == 'element' else strs[raw]
            seen[lb] += 1
            yield e, lb, edges[o + efi['to_node']] // st, seen[lb] - 1

    rev = collections.defaultdict(list)
    hclass_of = {}; protos = set()
    for h in range(n):
        for e, lb, to, ordi in out(h):
            rev[to].append((h, lb, ordi))
            if e != 'element':
                if lb == 'hclass':
                    hclass_of[h] = to
                elif lb in ('Proto', 'ProtoOrHClass', 'prototype', '__proto__'):
                    protos.add(to)

    OBJ = ('object', 'js_object')
    ARR = ('tagged_array', 'array', 'mutant_tagged_array', 'object_array')

    def owner_of(c):
        """resolve to (object, key) hopping through Properties array / accessor"""
        for h, lb, ordi in rev.get(c, []):
            t = ty(h)
            if t in OBJ:
                return h, f'{lb}#{ordi}'
            if t in ARR:
                for hh, lb2, o2 in rev.get(h, []):
                    if ty(hh) in OBJ:
                        return hh, f'{lb2}[{lb}]'
            if t == 'accessor_data':
                for hh, lb2, o2 in rev.get(h, []):
                    if ty(hh) in OBJ:
                        return hh, f'acc:{lb2}#{o2}'
                    if ty(hh) in ARR:
                        for h3, lb3, o3 in rev.get(hh, []):
                            if ty(h3) in OBJ:
                                return h3, f'acc:{lb3}[{lb2}]'
        return None, None

    has_src = lambda s: '#' in s and '(line:' in s
    stubs = [i for i in range(n) if ty(i) == 'closure' and not has_src(nm(i))]

    groups = collections.defaultdict(list)
    b_proto = n_proto = b_unres = n_unres = 0
    for c in stubs:
        o, key = owner_of(c)
        if o is None:
            b_unres += sz(c); n_unres += 1; continue
        if o in protos:
            b_proto += sz(c); n_proto += 1; continue
        groups[(hclass_of.get(o), key)].append(c)

    dup_bytes = dup_n = 0
    detail = []
    for (hc, key), cs in groups.items():
        if len(cs) < 2: continue
        db = sum(sz(x) for x in cs[1:])
        dup_bytes += db; dup_n += len(cs) - 1
        detail.append((db, len(cs), key, nm(cs[0])))
    detail.sort(reverse=True)
    single = sum(sz(cs[0]) for cs in groups.values() if len(cs) == 1)

    return dict(app=os.path.basename(path).replace('.heapsnapshot', ''),
                stub_n=len(stubs), stub_mib=sum(sz(i) for i in stubs) / 2**20,
                proto_n=n_proto, proto_mib=b_proto / 2**20,
                unres_n=n_unres, unres_mib=b_unres / 2**20,
                groups=len(groups), single_mib=single / 2**20,
                dup_n=dup_n, dup_mib=dup_bytes / 2**20,
                slot_mib=dup_n * SLOT / 2**20, detail=detail[:20])

def show(r):
    print(f"=== {r['app']} ===")
    print(f"  native stubs total     : n={r['stub_n']:7d}  {r['stub_mib']:7.2f} MiB")
    print(f"    already on prototype : n={r['proto_n']:7d}  {r['proto_mib']:7.2f} MiB   [not fixable]")
    print(f"    unresolved owner     : n={r['unres_n']:7d}  {r['unres_mib']:7.2f} MiB")
    print(f"    per-instance, 1 copy : {r['single_mib']:7.2f} MiB   [nothing to fold]")
    print(f"  groups={r['groups']}")
    print(f"  >> FIXABLE: redundant copies n={r['dup_n']}")
    print(f"     closure bytes measured : {r['dup_mib']:7.3f} MiB")
    print(f"     slot bytes  modeled 8B : {r['slot_mib']:7.3f} MiB")
    print(f"     TOTAL                  : {r['dup_mib']+r['slot_mib']:7.3f} MiB"
          f"  ({(r['dup_mib']+r['slot_mib'])/max(r['stub_mib'],1e-9)*100:.1f}% of stubs)")
    for db, cnt, key, name in r['detail'][:12]:
        print(f"       {db/1024:8.1f}KiB x{cnt:6d}  key={key[:26]:26s} {name[:24]}")

if __name__ == '__main__':
    out = []
    for p in sys.argv[1:]:
        r = analyze(p); show(r); print(); out.append(r)
    if len(out) > 1:
        print("=== TOTAL ACROSS APPS ===")
        print(f"  stubs           : {sum(r['stub_mib'] for r in out):8.2f} MiB")
        print(f"  fixable closure : {sum(r['dup_mib'] for r in out):8.3f} MiB")
        print(f"  fixable slots   : {sum(r['slot_mib'] for r in out):8.3f} MiB")
        print(f"  FIXABLE TOTAL   : {sum(r['dup_mib']+r['slot_mib'] for r in out):8.3f} MiB")
