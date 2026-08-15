#!/usr/bin/env python3
"""Layout-resolving classifier.

self_size of a function object = <concrete class SIZE> + 8 * <inlined prop slots>.
JSObject::SIZE = 32; JSFunctionBase::SIZE = 56; JSApiFunction::SIZE = 80;
JSFunction::SIZE = 112 (ENABLE_MEMORY_OPTIMIZATION=1, no WorkNodePointer).

So subtracting 8 x (number of InlineProperty edges) from self_size recovers the
concrete base class size, independent of which slots happen to be Undefined.
"""
import json, sys, os
from collections import Counter

def analyze(path):
    d = json.load(open(path, encoding='utf-8'))
    snap = d['snapshot']
    nf = snap['meta']['node_fields']; stride = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = snap['meta']['edge_fields']; estride = len(ef); efi = {n: i for i, n in enumerate(ef)}
    etypes = snap['meta']['edge_types'][0]
    nodes = d['nodes']; edges = d['edges']; strings = d['strings']
    n = len(nodes) // stride
    print("  snapshot.node_count meta =", snap.get('node_count'), " computed =", n)
    starts = [0]*(n+1); acc = 0
    for i in range(n):
        starts[i] = acc; acc += nodes[i*stride+fi['edge_count']]
    base_hist = Counter()
    inline_hist = Counter()
    heap_self = 0
    for i in range(n):
        heap_self += nodes[i*stride+fi['self_size']]
    for i in range(n):
        ec = nodes[i*stride+fi['edge_count']]; b = starts[i]*estride
        names = []
        for k in range(ec):
            o = b + k*estride
            if etypes[edges[o+efi['type']]] == 'element':
                continue
            names.append(strings[edges[o+efi['name_or_index']]])
        s = set(names)
        if 'Method' not in s:
            continue
        ninline = sum(1 for x in names if x == 'InlineProperty')
        ss = nodes[i*stride+fi['self_size']]
        base_hist[(ss - 8*ninline, ninline)] += 1
        inline_hist[ss - 8*ninline] += 1
    return heap_self, base_hist, inline_hist

for p in sys.argv[1:]:
    print(os.path.basename(p))
    heap_self, bh, ih = analyze(p)
    print("  heap_self_size =", heap_self)
    print("  recovered base-size histogram (base -> count):")
    for base, c in sorted(ih.items()):
        print(f"    base={base:5d}  count={c}")
    print("  top (base, n_inline) combos:")
    for k, c in bh.most_common(15):
        print(f"    base={k[0]:5d} inline={k[1]:2d}  count={c}")
