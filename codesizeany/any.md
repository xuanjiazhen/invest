# 二进制级 Code Size 优化分析：libcj_statvfs_ffi.z.so & libcj_file_fs_ffi.z.so

> 设备：HUAWEI Mate 60 Pro (ALN-AL00, 6.0.0.217)
> 来源：/system/lib64/platformsdk/

## 1. 总体 Size 对比

| 维度 | libcj_statvfs_ffi.z.so | libcj_file_fs_ffi.z.so |
|------|----------------------|----------------------|
| **文件大小** | 66 KB (67,352 B) | 793 KB (812,224 B) |
| **.text (代码)** | 35 KB (35,792 B) | 524 KB (533,008 B) |
| **导出符号数** | 44 | 453 |
| **NEEDED 依赖数** | 6 | 25 |
| **PLT 条目数** | 48 | 466 |
| **实际 FFI 入口** | 3 个 (`FfiOHOSStatvfs*`) | 97 个 (`FfiOHOS*`) |

## 2. 按段分析

### 2.1 libcj_file_fs_ffi.z.so (793KB) — 段大小 Top 10

| 段名 | 大小 | 占比 | 优化潜力 |
|------|------|------|---------|
| `.text` | 523.8 KB | 66.1% | 中（CFI + UBSan + 模板膨胀） |
| `.eh_frame` | 49.7 KB | 6.3% | **高**（-fno-unwind-tables） |
| `.dynstr` | 47.7 KB | 6.0% | **高**（-fvisibility=hidden） |
| `.gcc_except_table` | 26.1 KB | 3.3% | **高**（-fno-exceptions） |
| `_hilog_` | 24.3 KB | 3.1% | **高**（去重 + 裁剪 debug 日志） |
| `.data.rel.ro` | 23.5 KB | 3.0% | 中（vtable 精简） |
| `.dynsym` | 20.0 KB | 2.5% | **高**（-fvisibility=hidden） |
| `.gnu_debugdata` | 18.4 KB | 2.3% | **高**（strip release） |
| `.rela.plt` | 10.9 KB | 1.4% | 中（减少外部调用） |
| `.eh_frame_hdr` | 10.1 KB | 1.3% | **高**（随 .eh_frame 一起消减） |

### 2.2 libcj_statvfs_ffi.z.so (66KB) — 段大小 Top 5

| 段名 | 大小 | 占比 | 说明 |
|------|------|------|------|
| `.text` | 35.0 KB | 53.2% | 含 8KB libunwind 静态链接代码 |
| `.rodata` | 10.1 KB | 15.4% | 字符串常量 |
| `.eh_frame` | 3.5 KB | 5.3% | 异常展开表 |
| `.gnu_debugdata` | 2.9 KB | 4.4% | 压缩调试数据 |
| `.bss` | 2.8 KB | 4.3% | 未初始化数据 |

## 3. 关键发现

### 3.1 【statvfs】内嵌完整 libunwind 库 — 占 .text 的 22.6%

statvfs 的 .text 中静态链接了完整的 libunwind：

| 符号 | 地址 | 大小 | 说明 |
|------|------|------|------|
| `_Unwind_RaiseException` | 0x7138 | 0x320 (800B) | 异常抛出 |
| `_Unwind_ForcedUnwind` | 0x7af4 | 0xb4 (180B) | 强制展开 |
| `_Unwind_DeleteException` | 0x7d18 | 0x64 (100B) | 异常删除 |
| `_Unwind_Resume` | 0x7778 | 0xa4 (164B) | 异常恢复 |
| `_Unwind_GetGR/SetGR/GetIP/SetIP` | 0x7d7c-0x7f00 | ~400B | 寄存器操作 |
| `unw_getcontext/init_local/step/...` | 0x7f6c-0x8964 | ~3KB | libunwind API |
| `__unw_add/remove_dynamic_fde` | 0x8b34-0x9000 | ~1KB | 动态 FDE 管理 |
| `__cfi_check` | 0xe000 | 0xa0 (160B) | CFI 检查 |
| **合计 unwind 代码** | | **8,088 B** | **22.6% of .text** |

而实际 FFI 入口仅 3 个 8 字节 stub（`FfiOHOSStatvfsGetFreeSize/GetTotalSize` + 2 个 Impl 方法），占 .text 的 **0.08%**。

**根因**：编译时链接了 `-lunwind` 或 `-static-libunwind`，将整个 unwind 运行时静态链接进 .so。

### 3.2 【file_fs】CFI 检查点 14,082 处 — 估算占 .text ~8-12%

反汇编统计：`__cfi_check` 调用 **14,082 次**，`__cfi_slowpath` PLT 调用 **389 次**。

