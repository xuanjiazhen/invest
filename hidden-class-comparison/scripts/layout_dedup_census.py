#!/usr/bin/env python3
"""Distinct-object byte census for Layout arrays and constant_pool strings.

Attribution-by-edge double counts shared targets (interned strings, the 16 B
EmptyArray singleton). This script counts each target node once per snapshot:
  - layout_bytes: distinct targets of hclass --Layout--> tagged_array edges
  - cp_string_bytes: distinct string nodes reachable from constant_pool
  - layout_per_hclass: layout count / hclass count (sharing factor)
"""
import json, sys, os
from collections import Counter


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
    name_of = lambda i: strs[nodes[i * st + fi['name']]]
    is_string = [ntypes[nodes[i * st + fi['type']]] in
                 ('string', 'slicedstring', 'concatenated string') for i in range(n)]

    def ename(o):
        v = edges[o + efi['name_or_index']]
        return strs[v] if isinstance(v, int) else v

    layouts = set(); hclasses = 0; cp_strings = set()
    for i in range(n):
        hn = name_of(i)
        if hn == 'hclass':
            hclasses += 1
        ec = nodes[i * st + fi['edge_count']]; b = starts[i] * es
        for e in range(ec):
            o = b + e * es
            tgt = edges[o + efi['to_node']] // st
            if hn == 'hclass' and ename(o) == 'Layout':
                layouts.add(tgt)
            elif hn == 'constant_pool' and is_string[tgt]:
                cp_strings.add(tgt)
    lay_b = sum(nodes[t * st + fi['self_size']] for t in layouts)
    cps_b = sum(nodes[t * st + fi['self_size']] for t in cp_strings)
    return {'hclasses': hclasses, 'layouts': len(layouts), 'layout_bytes': lay_b,
            'cp_strings': len(cp_strings), 'cp_string_bytes': cps_b}


def main():
    tot = Counter()
    apps = {}
    for path in sys.argv[1:]:
        app = os.path.basename(path).split('.')[0]
        r = census(path)
        apps[app] = r
        tot.update(r)
        print(f"{app}: hclass={r['hclasses']} layout={r['layouts']} "
              f"layout_bytes={r['layout_bytes']/1048576:.2f}MiB "
              f"cp_string={r['cp_strings']} cp_str_bytes={r['cp_string_bytes']/1048576:.2f}MiB",
              file=sys.stderr)
    print(json.dumps({'total': dict(tot), 'apps': apps}, indent=1))


if __name__ == '__main__':
    main()
