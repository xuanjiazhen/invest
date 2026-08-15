#!/usr/bin/env python3
"""Shared-heap HClass count, as a seed set plus its transition closure.

Seed: an HClass with at least one live shared-JSType instance.
Closure: JSHClass::Clone / CloneWithNewSizeAndType allocate the new HClass in the
shared heap iff the source is (js_hclass.cpp:234-238, 256-260), and transitions
are built by cloning, so every HClass reachable from a shared seed along
Transitions / Parent is also shared.  Reported as [seed, closure] = [lower, upper].
"""
import json, sys, os
from collections import deque

def census(path):
    d = json.loads(open(path, encoding='utf-8', errors='replace').read(), strict=False)
    m = d['snapshot']['meta']
    nf = m['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = m['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    et = m['edge_types'][0]
    nodes = d['nodes']; edges = d['edges']; strs = d['strings']
    n = len(nodes) // st
    starts = [0]*(n+1); a = 0
    for i in range(n):
        starts[i] = a; a += nodes[i*st+fi['edge_count']]
    nm = lambda i: strs[nodes[i*st+fi['name']]]

    def named(i):
        ec = nodes[i*st+fi['edge_count']]; b = starts[i]*es
        for k in range(ec):
            o = b + k*es
            if et[edges[o+efi['type']]] == 'element':
                continue
            yield strs[edges[o+efi['name_or_index']]], edges[o+efi['to_node']]//st

    hcl = {i for i in range(n) if nm(i) == 'hclass'}
    seed = set(); n_inst = 0
    for i in range(n):
        if not nm(i).startswith('js_shared_'):
            continue
        n_inst += 1
        for e, to in named(i):
            if e == 'hclass' and to in hcl:
                seed.add(to); break

    # transition closure, both directions
    adj = {}
    rev = {}
    for i in hcl:
        for e, to in named(i):
            if e in ('Transitions', 'Parent') and to in hcl:
                adj.setdefault(i, []).append(to)
                rev.setdefault(to, []).append(i)
    clo = set(seed); q = deque(seed)
    while q:
        u = q.popleft()
        for v in adj.get(u, ()) + rev.get(u, ()):
            if v not in clo:
                clo.add(v); q.append(v)
    return {'n_hclass': len(hcl), 'seed': len(seed), 'closure': len(clo),
            'shared_inst': n_inst}

if __name__ == '__main__':
    out = {}
    for p in sys.argv[1:]:
        app = os.path.basename(p).replace('.heapsnapshot', '')
        c = census(p); out[app] = c
        print(f"{app}: hclass={c['n_hclass']} seed={c['seed']} closure={c['closure']} "
              f"({c['closure']/c['n_hclass']*100:.3f}%) inst={c['shared_inst']}", flush=True)
    print("---JSON---"); print(json.dumps(out))
