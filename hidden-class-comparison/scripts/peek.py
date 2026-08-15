#!/usr/bin/env python3
import json, sys
from collections import Counter
path = sys.argv[1]
data = json.load(open(path, "r", encoding="utf-8"))
snap = data["snapshot"]
nf = snap["meta"]["node_fields"]; stride = len(nf); fi = {n:i for i,n in enumerate(nf)}
node_types = snap["meta"]["node_types"][0]
ef = snap["meta"]["edge_fields"]; estride = len(ef); efi = {n:i for i,n in enumerate(ef)}
edge_types = snap["meta"]["edge_types"][0]
nodes = data["nodes"]; edges = data["edges"]; strings = data["strings"]
n = len(nodes)//stride
print("node_fields", nf, "edge_fields", ef)
print("node_types", node_types)
print("edge_types", edge_types)
names = Counter(); sizes = Counter()
for i in range(n):
    nm = strings[nodes[i*stride+fi["name"]]]
    names[nm]+=1; sizes[nm]+=nodes[i*stride+fi["self_size"]]
print("top 40 node names:")
for nm,c in names.most_common(40):
    print(f"  {nm!r}  count={c}  self={sizes[nm]}  avg={sizes[nm]//c}")