CFI（Control Flow Integrity）在每个间接函数调用前插入检查。每个检查约 4-8 字节代码 + 可能的 PLT 调用。

保守估算：14,082 × 6 字节 ≈ **82 KB CFI 代码**（占 524KB .text 的 ~15.7%）。

### 3.3 【file_fs】UBSan 运行时 — 不应在 release 中存在

发现 `__ubsan_handle_load_invalid_value_minimal_abort` 被调用 **67 次**，且 NEEDED 依赖中有 `libclang_rt.ubsan_minimal.so`。

UBSan（Undefined Behavior Sanitizer）是调试工具，不应出现在生产 .so 中。

### 3.4 【file_fs】std::string 析构 4,976 次 — 临时字符串膨胀

PLT 调用频率统计（反汇编全量）：

| PLT 函数 | 调用次数 | 说明 |
|----------|---------|------|
| `std::string::~string()` | **4,976** | 临时字符串析构 |
| `HiLogPrintDictNew` | 758 | 日志输出 |
| `HiLogIsLoggable` | 547 | 日志级别检查 |
| `__cfi_slowpath` | 389 | CFI 慢路径 |
| `_Unwind_Resume` | 351 | 异常恢复 |
| `__cxa_atexit` | 192 | 静态析构注册 |
| `NError::NError(int)` | 141 | 错误对象构造 |
| `NError::ThrowErr` | 126 | 错误抛出 |
| `operator delete` | 122 | 堆释放 |
| `std::string::string(const&)` | 100 | 字符串拷贝构造 |

**std::string 相关 PLT 调用总计 5,327 次**，其中析构占 93.4%。这意味着代码中大量创建临时 `std::string` 对象（错误消息、路径拼接、日志格式化）。

### 3.5 【file_fs】_hilog_ 段 24.3KB — 526 条嵌入日志格式串

`_hilog_` 段含 526 条 null 结尾的格式字符串，其中：

| 模式 | 出现次数 | 单条约 | 小计 |
|------|---------|--------|------|
| `[%{public}s:%{public}d->%{public}s] Failed to...` | 136 | ~60B | ~8KB |
| `FS_TEST::FfiOHOS*` (调试/测试用) | 43+ | ~50B | ~2KB |
| 其他唯一格式串 | 347 | ~40B | ~14KB |

### 3.6 【file_fs】异常处理数据 88KB

| 段 | 大小 | 说明 |
|----|------|------|
| `.eh_frame` | 49.7 KB | DWARF CFI 展开信息 |
| `.eh_frame_hdr` | 10.1 KB | 展开信息索引 |
| `.gcc_except_table` | 26.1 KB | C++ 异常处理表 |
| **合计** | **85.9 KB** | **10.8% of .so** |

配合 351 次 `_Unwind_Resume` 调用，说明代码大量使用 C++ 异常。

### 3.7 【file_fs】符号名膨胀 — 77% 为 C++ mangled

| 类型 | 数量 | 平均名长 | 小计 |
|------|------|---------|------|
| `_ZN*` (C++ mangled) | 264 | ~100B | ~26KB |
| `_Z*` (C++ mangled) | 84 | ~60B | ~5KB |
| `Ffi*` (C 接口) | 97 | ~25B | ~2.4KB |
| 其他 | 5 | ~10B | ~0.05KB |

`.dynstr` 总计 47.7KB，其中 C++ mangled 名占 ~31KB（65%）。最长名 211 字节。

## 4. 优化建议

### P0：编译选项调整（预计节省 ~200KB，file_fs 25%）

| 优化项 | 编译选项 | 预计节省 | 影响范围 |
|--------|---------|---------|---------|
| **禁用 UBSan** | `-fno-sanitize=undefined` + 移除 `libclang_rt.ubsan_minimal.so` NEEDED | ~5 KB + 去一个依赖 | file_fs |
| **禁用 CFI** | `-fno-sanitize=cfi -fno-sanitize-cfi-cross-dso` | ~82 KB (.text) + 去 `__cfi_check` 代码 | file_fs, statvfs |
| **禁用异步展开表** | `-fno-asynchronous-unwind-tables` | ~60 KB (.eh_frame + .eh_frame_hdr) | file_fs |
| **禁用异常** | `-fno-exceptions` | ~26 KB (.gcc_except_table) + 减少 _Unwind_Resume 调用 | file_fs |
| **隐藏内部符号** | `-fvisibility=hidden` + `__attribute__((visibility("default")))` 仅标 Ffi* | ~65 KB (.dynstr + .dynsym + .gnu.version + .gnu.hash) | file_fs |
| **strip 调试数据** | `strip --remove-section .gnu_debugdata` 或编译时不生成 | ~18 KB | 两者 |

