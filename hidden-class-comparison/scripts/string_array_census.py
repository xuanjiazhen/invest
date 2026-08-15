#!/usr/bin/env python3
"""String + array backing census across Top13 heapsnapshots.

Classification uses the snapshot `type` field for strings (their node names are
empty in rawheap translator output) and node names for holder attribution
(ArkVM puts fine-grained types into node names: 'constant_pool', 'hclass',
'tagged_array', ...). Holders whose name is a real object name (closures named
by function, module records named by path) are bucketed as other:<category>.

Answers:
  1. String bytes held via constant_pool element edges (cross-VM duplication
     bound for constantpool-shared-literal sub-A) vs rest.
  2. String size/type histogram for feasible-proposals/04.
  3. tagged_array / cow_tagged_array backing bytes by holder, decomposing the
     ~296 MiB non-constantpool array backing.

Edge semantics: RawHeapTranslate emits an edge only when the slot holds a live
heap reference; Smi/double/Hole slots produce no edge. All byte figures are
live-object self_size sums.
"""
import json, sys, os
from collections import Counter

STRING_TYPES = {'string', 'slicedstring', 'concatenated string'}
KNOWN_TOKENS = {
    'constant_pool', 'hclass', 'tagged_array', 'cow_tagged_array', 'js_object',
    'js_array', 'method', 'lexical_env', 'global_env', 'function_template',
    'class_literal', 'prototype_handler', 'js_map', 'js_shared_map', 'js_set',
    'property_box', 'js_weak_ref', 'accessor_data', 'js_native_pointer',
    'enum_cache', 'proto_change_marker', 'proto_change_details',
    'tagged_dictionary', 'primitive_ref', 'symbol',
}
BUCKETS = [(24, '<=24'), (32, '25-32'), (48, '33-48'), (64, '49-64'),
           (96, '65-96'), (160, '97-160'), (256, '161-256'),
           (1024, '257-1K'), (1 << 20, '1K-1M'), (1 << 62, '>1M')]


def bucket(sz):
    for lim, name in BUCKETS:
        if sz <= lim:
            return name
    return '>1M'


def census(path):
    d = json.loads(open(path, encoding='utf-8', errors='replace').read(), strict=False)
    s = d['snapshot']
    nf = s['meta']['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
    ef = s['meta']['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
    nodes = d['nodes']; edges = d['edges']; strs = d['strings']
    ntypes = s['meta']['node_types'][0]
    n = len(nodes) // st

    starts = [0] * (n + 1); acc = 0
    for i in range(n):
        starts[i] = acc; acc += nodes[i * st + fi['edge_count']]
    starts[n] = acc

    is_string = [False] * n
    string_bytes = Counter()   # by type
    string_histo = Counter()   # bucket -> bytes (type 'string' only)
    for i in range(n):
        t = ntypes[nodes[i * st + fi['type']]]
        if t in STRING_TYPES:
            is_string[i] = True
            string_bytes[t] += nodes[i * st + fi['self_size']]
            string_histo[bucket(nodes[i * st + fi['self_size']])] += nodes[i * st + fi['self_size']]

    def holder_key(i):
        nm = strs[nodes[i * st + fi['name']]]
        if nm in KNOWN_TOKENS:
            return nm
        return 'other:' + ntypes[nodes[i * st + fi['type']]]

    str_holder = Counter()
    str_via_cp = 0
    arr_backing = Counter()
    arr_count = Counter()
    for i in range(n):
        ec = nodes[i * st + fi['edge_count']]; b = starts[i] * es
        hk = None
        for e in range(ec):
            o = b + e * es
            tgt = edges[o + efi['to_node']] // st
            if is_string[tgt]:
                if hk is None:
                    hk = holder_key(i)
                sz = nodes[tgt * st + fi['self_size']]
                str_holder[hk] += sz
                if hk == 'constant_pool':
                    str_via_cp += sz
            elif strs[nodes[tgt * st + fi['name']]] in ('tagged_array', 'cow_tagged_array'):
                if hk is None:
                    hk = holder_key(i)
                if hk not in ('tagged_array', 'cow_tagged_array'):
                    arr_backing[hk] += nodes[tgt * st + fi['self_size']]
                    arr_count[hk] += 1
    return {
        'string_bytes_by_type': dict(string_bytes),
        'string_via_cp_bytes': str_via_cp,
        'string_by_holder': dict(str_holder.most_common(15)),
        'string_histo_bytes': dict(string_histo),
        'array_backing_by_holder': dict(arr_backing.most_common(20)),
        'array_count_by_holder': dict(arr_count.most_common(20)),
    }


def main():
    out = {}
    for path in sys.argv[1:]:
        app = os.path.basename(path).split('.')[0]
        try:
            out[app] = census(path)
            r = out[app]
            tot = sum(r['string_bytes_by_type'].values())
            print(f"{app}: strings={tot/1048576:.2f}MiB via_cp={r['string_via_cp_bytes']/1048576:.2f}MiB",
                  file=sys.stderr)
        except Exception as ex:
            out[app] = {'error': str(ex)}
            print(f"{app}: ERROR {ex}", file=sys.stderr)
    agg = lambda k: Counter({}) if False else None
    str_holder = Counter(); histo = Counter(); arr = Counter(); arrn = Counter()
    str_type = Counter(); via_cp = 0
    for r in out.values():
        if 'error' in r:
            continue
        via_cp += r['string_via_cp_bytes']
        for k, v in r['string_bytes_by_type'].items(): str_type[k] += v
        for k, v in r['string_by_holder'].items(): str_holder[k] += v
        for k, v in r['string_histo_bytes'].items(): histo[k] += v
        for k, v in r['array_backing_by_holder'].items(): arr[k] += v
        for k, v in r['array_count_by_holder'].items(): arrn[k] += v
    print(json.dumps({
        'total_string_bytes_by_type': dict(str_type),
        'total_string_via_cp_bytes': via_cp,
        'string_by_holder_top': dict(str_holder.most_common(15)),
        'string_histo_bytes': dict(histo),
        'array_backing_by_holder': dict(arr.most_common(20)),
        'array_count_by_holder': dict(arrn.most_common(20)),
        'apps': out,
    }, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
