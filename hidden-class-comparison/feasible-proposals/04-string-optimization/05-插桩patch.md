# 插桩 Patch：字符串收益预估（去重率 + intern 命中率）

目的：回填 01-requirement 的收益预估两个未知数——短字符串**重复率**（dedup 收益乘数）与 intern **命中率**（增量 intern 的可省量）。系统参数 `persist.ark.propf.strprobe`（示例名）开关。

## 口径修正（本轮核验，先于插桩成立）

快照中 string 节点 `self_size` = `EcmaStringAccessor(str).GetLength()`（`rawheap_dump.cpp:651-653`），**是字符数而非对象尺寸**：数据区 83.03 MiB 之外，2,281,554 个字符串对象还携带 ~43 MiB 头部+对齐（LineString 头 16 B = TaggedObject 8 + LengthAndFlags 4 + MixHashcode 4，`base_string.h:124-131`），真实堆占用模型 ≈ **126 MiB**。len≤16 的短串占 54.3%（1,238,647 个）却只装 10.75 MiB 数据——**头部开销是短串的主体成本**，这是 dedup/intern 的收益来源。

## Patch 1：dump 时全量去重率统计（核心数字，debug 构建限定）

**文件**：`arkcompiler/ets_runtime/ecmascript/dfx/hprof/rawheap_dump.cpp`

**位置**：`RawHeapDumpV1::DumpObjectTable`（:643，字符串分支已在此汇聚）。

```cpp
if (obj->GetClass()->IsString()) {
    ...
    if (UNLIKELY(StrProbe::Enabled())) {
        EcmaString *str = EcmaString::Cast(obj);
        uint32_t len = EcmaStringAccessor(str).GetLength();
        if (len <= StrProbe::MAX_LEN /* 建议档位 8/16/32 */ ) {
            // 读内容做 hash（压缩串按字节，UTF16 串按 u16）插入 CUnorderedSet<uint64_t>
            // 冲突时逐字节比对去歧义；同时累计该长度桶的 total/duplicate 字节（含 16B 头）
            StrProbe::Count(len, hashOfContent(str), isDup);
        }
    }
}
```

**输出**：

```text
strprobe: bucket  nTotal  nDup  dupRatio  bytesTotal(incl header)  bytesDup(incl header)
          <=8      ...    ...    x%           ...                     ...
          <=16     ...    ...    y%           ...                     ...
```

`bytesDup(incl header)` 即短串 dedup 的直接收益：`收益 = dupRatio × (data 10.75 MiB + header ≈18.9 MiB)`（≤16 桶，dupRatio 为实测值 y%）。

## Patch 2：运行时 intern 命中率（采样）

**文件**：`arkcompiler/ets_runtime/ecmascript/ecma_string_table.cpp`（`EcmaStringTable::GetOrInternString` 系列，声明见 `ecma_string_table.h:247-253`）

```cpp
EcmaString *EcmaStringTable::GetOrInternString(EcmaVM *vm, EcmaString *string)
{
    // 表查找命中/未命中处各加一个 atomic 计数，按 string 长度桶（<=8/<=16/<=64/>64）分桶；
    // 每 2^16 次方落一条 hilog 汇总，热路径仅两次 fetch_add
}
```

**输出**：`intern: bucket<=16 hit=x% miss=y% ...`——衡量「创建期即时 intern 短串」可拦截的重复创建比例，与 Patch 1 的存量 dupRatio 互相印证。

## 验证思路

1. 原型实现「len≤T 即时 intern（表容量上限 + 超限回退不 intern）」后复跑 Patch 1：≤T 桶 dupRatio 应降至 ≈0，字符串对象数下降量 × 32 B（16B 头 + 对齐均摊）≈ 实测收益；
2. PSS 与浅层堆双口径 A/B（≥5 次），intern 表锁开销以冷启动 P50 与字符串密集 workload（JSON parse）实测；
3. >1K 长串（数据 32.63 MiB）不在本 VM 方案内，转应用侧归因（`02-app-side-consolidated/`）。
