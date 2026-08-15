#!/usr/bin/env python3
"""Split the full-tail JSFunction population into NAPI-created vs the rest.

Every one of the 8 ENABLE_API_FUNCTION_OPTIMIZATION call sites is immediately
followed by JSFunction::SetFunctionExtraInfo (jsnapi_expo.cpp), which stores a
JSNativePointer at HASH_OFFSET (js_function.cpp:1110-1149) either directly or in
a TaggedArray slot.  In production that function is called only from
ecmascript/napi/jsnapi_expo.cpp, so a full-tail function whose HashField reaches
a js_native_pointer was created through the NAPI surface -- exactly the set the
macro would move to the JSApiFunction tier.

Builtins (Object.keys etc.) are native-entry too but are created by builtins.cpp
via CreateFunctionClass and never call SetFunctionExtraInfo, so they carry no
such HashField and are correctly excluded.
"""
import json, sys, os
from collections import Counter, defaultdict

FULL_TAIL = {'RawProfileTypeInfo', 'MachineCode', 'BaselineCode', 'Module'}


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

    def elems(i):
        ec = nodes[i*st+fi['edge_count']]; b = starts[i]*es
        for k in range(ec):
            o = b + k*es
            yield edges[o+efi['to_node']]//st

    # does this HashField target carry a JSNativePointer?
    def is_napi_hash(t):
        if nm(t) == 'js_native_pointer':
            return True
        if nm(t) in ('tagged_array', 'cow_tagged_array'):
            return any(nm(x) == 'js_native_pointer' for x in elems(t))
        return False

    insts = []
    by_hc = defaultdict(lambda: {'full': False})
    for i in range(n):
        if nm(i) == 'function_template':
            continue
        hc = None; hashto = None; names = []
        for e, to in named(i):
            names.append(e)
            if e == 'hclass': hc = to
            elif e == 'HashField': hashto = to
        if 'Method' not in names or hc is None:
            continue
        eset = set(names)
        if eset & FULL_TAIL:
            by_hc[hc]['full'] = True
        insts.append((hc, hashto, 'ProtoOrHClass' in eset))

    r = Counter()
    for hc, hashto, isctor in insts:
        if not by_hc[hc]['full']:
            continue
        r['FULL'] += 1
        if hashto is not None and is_napi_hash(hashto):
            r['NAPI'] += 1
            if isctor:
                r['NAPI_ctor'] += 1
    return dict(r)


if __name__ == '__main__':
    out = {}
    for p in sys.argv[1:]:
        app = os.path.basename(p).replace('.heapsnapshot', '')
        c = census(p); out[app] = c
        F = c.get('FULL', 0); N = c.get('NAPI', 0)
        print(f"{app}: FULL={F} NAPI={N} ({N/F*100:.2f}%) NAPI_ctor={c.get('NAPI_ctor',0)}",
              flush=True)
    print("---JSON---"); print(json.dumps(out))
