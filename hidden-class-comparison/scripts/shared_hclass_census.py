#!/usr/bin/env python3
"""Shared-heap HClass share of the JSHClass population.

An HClass is counted as shared when at least one of its instances is a shared
JSType.  Shared JSTypes are allocated through SharedObjectFactory
(shared_object_factory.cpp:120,131,149 -> sHeap_->AllocateNonMovableOrHugeObject),
so their describing HClass lives in the shared heap - the only heap the existing
ephemeron visitors exclude (full_gc-inl.h:391 et al).
"""
import json, sys, os
from collections import defaultdict

def census(path):
    d = json.loads(open(path, encoding='utf-8', errors='replace').read(), strict=False)
    s = d['snapshot']; m = s['meta']
    nf = m['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = m['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    et = m['edge_types'][0]
    nodes = d['nodes']; edges = d['edges']; strs = d['strings']
    n = len(nodes) // st

    starts = [0]*(n+1); acc = 0
    for i in range(n):
        starts[i] = acc; acc += nodes[i*st+fi['edge_count']]

    name = lambda i: strs[nodes[i*st+fi['name']]]
    size = lambda i: nodes[i*st+fi['self_size']]

    n_hclass = 0; sz_hclass = 0
    hclass_ids = set()
    for i in range(n):
        if name(i) == 'hclass':
            n_hclass += 1; sz_hclass += size(i); hclass_ids.add(i)

    # instance -> its hclass
    shared_hc = set(); n_shared_inst = 0
    for i in range(n):
        nm = name(i)
        if not (nm.startswith('js_shared_') or nm.startswith('shared_')):
            continue
        n_shared_inst += 1
        ec = nodes[i*st+fi['edge_count']]; b = starts[i]*es
        for k in range(ec):
            o = b + k*es
            if et[edges[o+efi['type']]] == 'element':
                continue
            if strs[edges[o+efi['name_or_index']]] == 'hclass':
                shared_hc.add(edges[o+efi['to_node']] // st)
    return {'n_hclass': n_hclass, 'sz_hclass': sz_hclass,
            'n_shared_hclass': len(shared_hc & hclass_ids),
            'n_shared_inst': n_shared_inst}

if __name__ == '__main__':
    out = {}
    for p in sys.argv[1:]:
        app = os.path.basename(p).replace('.heapsnapshot', '')
        c = census(p); out[app] = c
        print(f"{app}: hclass={c['n_hclass']} shared_hclass={c['n_shared_hclass']} "
              f"shared_inst={c['n_shared_inst']}", flush=True)
    print("---JSON---"); print(json.dumps(out))
