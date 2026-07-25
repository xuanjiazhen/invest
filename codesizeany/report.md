# PR #2072 分析报告

> 分析目标: https://gitcode.com/openharmony/filemanagement_file_api/pull/2072
> 分析范围: `interfaces/kits/cj` 目录
> 分析日期: 2026-06-27

---

## 一、二进制兼容性分析

### 1.1 编译标志变更 — 🔴 高风险

PR 对 `cj_file_fs_ffi` 和 `cj_statvfs_ffi` 两个 `ohos_shared_library` 目标新增以下编译标志：

| 标志 | 风险 | 说明 |
|------|------|------|
| `-fno-exceptions` | 🔴 高 | `use_exceptions: true → false`。若公开 API 曾抛 C++ 异常并被调用方 catch，改为 `abort()`。内部 `js_common_src` source_set 保留异常支持（隔离在 .so 内部），需确认无异常跨越 .so 边界 |
| `-flto` + `-Wl,--gc-sections` | 🔴 高 | LTO 跨 TU 内联 + 无用段裁剪。可能移除外部依赖的符号。建议运行 `abidiff` 对比新旧 .so 导出符号 |
| `-Wl,--icf=all` | 🔴 高 | Identical Code Folding 将相同函数合并，违反 C++ 标准的函数指针唯一性要求。若外部代码对库内函数指针做相等比较会出错 |
| `-fno-rtti` | 🟡 中 | `dynamic_cast`/`typeid` 不可用。若外部对库类型做 RTTI 操作则失败 |

### 1.2 符号可见性变更 — 🟡 中风险

**`uni_error.h` 三个全局映射表 `static inline` → `extern`：**
- `softbusErr2ErrCodeTable`、`uvCode2ErrCodeTable`、`errCodeTable` 原为 `static inline`（每个 TU 内联副本），迁移至 `uni_error.cpp` 作为 `extern` 导出符号
- 旧编译调用方不受影响（已有内联副本）
- 新编译但链接旧 .so → 符号缺失，链接失败
- 本质是 ABI 新增而非断裂，但要求同步更新

**`stat_impl.h` 14 个成员函数 `inline` → 非 inline：**
- `GetIno/GetMode/GetUid/GetGid/GetSize/GetAtime/GetMtime/GetCtime` 及 `IsBlockDevice/IsCharacterDevice/IsDirectory/IsFIFO/IsFile/IsSocket/IsSymbolicLink/CheckStatMode`
- 从头文件内联移至 `stat_impl.cpp` 作为外部符号
- ABI 新增（旧调用方已内联不受影响），新编译需新版 .so

### 1.3 其他变更 — 🟢 低风险

| 变更 | 说明 |
|------|------|
| `FILE_DISMATCH`/`FILE_MATCH` 移至 `utils.h` | `constexpr` 编译期常量，无 ABI 影响 |
| `file_utils.h` → `cj_file_utils.h` | 新头文件（`new (std::nothrow)` 版模板，适配 `-fno-exceptions`） |
| `defines = ["FILE_API_TRACE"]` 移除 | 条件编译宏消失，可能改变行为 |
| 源文件移入 `source_set` | 等效静态链接，符号表等价 |
| 大量 `LOGI("FS_TEST::...")` 删除 | 纯运行时行为，减小二进制体积 |

### 1.4 兼容性结论

**存在二进制兼容性风险**，主要来自编译标志变更（`-fno-exceptions` / `-flto` / `--icf=all`）。建议：
1. 合并前用 `abidiff` 对比新旧 `.so` 导出符号
2. 验证无异常跨越 .so 边界
3. 确认所有下游消费者功能正常

---

## 二、额外 Code Size 优化空间

### 2.1 `copy.cpp` 与 `copy_dir.cpp` 重复函数 — PR 已部分解决

源码比对确认以下函数**完全相同或高度相似**：

| 函数 | copy.cpp | copy_dir.cpp | 状态 |
|------|----------|--------------|------|
| `FilterFunc` | L118 | L103 | **完全相同** → PR 提取为 `CommonFilterFunc` 到 `utils.cpp` |
| `Deleter(NameList*)` | L131 | L59 | 高度相似（差 2 行 `delete arg`）→ PR 用 `NameListArgDeleter` 替代 |
| `MakeDir` | L219 | L32 | **完全相同** → PR 提取为 `CommonMakeDir` 到 `utils.cpp` |
| `CopySubDir` | L230 | L90 | 签名不同但逻辑相似 |
| `RecurCopyDir` | L266 | L29+L111 | 逻辑相似 |
| `CopyDirFunc` | L307 | L163 | 逻辑相似 |
| `SendFileCore` | L75 | L96 | 相似（`copy_file.cpp` 另有独立版本） |

**评价**: PR 的 `utils.cpp` 新增 `CommonFilterFunc`/`CommonMakeDir`/`NameListArgDeleter`/`VectorToCArrString` 等共享工具函数方向正确，但 `CopySubDir`/`RecurCopyDir`/`CopyDirFunc` 仍有合并空间。

