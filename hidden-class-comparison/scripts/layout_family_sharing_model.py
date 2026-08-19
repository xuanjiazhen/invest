#!/usr/bin/env python3
"""LayoutInfo family-sharing upper-bound model.

Reconstructs each distinct LayoutInfo's ordered key sequence from snapshot
element edges (keys are interned strings; interleaved attr slots are Smi and
produce no edge; element edge index encodes slot order). Then models:

  1. identical-content dedup  : layouts with equal key sequences share one
     array (covers today's proto/extensible/attr-update full copies that copy
     identical or re-derived content);
  2. family sharing (V8 slack-append): along a prefix chain one array serves
     the whole chain; arrays needed = leaves of the prefix forest.

Byte model per array: 16 + 16*N (current encoding), capacity = leaf N.
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
    is_str = [ntypes[nodes[i * st + fi['type']]] == 'string' for i in range(n)]

    layouts = set()
    for i in range(n):
        if name_of(i) != 'hclass':
            continue
        ec = nodes[i * st + fi['edge_count']]; b = starts[i] * es
        for e in range(ec):
            o = b + e * es
            v = edges[o + efi['name_or_index']]
            en = strs[v] if isinstance(v, int) else v
            if en == 'Layout':
                layouts.add(edges[o + efi['to_node']] // st)

    # key sequence per layout
    seqs = {}
    for L in layouts:
        ec = nodes[L * st + fi['edge_count']]; b = starts[L] * es
        keys = {}
        ok = True
        for e in range(ec):
            o = b + e * es
            if edges[o + efi['type']] != 1:  # 'element'
                continue
            tgt = edges[o + efi['to_node']] // st
            idx = edges[o + efi['name_or_index']]
            if not is_str[tgt]:
                ok = False; break
            keys[idx] = tgt
        if not ok:
            continue
        seq = tuple(keys[i] for i in sorted(keys))
        seqs[L] = seq
    return seqs


def model(seqs):
    # identical-content dedup
    uniq = {}
    for L, seq in seqs.items():
        uniq.setdefault(seq, []).append(L)
    # prefix forest over unique sequences (trie)
    trie = {}
    LEAF = '$'
    for seq in uniq:
        node = trie
        for k in seq:
            node = node.setdefault(k, {})
            node.pop(LEAF, None) if False else None
        node[LEAF] = True
    # count leaves: walk trie
    leaves = 0
    stack = [trie]
    while stack:
        node = stack.pop()
        children = [k for k in node if k != LEAF]
        if not children:
            leaves += 1
        else:
            stack.extend(node[k] for k in children)
    # NOTE: a node marked LEAF with children = intermediate terminal (chain continues) -> not a leaf
    # sizes: current = all layouts; dedup = unique seqs; family = leaf seqs sized at their N
    cur = sum((len(seq)) for seq in [])  # placeholder
    return uniq, leaves


def main():
    tot = Counter()
    for path in sys.argv[1:]:
        seqs = census(path)
        app = os.path.basename(path).split('.')[0]
        uniq, leaves = model(seqs)
        cur_count = len(seqs)
        cur_bytes = sum(16 + 16 * len(q) for q in seqs.values())
        uniq_count = len(uniq)
        uniq_bytes = sum(16 + 16 * len(q) for q in uniq)
        # family: need leaf sequences' lengths; recompute by walking trie with seq length
        trie = {}
        LEAF = '$'
        for q in uniq:
            node = trie
            for k in q:
                node = node.setdefault(k, {})
            node[LEAF] = len(q)
        fam_bytes = 0
        stack = [(trie, False)]
        while stack:
            node, _ = stack.pop()
            children = [k for k in node if k != LEAF]
            if not children:
                fam_bytes += 16 + 16 * node.get(LEAF, 0)
            else:
                stack.extend((node[k], False) for k in children)
        fam_count = sum(1 for _ in iter_leaves(trie))
        tot['cur_b'] += cur_bytes; tot['uniq_b'] += uniq_bytes; tot['fam_b'] += fam_bytes
        tot['cur_n'] += cur_count; tot['uniq_n'] += uniq_count; tot['fam_n'] += fam_count
        print(f"{app}: layouts={cur_count} ({cur_bytes/1048576:.2f}MiB) "
              f"dedup={uniq_count} ({uniq_bytes/1048576:.2f}MiB) "
              f"family={fam_count} ({fam_bytes/1048576:.2f}MiB)", file=sys.stderr)
    M = 1048576
    print(json.dumps({
        'current': {'count': tot['cur_n'], 'bytes': tot['cur_b']},
        'identical_dedup': {'count': tot['uniq_n'], 'bytes': tot['uniq_b']},
        'family_shared': {'count': tot['fam_n'], 'bytes': tot['fam_b']},
        'saving_dedup_only': tot['cur_b'] - tot['uniq_b'],
        'saving_family_total': tot['cur_b'] - tot['fam_b'],
    }, indent=1))


def iter_leaves(trie):
    stack = [trie]
    while stack:
        node = stack.pop()
        children = [k for k in node if k != '$']
        if not children:
            yield node
        else:
            stack.extend(node[k] for k in children)


if __name__ == '__main__':
    main()
