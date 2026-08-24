#!/usr/bin/env python3
"""Generate before/after core-flow comparison diagram for InternalAccessor->NAPI
migration (06 review doc). Single source of layout -> emits both .drawio and .svg
with identical coordinates. Rules: straight edges, explicit anchors, margins
(top/left>=30, bottom/right>=60), svg starts with '<svg xmlns=' and <100KB.
"""
import html

# ---------- palette ----------
BLUE_F, BLUE_S = "#dae8fc", "#1f6feb"    # existing path/structure
YELL_F, YELL_S = "#fff5cc", "#d4a017"    # new (migration)
RED_F, RED_S   = "#ffe0e0", "#c0392b"    # forbidden antipattern
GRAY_F, GRAY_S = "#f5f5f5", "#666666"    # off-heap / native side
PANEL_F, PANEL_S = "#fbfbfb", "#999999"

W, H = 1700, 1490

# ---------- nodes: id -> (x, y, w, h, lines, fill, stroke, bold_header?) ----------
def N(x, y, w, h, lines, fill=BLUE_F, stroke=BLUE_S, bold=False):
    return dict(x=x, y=y, w=w, h=h, lines=lines, fill=fill, stroke=stroke, bold=bold)

nodes = {
    # title
    "title": N(30, 20, 1600, 34, ["InternalAccessor 迁移 NAPI：核心流程与数据结构对比（修改前 / 修改后）"], PANEL_F, PANEL_S, True),
    # ---------- LEFT panel: before ----------
    "P1": N(30, 70, 780, 830, ["修改前：即时绑定（现状路径）"], PANEL_F, PANEL_S, True),
    "L1": N(60, 130, 350, 48, ["① napi_define_class", "native_api.cpp:1643"]),
    "L2": N(60, 198, 350, 48, ["② NapiDefineClass", "ark_native_engine.cpp:333"]),
    "L3": N(60, 266, 350, 64, ["③ NapiCreateClassFunction(:288)", "NapiGetKeysAndAttrsFromProps", "遍历 property_count(:250)"]),
    "L4": N(60, 350, 350, 48, ["④ NapiInitAttrValFromProp(:216)", "每个方法立即执行"]),
    "L5": N(60, 418, 350, 60, ["⑤ NapiNativeCreateFunction(:190)", "→ FunctionRef::NewConcurrentWithName", "(jsnapi_expo.cpp:3947)"]),
    "L6": N(60, 498, 350, 48, ["⑥ prototype 槽位 = 数据属性（JSFunction）"]),
    "LN": N(60, 600, 350, 60, ["注册即全量创建，与是否被访问无关", "Top13 Bucket C：447,707 方法闭包", "（61.47 MiB 上界）"], GRAY_F, GRAY_S),
    "LD": N(440, 230, 340, 210, ["注册即创建 · 每方法", "（无论是否被访问）", "—", "JSFunction 144 B（堆内）", "JSNativePointer 40 B（堆内）", "NapiFunctionInfo 32–40 B（堆外）", "descriptor 数组用后即弃", "＝ 堆内驻留 184 B/方法"], YELL_F, YELL_S),
    # ---------- RIGHT panel: after ----------
    "P2": N(850, 70, 820, 830, ["修改后：惰性绑定（迁移路径，06 §3–§4）"], PANEL_F, PANEL_S, True),
    "PA": N(880, 120, 300, 26, ["A. 注册期（惰性化）"], YELL_F, YELL_S, True),
    "R1": N(880, 152, 360, 48, ["① napi_define_class → NapiDefineClass", "注册期开关控制惰性化（sendable 排除）"], YELL_F, YELL_S),
    "R2": N(880, 220, 360, 64, ["② descriptor 深拷贝 → ClassBindingLifetime", "（堆外）descriptor 表 + slotState 状态机", "+ env cleanup 所有权"], YELL_F, YELL_S),
    "R3": N(880, 304, 360, 56, ["③ prototype 方法槽装 NapiLazyAccessor", "32 B = getter/setter 裸指针 + payload", "（lifetimeId, descIndex）—— 06 §3.3 X1"], YELL_F, YELL_S),
    "PB": N(880, 380, 380, 26, ["B. 首次读取 materialize（06 §4.2–4.3）"], BLUE_F, BLUE_S, True),
    "R4": N(880, 412, 360, 60, ["④ proto.m 读取 → property lookup 慢路径", "IsInternal() → CallInternalGet", "(object_fast_operator-inl.h:1080-1082)"]),
    "R5": N(880, 492, 360, 48, ["⑤ getter 解码 payload → 取 descriptor", "slot 状态机 LAZY → MATERIALIZING"], YELL_F, YELL_S),
    "R6": N(880, 560, 360, 60, ["⑥ 复用现行链 NapiNativeCreateFunction", "JSFunction / JSNativePointer /", "NapiFunctionInfo 此刻才创建"]),
    "R7": N(880, 640, 360, 60, ["⑦ 写回：SetProperty 等价路径", "+ MarkProtoChanged 原型链失效", "(js_hclass-inl.h:379-399)"]),
    "R8": N(880, 730, 360, 48, ["⑧ 之后：数据属性 + 正常 IC", "与修改前不可区分"]),
    "RD": N(1250, 200, 370, 150, ["未访问方法驻留（新）", "—", "NapiLazyAccessor 32 B（堆内）", "descriptor 深拷贝摊派 72–96 B", "（堆外，ClassBindingLifetime）"], YELL_F, YELL_S),
    "RUN": N(1250, 560, 370, 90, ["禁止照搬：ResetLazyInternalAttr", "原地改共享 LayoutInfo attr", "（内建场景专属，D2 反模式）"], RED_F, RED_S),
    "RUL": N(1250, 680, 370, 90, ["module unload：env cleanup 释放", "未物化 descriptor；DEAD 态", "防悬空 getter（06 §4.5）"], GRAY_F, GRAY_S),
    # ---------- BOTTOM panel: data structures ----------
    "P3": N(30, 930, 1640, 420, ["关键数据结构创建对比（06 §5.4 / §7.1）"], PANEL_F, PANEL_S, True),
    "C1T": N(70, 975, 380, 26, ["修改前 · 每方法注册即建"], BLUE_F, BLUE_S, True),
    "B1a": N(70, 1008, 180, 64, ["JSFunction", "144 B（堆内）"]),
    "B1b": N(260, 1008, 180, 64, ["JSNativePointer", "40 B（堆内）"]),
    "B1c": N(70, 1084, 370, 52, ["NapiFunctionInfo 32–40 B（堆外，注册即建）"], GRAY_F, GRAY_S),
    "B1s": N(70, 1148, 370, 40, ["堆内 184 B/方法 · 堆外 32–40 B/方法"]),
    "C2T": N(520, 975, 380, 26, ["修改后 · 未访问方法驻留"], YELL_F, YELL_S, True),
    "B2a": N(520, 1008, 380, 100, ["NapiLazyAccessor 32 B（堆内）", "Record 8 + getter 8 + setter 8 + payload 8", "payload = Smi(lifetimeId<<16 | descIndex)", "（内建 InternalAccessor 24 B 无 payload）"], YELL_F, YELL_S),
    "B2b": N(520, 1120, 380, 52, ["descriptor 深拷贝 72–96 B（堆外，ClassBindingLifetime）"], GRAY_F, GRAY_S),
    "C3T": N(960, 975, 380, 26, ["修改后 · 首次访问后（materialize 完成）"], BLUE_F, BLUE_S, True),
    "B3a": N(960, 1008, 380, 100, ["与修改前完全一致：", "JSFunction + JSNativePointer（堆内 184 B）", "NapiFunctionInfo（堆外）", "写回同一对象（proto.m === proto.m）"]),
    "NET": N(70, 1210, 1520, 64, ["净效果（每未访问方法）：堆内 184 → 32 B（−152 B，−83%）｜堆外 +32–64 B", "descriptor 驻留超过消除量 20% 时，静态存储期契约（零拷贝）转主路径（06 §4.6/§5.4）"], YELL_F, YELL_S),
    "LEG": N(30, 1375, 1640, 44, ["图例：蓝＝既有路径/结构（不改动）｜黄＝迁移新增｜红＝禁止照搬（D2 反模式）｜灰＝堆外/native 侧", "源数据：06-InternalAccessor迁移NAPI设计评审.md（冻结基线 ets_runtime@f04900cf）"], PANEL_F, PANEL_S),
}