### 2.2 `file_fs_ffi.cpp` 调试日志 — PR 已大幅削减

| 指标 | 当前值 |
|------|--------|
| `file_fs_ffi.cpp` LOGI 密度 | **11.1%**（101/908 行） |
| `stat_ffi.cpp` LOGI 密度 | **7.8%**（23/295 行） |
| 全目录 LOGI 总数 | **220 条**（9135 行总代码） |

PR 删除了大量 `LOGI("FS_TEST::...")` 行。建议继续清理剩余的 `FS_TEST::` 前缀 LOGI（release 构建中可考虑用宏在编译期剔除）。

### 2.3 微小 .cpp 文件合并 — 未处理

以下文件代码行数极少，每个产生独立的 `.o` 文件（ELF 头部、符号表等固定开销）：

| 文件 | 总行数 | 实际代码行 |
|------|--------|-----------|
| `task_signal_impl.cpp` | 41 | ~11 |
| `fdatasync.cpp` | 48 | ~13 |
| `fsync.cpp` | 48 | ~15 |
| `symlink.cpp` | 51 | ~15 |
| `uni_error.cpp` | 48 | ~15 |
| `lseek.cpp` | 52 | ~17 |
| `statvfs_impl.cpp` | 49 | ~19 |
| `statvfs_ffi.cpp` | 51 | ~20 |
| `stat_impl.cpp` | 62 | ~22 |
| `readerIterator_impl.cpp` | 52 | ~22 |
| `mkdtemp.cpp` | 67 | ~26 |
| `xattr_ffi.cpp` | 61 | ~26 |

**建议**: 将 `fdatasync.cpp` + `fsync.cpp`（几乎相同，仅 `uv_fs_fdatasync` vs `uv_fs_fsync`）合并为一个文件。其他微型文件可合并到已有的较大文件中（如 `file_fs_impl.cpp`）。

### 2.4 `copy.h` 头文件内联方法 — 未处理

`copy.h`（179 行，6.8KB）中的 struct 包含多个内联方法：

```cpp
struct CjCallbackObject {
    explicit CjCallbackObject(int64_t id) : callbackId(id) { /* ~15 行构造函数 */ }
    void CloseFd() { /* ~15 行 */ }
    ~CjCallbackObject() { CloseFd(); }
};

struct FileInfos {
    bool operator==(const FileInfos &infos) const { /* ... */ }
    bool operator<(const FileInfos &infos) const { /* ... */ }
};
```

这些方法在头文件中内联，每个包含 `copy.h` 的 TU 都会编译一份。移入 `copy.cpp` 可减少跨 TU 重复。

### 2.5 重复 include 头文件 — 低优先级

`macro.h`（12 处引用）、`uni_error.h`（9 处）、`file_fs_impl.h`（8 处）被大量文件包含。可考虑合并小型头文件为公共 `cj_common.h`。

### 2.6 `std::string` → `std::string_view` — 详细估算

> 基准数据来源：旧 `.so` 二进制分析 (`any.md`) — `libcj_file_fs_ffi.z.so` 中 `std::string::~string()` 被调用 **4,976 次**，`std::string::string(const&)` 被调用 **100 次**，合计 5,327 次 PLT 级 string 操作。

#### 2.6.1 当前源码 `std::string` 分布

| 文件 | string 数 | string_view 数 | 占比 |
|------|-----------|---------------|------|
| `copy.cpp` | 37 | 2 | 14.1% |
| `file_fs_impl.cpp` | 35 | 1 | 13.4% |
| `copy_dir.cpp` | 29 | 2 | 11.1% |
| `copy.h` | 28 | 0 | 10.7% |
| `translistener.cpp` | 25 | 0 | 9.5% |
| `file_impl.cpp` | 23 | 0 | 8.8% |
| `file_fs_impl.h` | 20 | 0 | 7.6% |
| `translistener.h` | 16 | 0 | 6.1% |
| 其余 20 个文件 | 49 | 0 | 18.7% |
| **合计** | **262** | **5** | 100% |

`std::string_view` 仅 5 处使用（都在 `copy.cpp` 和 `copy_dir.cpp` 的 `FilterFunc` 中），占 1.9%。

#### 2.6.2 按类别估算

**A 类：`const std::string&` 参数 → `std::string_view`（头文件 40 处 + 内部 27 处 = 67 处）**

这是最高收益的转换。头文件中的声明影响所有调用方（包括外部消费者）：