**file_fs 合计预计节省：~256 KB（793KB → ~537KB，减少 32%）**

### P1：代码层面优化（预计额外节省 ~50KB）

| 优化项 | 方法 | 预计节省 |
|--------|------|---------|
| **减少临时 std::string** | 错误消息改用 `string_view` 或 `const char*`；路径拼接用 `snprintf` 到栈缓冲 | ~10 KB（减少 PLT + 内联析构代码） |
| **_hilog_ 格式串去重** | 136 条相同前缀的模式提取为共享常量 + 参数化 | ~8 KB |
| **裁剪 FS_TEST 调试日志** | `#ifdef NDEBUG` 包裹或 `--strip-debug-log` 编译选项 | ~2 KB |
| **减少 hilog 调用** | 1,305 次 hilog 调用（758 print + 547 check），合并同类日志、降级 debug 日志为编译期排除 | ~5 KB (.text) + ~3 KB (_hilog_) |
| **减少静态变量** | 192 个 `__cxa_atexit` 注册，合并静态状态或用 `constexpr` | ~3 KB |

### P2：statvfs 专项优化（预计节省 ~15KB，66KB → ~51KB）

| 优化项 | 方法 | 预计节省 |
|--------|------|---------|
| **去除静态链接 libunwind** | 改用系统 `libunwind.so`（`-lunwind` 动态链接）或 `-fno-unwind-tables -fno-exceptions` | ~8 KB (.text) + ~4 KB (.eh_frame) |
| **strip 调试数据** | 移除 `.gnu_debugdata` | ~3 KB |
| **精简 .rodata** | 10KB 字符串常量中可能含重复错误消息，去重 | ~2 KB |
| **去除 CFI** | `-fno-sanitize=cfi` | ~1 KB |

**statvfs 合计预计节省：~18 KB（66KB → ~48KB，减少 27%）**

## 5. 优化效果汇总

| .so | 当前大小 | P0 后 | P0+P1 后 | 减少比例 |
|-----|---------|-------|----------|---------|
| libcj_file_fs_ffi.z.so | 793 KB | ~537 KB | ~487 KB | **-38.6%** |
| libcj_statvfs_ffi.z.so | 66 KB | ~53 KB | ~48 KB | **-27.3%** |

## 6. 优化优先级建议

1. **立即执行**（零代码改动，仅编译选项）：
   - `-fno-sanitize=undefined,cfi` — 去 UBSan + CFI
   - `-fvisibility=hidden` — 隐藏内部符号
   - `-fno-asynchronous-unwind-tables` — 去异步展开表
   - `strip --remove-section .gnu_debugdata` — 去调试数据

2. **短期**（少量代码改动）：
   - `-fno-exceptions` — 需将 `throw/catch` 改为错误码返回
   - `_hilog_` 格式串去重
   - 裁剪 `FS_TEST::` 调试日志

3. **中期**（较多代码改动）：
   - `std::string` → `std::string_view` / `const char*`
   - 减少静态变量
   - statvfs 去静态 libunwind 依赖

4. **长期**（架构层面）：
   - 评估 25 个 NEEDED 依赖是否可合并或延迟加载
   - 评估 453 个导出符号中是否有从未被 Cangjie 侧调用的死代码
   - 考虑按功能域拆分为多个更小的 .so（如 file_io / file_watch / file_stat 分别独立）

---

# 7. PR #2072 对照分析

> PR: https://gitcode.com/openharmony/filemanagement_file_api/pull/2072
> 标题: "romsize compiler" / "fix: reduce code size"
> 分析范围: `interfaces/kits/cj` 目录

## 7.1 PR 实际采纳的优化项

| any.md 建议 | PR 变更 | 预估节省 |
|-------------|---------|---------|
| P0: 禁用异步展开表 `-fno-asynchronous-unwind-tables` | ✅ 新增 `-fno-asynchronous-unwind-tables` + `-fno-unwind-tables`（file_fs + statvfs） | ~60KB |
| P0: 禁用异常 `-fno-exceptions` | ✅ 新增 `-fno-exceptions`, `use_exceptions = false`（file_fs + statvfs） | ~30KB |
| P2: statvfs 去 libunwind | ✅ 随 `-fno-exceptions` + `-fno-unwind-tables` 自动消除 | ~8KB |
| P1: 裁剪 FS_TEST:: 调试日志 | ✅ 删除大量 `LOGI("FS_TEST::...")` 行（81% LOGI 为 FS_TEST 前缀） | ~5KB |
| P0: 隐藏内部符号 | ⚠️ 已有 `-fvisibility=hidden`，PR 新增 `-fvisibility-inlines-hidden` | ~2KB |
| 代码去重（copy/copy_dir） | ✅ 提取 `CommonFilterFunc`/`CommonMakeDir`/`VectorToCArrString` 到 `utils.cpp` | ~5KB |
| LTO + ICF + GC sections | ✅ 新增 `-flto` + `-Wl,--icf=all` + `-Wl,--gc-sections` | ~20KB |
| 合并常量 `-fmerge-all-constants` | ✅ 新增（file_fs + statvfs） | ~5KB |
| `-fno-rtti` + `-fno-threadsafe-statics` | ✅ 新增 | ~5KB |
| `stat_impl.h` inline → 非 inline | ✅ 14 个成员函数移入 `stat_impl.cpp` | ~2KB |
| `uni_error.h` 全局表 → extern | ✅ 3 个大表从 inline 移至 `uni_error.cpp` | ~5KB |