# ---------- edges: (src, dst, ex,ey, enx,eny, label, color, dashed) ----------
E = BLUE_S
edges = [
    ("L1","L2",0.5,1,0.5,0,"",E,False), ("L2","L3",0.5,1,0.5,0,"",E,False),
    ("L3","L4",0.5,1,0.5,0,"",E,False), ("L4","L5",0.5,1,0.5,0,"",E,False),
    ("L5","L6",0.5,1,0.5,0,"",E,False),
    ("L5","LD",1,0.5,0,0.5,"每方法创建",E,False),
    ("R1","R2",0.5,1,0.5,0,"",E,False), ("R2","R3",0.5,1,0.5,0,"",E,False),
    ("R3","R4",0.5,1,0.5,0,"首读触发",E,False),
    ("R4","R5",0.5,1,0.5,0,"",E,False), ("R5","R6",0.5,1,0.5,0,"",E,False),
    ("R6","R7",0.5,1,0.5,0,"",E,False), ("R7","R8",0.5,1,0.5,0,"",E,False),
    ("R3","RD",1,0.5,0,0.5,"驻留",E,False),
    ("R7","RUN",1,0.5,0,0.5,"不可照搬",RED_S,True),
    ("B1s","B2a",1,0.5,0,0.5,"惰性化",E,False),
    ("B2b","B3a",1,0.5,0,0.5,"materialize",E,False),
]

