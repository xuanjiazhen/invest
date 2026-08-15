#!/usr/bin/env python3
"""
measure_lazy_binding_targets.py
===============================
Size the app-side addressable share of bucket C -- native interop JSFunction
closures bound to prototypes of classes that have ZERO live instances.

Bucket C splits into structurally different populations needing different fixes:

  WIDE   1 prototype carrying >=20 native methods. These are system NAPI class
         prototypes (@ohos.multimedia.camera VideoSession, @ohos.web.webview
         WebviewController, ...). The app cannot rewrite the class; the app-side
         lever is a lazy module accessor so the prototype is never materialized.

  NARROW many prototypes each carrying an identical small method set
         (copy/equals/hashCode/toString). These are code-generator output
         (protobuf *_pb.js message and enum wrappers). Lever: generator
         granularity / tree-shaking.

  BARE   prototypes contributing only the constructor closure, no methods.

Evidence for WIDE attribution: the class is reported together with the
`@ohos:*` module specifier strings actually present in that snapshot, so a
class is only claimed reclaimable when the app demonstrably loaded its module.

Usage:
    python measure_lazy_binding_targets.py [--json] [--wide N] *.heapsnapshot
"""
import json as _json
import sys
import os
import argparse
import collections

__version__ = "1.0.0"
M = 1048576

