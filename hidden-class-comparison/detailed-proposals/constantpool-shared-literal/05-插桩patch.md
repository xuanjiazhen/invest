# 插桩 Patch：worker 场景调研与字面量占比归因

目的：补齐两个前置量化项——①子方向 A 的乘数（进程内并发 VM 数 × 每 VM 加载同 abc 的重合度）；②子方向 B 的基数（对象/数组字面量在 js_object/js_array 中的规模与归属 abc）。由系统参数 `persist.ark.propf.census`（示例名）开关。

## Patch 1：VM 生命周期与 abc 加载矩阵（子方向 A 乘数）

**文件**：`arkcompiler/ets_runtime/ecmascript/ecma_vm.cpp`、`jspandafile/js_pandafile_manager.cpp`

**位置 1**：`EcmaVM::EcmaVM`（构造函数尾部）与 `EcmaVM::~EcmaVM`。

```cpp
// 构造：记录 VMId（进程内递增）、isWorker（由 RuntimeOption 的 worker 标志传入）、创建时刻
Census::LogEvent("vm_create", vmId, isWorker, nowMs);
// 析构：Census::LogEvent("vm_destroy", vmId, nowMs);
```

**位置 2**：`JSPandaFileManager` 的 abc 打开/缓存命中路径（`LoadPandaFile`/`OpenPandaFile` 系列，`js_pandafile_manager.cpp`）。

```cpp
// 首次加载与命中均记录：Census::LogEvent("abc_load", vmId, pandaFileHash64, isNew);
// pandaFileHash64 取文件路径的 hash 或 IndexHeader 摘要，避免落盘明文路径
```

**输出与换算**：进程存续期事件流汇成 `vm × abc` 关联矩阵；对每个 abc 计算**并发重叠窗口数** `k(abc)`（同时存活且加载了该 abc 的 VM 数最大值），则：

```text
子方向 A 上界收益 = Σ_abc (k(abc) − 1) × 该 abc 的 CP 字符串字节数
```

abc 级 CP 字符串字节数由 Patch 3 输出。`Σ(k−1)==0` 即撤项判据。

## Patch 2：字面量创建计数（子方向 B 基数）

**文件**：`arkcompiler/ets_runtime/ecmascript/object_factory.cpp`

**位置**：`CloneObjectLiteral`（:517）与 `CloneArrayLiteral`（:539）入口。

```cpp
JSHandle<JSObject> ObjectFactory::CloneObjectLiteral(JSHandle<JSObject> object)
{
    if (UNLIKELY(Census::Enabled())) {
        // 当前解释帧函数 → Method → ConstantPool → JSPandaFile，取 abc 归属
        Census::CountLiteral(vmId, thread_->GetInterpreterFrameMethod(), OBJ_LITERAL, object->GetJSHClass()->GetObjectSize());
    }
    ...
```

`GetInterpreterFrameMethod` 以目标 revision 实际接口为准（解释态从 InterpretedFrame 取 function→Method；非解释态跳过归因只计数）。输出：`(abc, literalKind) → {count, sumShallowSize, avgSize}`。

**口径**：该计数度量的是**创建频次**（时间成本/COW 化收益上限），驻留存量（js_object 83.69 MiB 中字面量占比）需 Patch 4 的 dump 侧归因。

## Patch 3：abc 级 ConstantPool 字符串字节

**文件**：`arkcompiler/ets_runtime/ecmascript/jspandafile/program_object.cpp`

**位置**：ConstantPool 字符串条目 resolve 路径（`GetConstantPool`/字符串条目 GetOrInternString 调用处）。

```cpp
// 首次 resolve 时：Census::CountCPString(vmId, cpOwnerPandaFileHash, stringBytes);
```

与 Patch 1 的 `k(abc)` 相乘即得子方向 A 收益；单独输出亦校验快照口径（Top13 单 VM 合计 15.38 MiB）。

## Patch 4：dump 侧字面量驻留归因（可选，debug 构建限定）

**文件**：`arkcompiler/ets_runtime/ecmascript/dfx/hprof/rawheap_dump.cpp`

**位置**：`IterateMarkedObjects`（:650 一带，对象表遍历）。

```cpp
// 对 JSObject/JSArray：沿 hclass → root HClass 的 ObjectLiteralHClass 缓存命中判定是否字面量 root
// （GetObjectLiteralRootHClass 产出的 root hclass 记录在 GlobalEnv 的缓存数组内，dump 时可比对）
// 命中则记 (literalKind, selfSize)，并经 elements/properties 边归入其模板 abc（可选：经 Method 边）
```

输出：`字面量驻留 MiB / js_object+js_array 驻留 MiB = 占比`，直接回填子方向 B 的空间收益基数。

## 汇总输出

```text
census: vms=<n> workers=<w> abcMatrixEntries=<m>
dupPotentialMiB=<Σ(k−1)×cpString>          # 子方向 A 收益（0 则撤项）
literalCreate=<obj:n,bytes|arr:n,bytes>     # 子方向 B 时间口径
literalResidentMiB=<x> of <objArrMiB>       # 子方向 B 空间口径（Patch 4）
cpStringTotalMiB=<y>                        # 校验 15.38 MiB 快照口径
```