def anchor(nid, fx, fy):
    n = nodes[nid]
    return n["x"] + n["w"] * fx, n["y"] + n["h"] * fy

# ---------- SVG ----------
def esc(s):
    return html.escape(s, quote=True)

svg = []
svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,’Microsoft YaHei’,sans-serif">')
svg.append('<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker></defs>' % "#333333")
svg.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

def text_block(x, y, w, h, lines, bold=False, size=12):
    cx, cy = x + w / 2, y + h / 2
    n = len(lines)
    lh = size + 5
    y0 = cy - (n - 1) * lh / 2 - size * 0.36
    weight = ' font-weight="bold"' if bold else ''
    out = [f'<text x="{cx:.0f}" y="{y0:.0f}" text-anchor="middle" fill="#333333" '
           f'font-size="{size}"{weight}>']
    for i, ln in enumerate(lines):
        if i == 0:
            out.append(f'  <tspan x="{cx:.0f}" dy="0">{esc(ln)}</tspan>')
        else:
            out.append(f'  <tspan x="{cx:.0f}" dy="{lh}">{esc(ln)}</tspan>')
    out.append('</text>')
    return "\n".join(out)

for nid, n in nodes.items():
    hdr = n["bold"] and nid in ("P1", "P2", "P3")
    if nid in ("P1", "P2", "P3"):
        # panel: rect + header band
        svg.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" '
                   f'fill="{n["fill"]}" stroke="{n["stroke"]}" stroke-width="1.5" rx="4"/>')
        svg.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="30" '
                   f'fill="#eef1f4" stroke="{n["stroke"]}" rx="4"/>')
        svg.append(text_block(n["x"], n["y"], n["w"], 30, n["lines"], bold=True, size=13))
    else:
        svg.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" '
                   f'fill="{n["fill"]}" stroke="{n["stroke"]}" rx="6" stroke-width="1.4"/>')
        size = 11 if nid in ("PA", "PB", "C1T", "C2T", "C3T", "LEG") else 12
        svg.append(text_block(n["x"], n["y"], n["w"], n["h"], n["lines"], bold=n["bold"], size=size))

