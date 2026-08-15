#!/usr/bin/env python3
"""Top13 census: full-tail JSFunction population and its NAPI-convertible subset.

Two facts constrain the method:
  1. JSType is carried by the HClass, not the instance, so tail ownership must be
     decided per HClass and then applied to all of its instances.
  2. RawHeapTranslateV2 emits a field edge only for a live reference
     (GetNextEdgeTo returns nullptr on the ZERO_VALUE tag), so under JIT-off the
     MachineCode / BaselineCode / RawProfileTypeInfo / Module slots are Undefined
     on nearly every function and produce no edge.  Per-instance edge presence
     therefore undercounts; per-HClass "any instance ever showed a tail edge"
     does not.

Classification of every Method-bearing node (FunctionTemplate excluded: it is a
bare TaggedObject of 40 B, not a JSFunctionBase subclass):
  FULL   - its HClass had at least one instance with a full-tail edge
  PROXY  - Target + Handler edges (JSProxy, callable but not a function object)
  API    - self_size - 8*maxInlineSlots < JSFunction::SIZE (112)
  AMBIG  - remainder; inline-slot count is undercounted by undefined slots

NAPI-convertible proxy (what ENABLE_API_FUNCTION_OPTIMIZATION would move to the
JSApiFunction tail): a FULL function whose Method carries no ConstantPool edge,
i.e. a native entry with no bytecode.  All four macro call sites create
functions over a native entry.
"""
import json, sys, os
from collections import Counter, defaultdict

FULL_TAIL = {'RawProfileTypeInfo', 'MachineCode', 'BaselineCode', 'Module'}
JSFUNCTION_SIZE = 112


def census(path):
    # strict=False: some app snapshots carry raw control characters inside
    # framework-generated node names
    d = json.loads(open(path, encoding='utf-8', errors='replace').read(), strict=False)
    s = d['snapshot']
    nf = s['meta']['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = s['meta']['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    et = s['meta']['edge_types'][0]
    nodes = d['nodes']; edges = d['edges']; strs = d['strings']
    n = len(nodes) // st

    starts = [0] * (n + 1); acc = 0
    for i in range(n):
        starts[i] = acc; acc += nodes[i * st + fi['edge_count']]
    starts[n] = acc

    def named_edges(i):
        ec = nodes[i * st + fi['edge_count']]; b = starts[i] * es
        for k in range(ec):
            o = b + k * es
            if et[edges[o + efi['type']]] == 'element':
                continue
            yield strs[edges[o + efi['name_or_index']]], edges[o + efi['to_node']] // st

    # a Method node is native iff it has no ConstantPool edge
    method_native = {}

    heap_self = sum(nodes[i * st + fi['self_size']] for i in range(n))

    insts = []          # (hclass, self_size, ninline, edgeset, native)
    by_hc = defaultdict(lambda: {'full': False, 'ss': 0, 'maxinl': 0, 'ed': set()})
    for i in range(n):
        if strs[nodes[i * st + fi['name']]] == 'function_template':
            continue
        names = []; hc = None; mnode = None
        for nm, to in named_edges(i):
            names.append(nm)
            if nm == 'hclass':
                hc = to
            elif nm == 'Method':
                mnode = to
        eset = set(names)
        if 'Method' not in eset or hc is None:
            continue
        if mnode not in method_native:
            method_native[mnode] = not any(x == 'ConstantPool' for x, _ in named_edges(mnode))
        ss = nodes[i * st + fi['self_size']]
        ninl = sum(1 for x in names if x == 'InlineProperty')
        e = by_hc[hc]
        e['ss'] = ss
        e['maxinl'] = max(e['maxinl'], ninl)
        e['ed'] |= eset
        if eset & FULL_TAIL:
            e['full'] = True
        insts.append((hc, ss, eset, method_native[mnode]))

    r = Counter(); sz = Counter()
    for hc, ss, eset, native in insts:
        e = by_hc[hc]
        if e['full']:
            cls = 'FULL'
        elif 'Target' in e['ed'] and 'Handler' in e['ed']:
            cls = 'PROXY'
        elif e['ss'] - 8 * e['maxinl'] < JSFUNCTION_SIZE:
            cls = 'API'
        else:
            cls = 'AMBIG'
        r[cls] += 1; sz[cls] += ss
        if cls == 'FULL':
            if native:
                r['FULL_native'] += 1; sz['FULL_native'] += ss
                if 'ProtoOrHClass' in eset:
                    r['FULL_native_ctor'] += 1; sz['FULL_native_ctor'] += ss
            if 'ProtoOrHClass' in eset:
                r['FULL_ctor'] += 1
    return {'nodes': n, 'heap_self_size': heap_self,
            'func_hclasses': len(by_hc),
            **{f'n_{k}': v for k, v in r.items()},
            **{f'sz_{k}': v for k, v in sz.items()}}


if __name__ == '__main__':
    out = {}
    for p in sys.argv[1:]:
        app = os.path.basename(p).replace('.heapsnapshot', '')
        c = census(p)
        out[app] = c
        print(f"{app}: FULL={c.get('n_FULL',0)} native={c.get('n_FULL_native',0)} "
              f"native_ctor={c.get('n_FULL_native_ctor',0)} ctor={c.get('n_FULL_ctor',0)} "
              f"API={c.get('n_API',0)} PROXY={c.get('n_PROXY',0)} AMBIG={c.get('n_AMBIG',0)} "
              f"heap_self={c['heap_self_size']}", flush=True)
    print("---JSON---")
    print(json.dumps(out, ensure_ascii=False))