| 头文件 | 参数数 | 示例 |
|--------|--------|------|
| `copy.h` | 14 | `IsFile(const std::string &path)`, `CopyFile(const std::string &src, const std::string &dest, ...)` |
| `translistener.h` | 10 | `CopyFileFromSoftBus(const std::string& srcUri, ...)`, `RmDir(const std::string &path)` |
| `file_fs_impl.h` | 6 | `UvAccess(const std::string &path, ...)`, `IsCloudOrDistributedFilePath(...)` |
| `watcher_impl.h` | 3 | `AddWatcherInfo(const std::string &fileName, ...)` |
| `stream_impl.h` | 2 | `Write(void* buf, int64_t len, int64_t offset, const std::string& encode)` |
| 其他 | 5 | `ListFile`, `Mkdtemp`, `Symlink` 等 |

每个 `const std::string&` → `std::string_view` 后，传字符串字面量或 `const char*` 的调用方不再需要构造临时 `std::string`。单次调用约节省：构造函数（~40B .text）+ 析构函数（~50B .text）+ PLT 开销（~24B）= **~114B**。

假设 40% 调用方能受益（其余传 `std::string` 不变），67 × 5 平均调用方 × 40% = 134 处调用：
**134 × 114B ≈ 15KB**

**B 类：本地临时路径拼接 → 栈缓冲区（~20 处）**

典型模式（`copy.cpp`/`copy_dir.cpp` 中大量出现）：

```cpp
std::string src = srcPath + '/' + std::string((pNameList->namelist[i])->d_name);
std::string dest = destPath + '/' + std::string((pNameList->namelist[i])->d_name);
```

每行产生 3 个临时 `std::string` 对象（一次 `operator+` 创建两个 + 一次构造），对应 ~6 次 PLT 调用。替换为栈缓冲区：

```cpp
char src[PATH_MAX];
snprintf(src, sizeof(src), "%s/%s", srcPath.data(), pNameList->namelist[i]->d_name);
```

每处节省 ~200B（消除 3 次构造 + 3 次析构 + 堆分配路径）。20 处 × 200B = **~4KB**。

**C 类：`static const std::string` → `constexpr std::string_view`（15 处）**

| 文件 | 数量 | 示例 |
|------|------|------|
| `file_impl.cpp` | 9 | `PROCEDURE_OPEN_NAME`, `MEDIALIBRARY_DATA_URI`, `MODE_RW`, `SCHEME_BROKER` 等 |
| `file_fs_impl.cpp` | 3 | `CLOUDDISK_FILE_PREFIX`, `PACKAGE_NAME_FLAG`, `USER_ID_FLAG` 等 |
| `translistener.cpp` | 2 | `FILE_MANAGER_AUTHORITY`, `MEDIA_AUTHORITY` |
| `copy.cpp` | 1 | `MEDIALIBRARY_DATA_URI` |

`static const std::string` 产生静态析构注册（`__cxa_atexit`）和堆分配。`constexpr std::string_view` 仅占 16B `.rodata`，无运行时开销。15 × 50B = **~1KB**。同时减少 `__cxa_atexit` 调用（旧 .so 中有 192 次）。

**D+E 类：返回值 + 值参数（少量，保守估算）**

约 5 个返回 `std::string` 的函数和 10 个可转换的值参数，合计 **~1.5KB**。

#### 2.6.3 估算汇总

| 类别 | 涉及数 | 单位节省 | 小计 |
|------|--------|---------|------|
| A. `const&` 参数 → `string_view` | 67 声明，~134 调用点 | 114B/调用点 | **~15KB** |
| B. 本地路径拼接 → 栈缓冲 | ~20 处 | 200B/处 | **~4KB** |
| C. `static const string` → `constexpr sv` | 15 处 | 50B/处 | **~1KB** |
| D+E. 返回值 + 值参数 | ~15 处 | 100B/处 | **~1.5KB** |
| **合计** | | | **~21.5KB** |

考虑到 PR 已启用 LTO（会内联部分短字符串优化路径），实际收益打 8 折：**~17KB**。

占旧 .so 总大小（793KB）的 **2.1%**，占 `.text` 段（524KB）的 **3.2%**。

#### 2.6.4 投入产出评估

| 维度 | 评估 |
|------|------|
| 改动量 | 67 处函数签名 + 20 处局部变量改写，涉及 ~10 个文件 |
| 风险 | 低 — `string_view` 是 `const&` 的严格超集（可隐式从 string 构造） |
| 二进制兼容性 | 无影响 — 不改变 ABI 导出符号 |
| 代码可读性 | 提升 — `string_view` 明确表达"不持有所有权"语义 |

---

## 三、总结

| 维度 | 结论 |
|------|------|
| 二进制兼容性 | ⚠️ 有风险，主要在 `-fno-exceptions`/`-flto`/`--icf=all` |
| PR 代码质量 | ✅ 方向正确：提取共享函数、删除冗余日志、编译优化 |
| 额外优化空间 | 📋 6 项：去掉 UBSan/CFI（~87KB）、`std::string`→`string_view`（~17KB）、`copy.cpp`/`copy_dir.cpp` 深层合并、微小文件合并、`copy.h` 内联移出、残余日志清理 |