**PR 合计预估节省: file_fs ~130-140KB (793→~653KB, -17.7%), statvfs ~10-12KB (66→~54KB, -18.2%)**

## 7.2 PR 未采纳的优化项（仍可继续优化）

### 仍存在的高收益项（零代码改动）

| 优先级 | any.md 建议 | 当前 BUILD.gn 状态 | 预估节省 |
|--------|-----------|-------------------|---------|
| 🔴 P0 | **禁用 UBSan** | ❌ `ubsan = true`, `integer_overflow = true`, `boundary_sanitize = true` 均保留 | ~5KB + 移除 `libclang_rt.ubsan_minimal.so` NEEDED |
| 🔴 P0 | **禁用 CFI** | ❌ `cfi = true`, `cfi_cross_dso = true` 均保留（14,082 个检查点） | ~82KB |
| 🟡 P0 | **strip .gnu_debugdata** | ❌ 未处理 | ~18KB (file_fs) + ~3KB (statvfs) |

**三项合计: file_fs ~105KB, statvfs ~3KB — 均为 BUILD.gn 配置项，无需改动 C++ 代码。**

### 仍存在的中等收益项（少量代码改动）

| 优先级 | any.md 建议 | 当前状态 | 预估节省 |
|--------|-----------|---------|---------|
| 🟡 P1 | **_hilog_ 格式串去重** | ❌ 未处理。136 条相同前缀的模式可提取为共享常量 | ~8KB |
| 🟡 P1 | **减少 hilog 调用** | ⚠️ 仅删除了 LOGI（~100+），LOGE 397 条全保留。758+547 = 1305 hilog 调用 | ~8KB |
| 🟡 P1 | **残余 LOGI** | ⚠️ 约 42 条非 FS_TEST LOGI 未删除（如 `file_ffi.cpp` 15 条、`stat_ffi.cpp` 23 条） | ~2KB |

### 仍存在的高工作量项

| 优先级 | any.md 建议 | 当前源码状态 | 预估节省 |
|--------|-----------|-------------|---------|
| 🟢 P1 | **减少临时 std::string** | ❌ `std::string` 166 处 vs `std::string_view` 仅 5 处 | ~10KB |
| 🟢 P1 | **减少静态变量** | ❌ 192 个 `__cxa_atexit` | ~3KB |

## 7.3 优化效果预测

| .so | 旧版本 | PR 后 | +剩余 P0 | +剩余 P0+P1 | 总缩减 |
|-----|-------|-------|----------|------------|-------|
| libcj_file_fs_ffi.z.so | 793 KB | ~653 KB | ~548 KB | ~520 KB | **-34.4%** |
| libcj_statvfs_ffi.z.so | 66 KB | ~54 KB | ~51 KB | ~48 KB | **-27.3%** |

## 7.4 建议下一步

1. **立即执行**（仅 BUILD.gn，零 C++ 改动）：
   ```gn
   sanitize = {
     integer_overflow = false  # was true
     ubsan = false             # was true
     boundary_sanitize = false # was true
     cfi = false               # was true
     cfi_cross_dso = false     # was true
     debug = false
   }
   ```
   预计节省 ~87KB (file_fs) + ~1KB (statvfs)。

2. **短期**（构建脚本）：
   - `strip --remove-section .gnu_debugdata` 去除压缩调试数据
   - 预计节省 ~21KB

3. **中期**（少量代码改动）：
   - `_hilog_` 格式串去重：将 136 条相同前缀 `[%{public}s:%{public}d->%{public}s] Failed to...` 提取为宏或公共常量
   - 残余 `FS_TEST::` LOGI 清理
   - 预计节省 ~18KB

4. **长期**（架构考量）：
   - `std::string` → `std::string_view` 逐步迁移（当前比例 166:5）
   - 评估 UBSan/CFI 是否在所有构建配置中都需要（debug-only？）