# class -> @ohos module specifier. Only used to name the import site in the
# report; membership in bucket C is measured from the snapshot, not this table.
SYS_CLASS_MODULE = {
    # @ohos.multimedia.camera
    "VideoSession": "@ohos.multimedia.camera", "PhotoSession": "@ohos.multimedia.camera",
    "SecureCameraSession": "@ohos.multimedia.camera", "CameraManager": "@ohos.multimedia.camera",
    "PhotoOutput": "@ohos.multimedia.camera", "PreviewOutput": "@ohos.multimedia.camera",
    "VideoOutput": "@ohos.multimedia.camera", "CameraInput": "@ohos.multimedia.camera",
    "MetadataOutput": "@ohos.multimedia.camera", "CameraDevice": "@ohos.multimedia.camera",
    "DeferredPhotoProxy": "@ohos.multimedia.camera",
    # @ohos.web.webview
    "WebviewController": "@ohos.web.webview", "WebCookieManager": "@ohos.web.webview",
    "WebStorage": "@ohos.web.webview", "WebDataBase": "@ohos.web.webview",
    "WebSchemeHandler": "@ohos.web.webview", "WebHeader": "@ohos.web.webview",
    "WebResourceHandler": "@ohos.web.webview", "WebSchemeHandlerRequest": "@ohos.web.webview",
    # @ohos.multimedia.media
    "AVPlayer": "@ohos.multimedia.media", "AVRecorder": "@ohos.multimedia.media",
    "AVMetadataExtractor": "@ohos.multimedia.media", "AVImageGenerator": "@ohos.multimedia.media",
    "AVTranscoder": "@ohos.multimedia.media", "SoundPool": "@ohos.multimedia.media",
    # @ohos.multimedia.audio
    "AudioRenderer": "@ohos.multimedia.audio", "AudioCapturer": "@ohos.multimedia.audio",
    "AudioManager": "@ohos.multimedia.audio", "AudioVolumeManager": "@ohos.multimedia.audio",
    "AudioVolumeGroupManager": "@ohos.multimedia.audio",
    "AudioRoutingManager": "@ohos.multimedia.audio",
    "AudioStreamManager": "@ohos.multimedia.audio",
    "AudioSpatializationManager": "@ohos.multimedia.audio",
    "AudioSessionManager": "@ohos.multimedia.audio",
    "AudioEffectManager": "@ohos.multimedia.audio",
    "AudioLoopback": "@ohos.multimedia.audio",
    # @ohos.multimedia.image
    "ImageSource": "@ohos.multimedia.image", "ImagePacker": "@ohos.multimedia.image",
    "ImageReceiver": "@ohos.multimedia.image", "ImageCreator": "@ohos.multimedia.image",
    "PixelMap": "@ohos.multimedia.image", "Picture": "@ohos.multimedia.image",
    "AuxiliaryPicture": "@ohos.multimedia.image", "Metadata": "@ohos.multimedia.image",
    # @ohos.rpc
    "MessageSequence": "@ohos.rpc", "MessageParcel": "@ohos.rpc",
    "RemoteObject": "@ohos.rpc", "RemoteProxy": "@ohos.rpc", "IPCSkeleton": "@ohos.rpc",
    "Ashmem": "@ohos.rpc",
    # @ohos.data.relationalStore / rdb
    "RdbPredicates": "@ohos.data.relationalStore", "ResultSet": "@ohos.data.relationalStore",
    "Transaction": "@ohos.data.relationalStore", "RdbStore": "@ohos.data.relationalStore",
    "LiteResultSet": "@ohos.data.relationalStore",
    # @ohos.data.*
    "DataSharePredicates": "@ohos.data.dataSharePredicates",
    "Query": "@ohos.data.distributedKVStore", "KVStore": "@ohos.data.distributedKVStore",
    "SingleKVStore": "@ohos.data.distributedKVStore",
    "DeviceKVStore": "@ohos.data.distributedKVStore",
    "KVManager": "@ohos.data.distributedKVStore",
    "Preferences": "@ohos.data.preferences",
    # @ohos.file.photoAccessHelper
    "PhotoAccessHelper": "@ohos.file.photoAccessHelper",
    "PhotoAccessHelperFileAsset": "@ohos.file.photoAccessHelper",
    "FileAsset": "@ohos.file.photoAccessHelper",
    "FetchResult": "@ohos.file.photoAccessHelper",
    "Album": "@ohos.file.photoAccessHelper",
    "MediaAssetChangeRequest": "@ohos.file.photoAccessHelper",
    "MediaAlbumChangeRequest": "@ohos.file.photoAccessHelper",
    "MediaAssetManager": "@ohos.file.photoAccessHelper",
    # @ohos.account.osAccount
    "AccountManager": "@ohos.account.osAccount",
    "AppAccountManager": "@ohos.account.appAccount",
    # @ohos.graphics.text / drawing
    "Paragraph": "@ohos.graphics.text", "ParagraphBuilder": "@ohos.graphics.text",
    "TextLine": "@ohos.graphics.text", "Run": "@ohos.graphics.text",
    "FontCollection": "@ohos.graphics.text", "LineTypeset": "@ohos.graphics.text",
    # @ohos.pasteboard
    "SystemPasteboard": "@ohos.pasteboard", "PasteData": "@ohos.pasteboard",
    "PasteDataRecord": "@ohos.pasteboard",
    # misc
    "Zip": "@ohos.zlib", "GZip": "@ohos.zlib", "Checksum": "@ohos.zlib",
    "Calendar": "@ohos.i18n", "Locale": "@ohos.intl", "Localization": "@ohos.i18n",
    "atManager": "@ohos.abilityAccessCtrl",
    "DeviceManager": "@ohos.distributedDeviceManager",
    "STValue": "@ohos.arkui.StateManagement",
    "XmlSerializer": "@ohos.xml", "XmlDynamicSerializer": "@ohos.xml",
    "XmlPullParser": "@ohos.xml",
    "URLSearchParams": "@ohos.url", "URL": "@ohos.url",
    "LayeredDrawableDescriptor": "@ohos.arkui.drawableDescriptor",
    "Font": "@ohos.font", "UIContext": "@ohos.arkui.UIContext",
    "HttpRequest": "@ohos.net.http", "TCPSocket": "@ohos.net.socket",
    "UDPSocket": "@ohos.net.socket", "TLSSocket": "@ohos.net.socket",
    "WebSocket": "@ohos.net.webSocket",
    "Cipher": "@ohos.security.cryptoFramework",
    "HuksKey": "@ohos.security.huks",
    "TaskGroup": "@ohos.taskpool", "Task": "@ohos.taskpool",
    "Sendable": "@ohos.arkui.sendable",
    "AVSession": "@ohos.multimedia.avsession",
    "AVCastController": "@ohos.multimedia.avsession",
    "AVSessionController": "@ohos.multimedia.avsession",
    "AudioDecoder": "@ohos.multimedia.avcodec",
    "VideoDecoder": "@ohos.multimedia.avcodec",
    "VideoEncoder": "@ohos.multimedia.avcodec",
    "AudioEncoder": "@ohos.multimedia.avcodec",
    "AVMuxer": "@ohos.multimedia.avcodec", "AVDemuxer": "@ohos.multimedia.avcodec",
    "MediaSource": "@ohos.multimedia.media",
    "Sensor": "@ohos.sensor", "Vibrator": "@ohos.vibrator",
    "BundleManager": "@ohos.bundle.bundleManager",
    "UploadTask": "@ohos.request", "DownloadTask": "@ohos.request",
    "RequestTask": "@ohos.request", "Agent": "@ohos.request",
}


def load(path):
    d = _json.loads(open(path, encoding="utf-8", errors="replace").read(), strict=False)
    m = d["snapshot"]["meta"]
    nf = m["node_fields"]; st = len(nf); fi = {x: i for i, x in enumerate(nf)}
    ef = m["edge_fields"]; es = len(ef); efi = {x: i for i, x in enumerate(ef)}
    nodes, edges, strs = d["nodes"], d["edges"], d["strings"]
    n = len(nodes) // st
    starts = [0] * (n + 1); a = 0
    for i in range(n):
        starts[i] = a; a += nodes[i * st + fi["edge_count"]]
    starts[n] = a
    return dict(nodes=nodes, edges=edges, strs=strs, n=n, st=st, fi=fi, es=es,
                efi=efi, et=m["edge_types"][0], nt=m["node_types"][0], starts=starts)


