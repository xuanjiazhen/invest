#!/usr/bin/env python3
"""Function-object census resolved at HClass granularity.

Why HClass granularity: the V2 rawheap translator emits a field edge ONLY when
the slot holds a live reference (RawHeapTranslateV2::GetNextEdgeTo returns
nullptr for the ZERO_VALUE tag).  Under JIT-off, MachineCode / BaselineCode /
RawProfileTypeInfo / Module are Undefined on almost every function, so per-node
edge presence badly undercounts the population that OWNS those slots.

JSType is a property of the HClass, not of the instance.  So:
  1. bucket every Method-bearing node by the node its 'hclass' edge points to;
  2. an HClass is JS_FUNCTION-family if ANY of its instances ever emitted a
     full-tail edge (RawProfileTypeInfo / MachineCode / BaselineCode / Module),
     or if its instance self_size matches JSFunction::SIZE + 8k and no instance
     contradicts that;
  3. every instance of such an HClass owns the 4 tail slots.

Sizes (ENABLE_MEMORY_OPTIMIZATION=1, no WorkNodePointer):
  JSObject::SIZE = 32, JSFunctionBase::SIZE = 56,
  JSApiFunction::SIZE = 80, JSFunction::SIZE = 112.
FunctionTemplate is a bare TaggedObject (40 B) and is excluded explicitly.
"""
import json, sys, os
from collections import Counter, defaultdict

FULL_TAIL = {'RawProfileTypeInfo', 'MachineCode', 'BaselineCode', 'Module'}
API_ONLY = {'ProtoOrHClass', 'LexicalEnv', 'HomeObject'}


def census(path):
    d = json.load(open(path, encoding='utf-8'))
    s = d['snapshot']
    nf = s['meta']['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    nt = s['meta']['node_types'][0]
    ef = s['meta']['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    et = s['meta']['edge_types'][0]
    nodes = d['nodes']; edges = d['edges']; strs = d['strings']
    n = len(nodes) // st

    heap_self = sum(nodes[i * st + fi['self_size']] for i in range(n))

    # pass 1: bucket function-shaped nodes by their hclass node
    by_hc = defaultdict(lambda: {'n': 0, 'size': 0, 'full': False, 'ctor': False,
                                 'sizes': Counter(), 'ninl': Counter()})
    off = 0
    for i in range(n):
        ec = nodes[i * st + fi['edge_count']]; b = off * es; off += ec
        names = []
        hc = None
        for k in range(ec):
            o = b + k * es
            if et[edges[o + efi['type']]] == 'element':
                continue
            nm = strs[edges[o + efi['name_or_index']]]
            names.append(nm)
            if nm == 'hclass':
                hc = edges[o + efi['to_node']] // st
        sset = set(names)
        if 'Method' not in sset:
            continue
        if strs[nodes[i * st + fi['name']]] == 'function_template':
            continue          # FunctionTemplate: bare TaggedObject, 40 B
        if hc is None:
            continue
        e = by_hc[hc]
        ss = nodes[i * st + fi['self_size']]
        e['n'] += 1; e['size'] += ss
        e['sizes'][ss] += 1
        e['ninl'][sum(1 for x in names if x == 'InlineProperty')] += 1
        if sset & FULL_TAIL:
            e['full'] = True
        if 'ProtoOrHClass' in sset:
            e['ctor'] = True

    full_n = full_sz = api_n = api_sz = 0
    unres_n = unres_sz = 0
    ctor_full_n = 0
    for hc, e in by_hc.items():
        # every instance of one HClass has the same self_size and the same JSType
        ss = e['sizes'].most_common(1)[0][0]
        if e['full']:
            full_n += e['n']; full_sz += e['size']
            if e['ctor']:
                ctor_full_n += e['n']
            continue
        # no instance ever showed a tail edge -> resolve by size.
        # a JS_API_FUNCTION instance is 80 + 8k; a JS_FUNCTION instance is 112 + 8k.
        # both forms are 8-aligned, so size alone cannot separate them; fall back
        # to the maximum inline-slot count actually observed.
        maxinl = max(e['ninl'])
        base = ss - 8 * maxinl
        if base <= 80:
            api_n += e['n']; api_sz += e['size']
        else:
            unres_n += e['n']; unres_sz += e['size']
    return {
        'nodes': n, 'heap_self_size': heap_self,
        'hclasses': len(by_hc),
        'full_n': full_n, 'full_sz': full_sz,
        'full_ctor_n': ctor_full_n,
        'api_n': api_n, 'api_sz': api_sz,
        'unresolved_n': unres_n, 'unresolved_sz': unres_sz,
    }


if __name__ == '__main__':
    out = {}
    for p in sys.argv[1:]:
        app = os.path.basename(p).replace('.heapsnapshot', '')
        c = census(p)
        out[app] = c
        print(f"{app}: nodes={c['nodes']} funcHClasses={c['hclasses']} "
              f"FULL={c['full_n']} (ctor {c['full_ctor_n']}) API={c['api_n']} "
              f"UNRES={c['unresolved_n']}", flush=True)
    print("---JSON---")
    print(json.dumps(out, ensure_ascii=False))