for (s, t, ex, ey, nx, ny, label, color, dashed) in edges:
    x1, y1 = anchor(s, ex, ey)
    x2, y2 = anchor(t, nx, ny)
    dash = ' stroke-dasharray="7 5"' if dashed else ''
    svg.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
               f'stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#arr)"/>')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        svg.append(f'<rect x="{mx-34:.0f}" y="{my-9:.0f}" width="68" height="16" fill="#ffffff" '
                   f'fill-opacity="0.85" stroke="none"/>')
        svg.append(f'<text x="{mx:.0f}" y="{my+4:.0f}" text-anchor="middle" font-size="10" '
                   f'fill="{color}">{esc(label)}</text>')

svg.append('</svg>')
svg_text = "\n".join(svg)

# ---------- drawio ----------
def dval(lines):
    return esc("\n".join(lines)).replace("\n", "&#xa;")

mx = []
mx.append('<mxfile host="app.diagrams.net" modified="2026-08-20T00:00:00.000Z" agent="generator" version="24.0.0">')
mx.append('  <diagram id="core-before-after" name="核心流程对比">')
mx.append(f'    <mxGraphModel dx="1700" dy="1490" grid="1" gridSize="10" page="1" pageWidth="{W}" pageHeight="{H}">')
mx.append('      <root>')
mx.append('        <mxCell id="0"/>')
mx.append('        <mxCell id="1" parent="0"/>')

def dstyle(n):
    st = "rounded=1;whiteSpace=wrap;html=1;"
    if n["bold"]:
        st += "fontStyle=1;"
    st += f'fillColor={n["fill"]};strokeColor={n["stroke"]};'
    return st

for nid, n in nodes.items():
    if nid in ("P1", "P2", "P3"):
        st = (f'swimlane;startSize=30;verticalAlign=top;whiteSpace=wrap;html=1;fontStyle=1;'
              f'fillColor={n["fill"]};strokeColor={n["stroke"]};')
    else:
        st = dstyle(n)
    mx.append(f'        <mxCell id="{nid}" value="{dval(n["lines"])}" style="{st}" vertex="1" parent="1">')
    mx.append(f'          <mxGeometry x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" as="geometry"/>')
    mx.append('        </mxCell>')

for i, (s, t, ex, ey, nx, ny, label, color, dashed) in enumerate(edges):
    st = (f'endArrow=block;endFill=1;strokeColor={color};fontSize=10;'
          f'exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={nx};entryY={ny};entryDx=0;entryDy=0;')
    if dashed:
        st += 'dashed=1;'
    mx.append(f'        <mxCell id="e{i}" value="{esc(label)}" style="{st}" edge="1" source="{s}" target="{t}" parent="1">')
    mx.append('          <mxGeometry relative="1" as="geometry"/>')
    mx.append('        </mxCell>')

mx.append('      </root>')
mx.append('    </mxGraphModel>')
mx.append('  </diagram>')
mx.append('</mxfile>')
mx_text = "\n".join(mx)

import sys, os
out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
base = "napi-lazy-binding-before-after-core"
open(os.path.join(out_dir, base + ".svg"), "w", encoding="utf-8", newline="\n").write(svg_text)
open(os.path.join(out_dir, base + ".drawio"), "w", encoding="utf-8", newline="\n").write(mx_text)
print("svg head ok:", svg_text.startswith("<svg xmlns="), "| svg bytes:", len(svg_text.encode()),
      "| drawio bytes:", len(mx_text.encode()))