def analyze(path, wide=20, threshold=1000):
    app = os.path.basename(path).replace(".heapsnapshot", "")
    g = load(path)
    nodes, edges, strs, n = g["nodes"], g["edges"], g["strs"], g["n"]
    st, fi, es, efi = g["st"], g["fi"], g["es"], g["efi"]
    et, nt, starts = g["et"], g["nt"], g["starts"]
    nm = lambda i: strs[nodes[i * st + fi["name"]]]
    szf = lambda i: nodes[i * st + fi["self_size"]]
    ty = lambda i: nt[nodes[i * st + fi["type"]]]

    def out(i):
        ec = nodes[i * st + fi["edge_count"]]; b = starts[i] * es
        for k in range(ec):
            o = b + k * es
            e = et[edges[o + efi["type"]]]
            raw = edges[o + efi["name_or_index"]]
            lb = strs[raw] if e != "element" else raw
            yield e, lb, edges[o + efi["to_node"]] // st

    # module specifiers actually present in this snapshot
    ohos_mods = {s.replace("@ohos:", "@ohos.") for s in strs if s.startswith("@ohos:")}

    # closures sharing a native Method stub
    mu = collections.defaultdict(list)
    for i in range(n):
        if ty(i) != "closure":
            continue
        for _, lb, to in out(i):
            if lb == "Method":
                mu[to].append(i); break
    target = set()
    for v in mu.values():
        if len(v) >= threshold:
            target.update(v)

    proto_objs = set(); hproto = collections.defaultdict(list)
    inc = collections.defaultdict(list); rev = collections.defaultdict(list)
    for i in range(n):
        for e, lb, to in out(i):
            if lb in ("Proto", "ProtoOrHClass"):
                proto_objs.add(to); hproto[to].append(i)
            if to in target:
                inc[to].append((lb, i))
            rev[to].append((lb, i))
    hci = collections.Counter()
    for i in range(n):
        for _, lb, to in out(i):
            if lb == "hclass":
                hci[to] += 1

    def own(i):
        """closure's real identity string (node name is the shared stub's)"""
        for _, lb, to in out(i):
            if lb == "InlineProperty" and ty(to) == "string" and nm(to):
                return nm(to)
        return None

    cproto = collections.defaultdict(list)
    for ci in target:
        if own(ci) is None:
            continue
        ph = None
        for lb, h in inc[ci]:
            if h in proto_objs and lb in ("InlineProperty", "Getter", "Setter"):
                ph = h; break
        if ph is None or any(hci.get(h, 0) > 0 for h in hproto.get(ph, ())):
            continue
        cproto[ph].append(ci)

    # classify each prototype
    WIDE, NARROW, BARE = {}, collections.defaultdict(
        lambda: dict(protos=0, n=0, b=0, names=[])), dict(protos=0, n=0, b=0)
    for p, cl in cproto.items():
        cname = None
        for lb, h in rev.get(p, []):
            if lb in ("ProtoOrHClass", "HomeObject") and ty(h) == "closure" and own(h):
                cname = own(h); break
        ms = sorted({own(c) for c in cl if own(c)} - {cname})
        b = sum(szf(c) for c in cl)
        if len(ms) >= wide:
            e = WIDE.setdefault(cname or f"<proto#{p}>",
                                dict(n=0, b=0, methods=0, protos=0))
            e["n"] += len(cl); e["b"] += b
            e["methods"] = max(e["methods"], len(ms)); e["protos"] += 1
            e["mset"] = len(ms)
        elif not ms:
            BARE["protos"] += 1; BARE["n"] += len(cl); BARE["b"] += b
        else:
            e = NARROW["|".join(ms)]
            e["protos"] += 1; e["n"] += len(cl); e["b"] += b
            if len(e["names"]) < 6:
                e["names"].append(cname)

    tot_n = sum(len(v) for v in cproto.values())
    tot_b = sum(szf(c) for v in cproto.values() for c in v)

    # WIDE grouped by owning @ohos module, keeping only modules this app loaded
    bymod = collections.defaultdict(lambda: dict(n=0, b=0, classes=[]))
    wide_unknown = dict(n=0, b=0, classes=[])
    for cn, e in WIDE.items():
        mod = SYS_CLASS_MODULE.get(cn)
        if mod is None:
            wide_unknown["n"] += e["n"]; wide_unknown["b"] += e["b"]
            wide_unknown["classes"].append(
                (cn, e["n"], e["methods"], e["protos"], e["b"] / M))
            continue
        t = bymod[mod]
        t["n"] += e["n"]; t["b"] += e["b"]
        t["classes"].append((cn, e["n"], e["methods"], e["protos"], e["b"] / M))
    for mod, t in bymod.items():
        t["loaded"] = mod in ohos_mods or mod.replace("@ohos.", "@ohos:") in strs

    return dict(
        app=app, c_protos=len(cproto), c_n=tot_n, c_mib=tot_b / M,
        wide_n=sum(e["n"] for e in WIDE.values()),
        wide_mib=sum(e["b"] for e in WIDE.values()) / M,
        wide_classes=len(WIDE),
        narrow_n=sum(e["n"] for e in NARROW.values()),
        narrow_mib=sum(e["b"] for e in NARROW.values()) / M,
        narrow_protos=sum(e["protos"] for e in NARROW.values()),
        narrow_families=len(NARROW),
        bare_n=BARE["n"], bare_mib=BARE["b"] / M, bare_protos=BARE["protos"],
        by_module={k: dict(n=v["n"], mib=v["b"] / M, loaded=v["loaded"],
                           classes=sorted(v["classes"], key=lambda x: -x[1]))
                   for k, v in bymod.items()},
        wide_unknown=dict(n=wide_unknown["n"], mib=wide_unknown["b"] / M,
                          classes=sorted(wide_unknown["classes"], key=lambda x: -x[1])),
        narrow_top=[dict(methods=k.split("|"), protos=v["protos"], n=v["n"],
                         mib=v["b"] / M, names=v["names"])
                    for k, v in sorted(NARROW.items(), key=lambda kv: -kv[1]["b"])[:60]],
        ohos_mods=len(ohos_mods),
    )


def report(results):
    for r in results:
        print(f"=== {r['app']} === bucketC protos={r['c_protos']} n={r['c_n']} "
              f"{r['c_mib']:.3f} MiB   @ohos modules loaded={r['ohos_mods']}")
        print(f"  WIDE   classes={r['wide_classes']:4d} n={r['wide_n']:6d} "
              f"{r['wide_mib']:7.3f} MiB   <== lazy module accessor")
        print(f"  NARROW families={r['narrow_families']:4d} protos={r['narrow_protos']:5d} "
              f"n={r['narrow_n']:6d} {r['narrow_mib']:7.3f} MiB  <== codegen / tree-shake")
        print(f"  BARE   protos={r['bare_protos']:5d} n={r['bare_n']:6d} "
              f"{r['bare_mib']:7.3f} MiB")
        print("  -- WIDE by @ohos module --")
        for mod, v in sorted(r["by_module"].items(), key=lambda kv: -kv[1]["mib"]):
            tag = "loaded" if v["loaded"] else "n/a"
            cs = ", ".join(f"{c}({mth}m x{pr})" for c, k, mth, pr, _ in v["classes"][:4])
            print(f"     {v['mib']:7.3f} MiB n={v['n']:5d} [{tag:6s}] {mod:<38} {cs}")
        wu = r["wide_unknown"]
        if wu["n"]:
            print(f"     {wu['mib']:7.3f} MiB n={wu['n']:5d} [unmapped] "
                  f"{[(c, f'{m}m x{pr}') for c, k, m, pr, _ in wu['classes'][:6]]}")
        print("  -- NARROW top families --")
        for f in r["narrow_top"][:6]:
            print(f"     {f['mib']:7.3f} MiB protos={f['protos']:5d} n={f['n']:6d} "
                  f"methods={f['methods'][:6]} eg={f['names'][:4]}")
        sys.stdout.flush()

    print("\n=== SUMMARY ===")
    tc = tw = tnr = tb = 0.0
    for r in results:
        tc += r["c_mib"]; tw += r["wide_mib"]; tnr += r["narrow_mib"]; tb += r["bare_mib"]
        print(f"  {r['app']:<18} C={r['c_mib']:7.3f}  WIDE={r['wide_mib']:7.3f}  "
              f"NARROW={r['narrow_mib']:7.3f}  BARE={r['bare_mib']:6.3f}  "
              f"protos={r['c_protos']:6d}")
    print(f"  {'TOTAL':<18} C={tc:7.3f}  WIDE={tw:7.3f}  NARROW={tnr:7.3f}  BARE={tb:6.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshots", nargs="+")
    ap.add_argument("--wide", type=int, default=20,
                    help="min prototype method count to classify as WIDE (default 20)")
    ap.add_argument("--threshold", type=int, default=1000,
                    help="min closures per shared Method to count as a native stub")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args()

    res = []
    for p in a.snapshots:
        if not os.path.exists(p):
            print(f"skip (missing): {p}", file=sys.stderr); continue
        try:
            res.append(analyze(p, a.wide, a.threshold))
        except Exception as e:
            print(f"error on {p}: {e}", file=sys.stderr)
    if not res:
        return 1
    if a.json:
        print(_json.dumps(res, indent=2, ensure_ascii=False))
    else:
        report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
