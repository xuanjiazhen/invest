# Bucket C 惰性绑定：应用侧改造指南

> 配套提案：`detailed-proposals/native-interop-lazy-binding/`（VM 侧方案 A）
> 本文只讲**应用侧现在就能做**的部分，不依赖 VM 改动。
> 全部数字来自 13 个应用快照实测，脚本见 `scripts/measure_lazy_binding_targets.py`。

---

## 0. 一页结论

Bucket C 共 **68.54 MiB**（505,444 个 native JSFunction 闭包，绑定在**零实例类**的
prototype 上），其中 447,707 个方法闭包为 61.47 MiB，另有 57,737 个类构造器闭包为
7.06 MiB。方案 A 的方法惰性绑定收益口径排除构造器，只使用前者。按宿主结构切分为三块，需要三种完全不同的手段：

| 分类 | 结构特征 | 13 app 合计 | 应用侧手段 |
|------|---------|------------|-----------|
| **WIDE** | 1 个 prototype × ≥20 个方法 | **38.69 MiB** | 惰性模块访问器（本文重点）+ 注册去重 |
| **NARROW** | 多个 prototype × 3–6 个相同方法 | 26.13 MiB | 代码生成器粒度 / tree-shaking |
| **BARE** | 只有构造器，无方法 | 3.72 MiB | 无独立手段 |

WIDE 再按类的归属切分：

| 归属 | 合计 | 说明 |
|------|------|------|
| W-sys（映射到 `@ohos.*` 系统模块） | 16.67 MiB | 系统 NAPI 类，应用不能改类本身，只能改**导入方式** |
| W-app（应用/三方 SDK 自有 native 类） | 14.76 MiB | 应用可改注册代码本身 |
| 其余（未归类到具体 `@ohos` 模块的系统类） | 7.26 MiB | 同 W-sys 手段 |

**其中 80% 是重复拷贝，不是首份开销**：W-sys 16.67 MiB 里 **13.39 MiB（80%）**
是同一个类的 prototype 被重复创建的第 2..N 份；W-app 14.76 MiB 里 **12.99 MiB（88%）**
同理。这意味着**收益最高的改造不是"别加载"，而是"别重复注册/重复解析"**。

---

## 1. 三个改造点，按收益排序

| # | 改造点 | 影响应用 | 可回收 | 改动位置 |
|---|-------|---------|-------|---------|
| 1 | native 类注册去重（同 context 重复注册） | kuaishou / meituan / weibo | **~9.5 MiB** | 应用自有 native 注册入口，1 个文件 |
| 2 | 系统模块惰性导入（手动 getter 替换） | 全部 13 个 | **~13.4 MiB** 上限 | 各 HAR 的 import 处 |
| 3 | 代码生成器粒度（NARROW） | 全部 13 个 | 26.13 MiB 上限 | protobuf/IDL 生成器配置 |

下面逐个给完整的改前/改后。

---

## 2. 改造点 1：native 类注册去重

### 2.1 实测证据

kuaishou 的 W-app 14.10 MiB 里，**216 个应用自有 native 类全部有 18 份 prototype 拷贝**，
且这 18 份：

- 方法名集合**完全一致**（`PrivateExportTaskStats` 18 份都是同一组 373 个方法名）
- 只分布在 **7 个 global_env** 里，其中 **12 份挤在同一个 global_env**
- 每一份都被一个独立的 `GlobalHandleRoot`（native `napi_create_reference`）钉住

同一个 context 里出现 12 份同名类的 prototype，只能是**注册函数被调了 12 次**，
而不是多 worker / 多 context 各注册一次。

全部 281 个类的持有链都指向同一个文件：

```
com.kuaishou.hmapp/kop@0.0.23/src/main/ets/Kop.ts#Kop(line:1)[kwai]
com.kuaishou.hmapp/kop@0.0.23/src/main/ets/Kop.ts#checkBundleIntegrity(line:127)[kwai]
```

meituan 的 `MRNBundleInfoWrapper` 有 **39 份**拷贝（0.117 MiB，占其 W-app 的 97%），
weibo 的 `LottieController` 有 **11 份**（0.034 MiB）。

### 2.2 改造前（有缺陷的写法）

典型形态是"每次用到就注册一次"，注册函数自身没有幂等保护：

```typescript
// kop/src/main/ets/Kop.ts —— 改造前
import nativeKop from 'libkop.so';

export class Kop {
  // 每个业务入口都会调一次 ensureNative()，每次都重新注册全部 native 类
  static ensureNative(env: KopEnv): void {
    nativeKop.registerClasses(env);   // ← 内部对 281 个类逐一 napi_define_class
  }
}

// 业务侧（编辑器、直播、RTC、导出…各自初始化时都调一次）
Kop.ensureNative(env);
```

native 侧对应的缺陷写法：

```cpp
// libkop —— 改造前
napi_value RegisterClasses(napi_env env, napi_callback_info info) {
  for (const auto& desc : kAllClassDescriptors) {   // 281 个类
    napi_value ctor;
    napi_define_class(env, desc.name, NAPI_AUTO_LENGTH, desc.ctor,
                      nullptr, desc.methodCount, desc.methods, &ctor);
    napi_ref ref;
    napi_create_reference(env, ctor, 1, &ref);      // ← 每次调用都新建一份并钉死
    g_refs.push_back(ref);
  }
  return nullptr;
}
```

每调一次，281 个类各多出一个 prototype + 全套方法闭包，且因为 `napi_create_reference`
持有强引用，GC 无法回收任何一份。

### 2.3 改造后

**native 侧（根治，推荐）** —— 按 env 做一次性注册：

```cpp
// libkop —— 改造后
namespace {
// 每个 napi_env（≈每个 context/worker）只注册一次
std::unordered_map<napi_env, std::vector<napi_ref>> g_registry;
std::mutex g_registry_mu;
}

napi_value RegisterClasses(napi_env env, napi_callback_info info) {
  {
    std::lock_guard<std::mutex> lk(g_registry_mu);
    if (g_registry.count(env)) {
      return nullptr;                                // ← 幂等：第 2..N 次直接返回
    }
    g_registry.emplace(env, std::vector<napi_ref>{});
  }

  std::vector<napi_ref> refs;
  refs.reserve(std::size(kAllClassDescriptors));
  for (const auto& desc : kAllClassDescriptors) {
    napi_value ctor;
    napi_define_class(env, desc.name, NAPI_AUTO_LENGTH, desc.ctor,
                      nullptr, desc.methodCount, desc.methods, &ctor);
    napi_ref ref;
    napi_create_reference(env, ctor, 1, &ref);
    refs.push_back(ref);
  }
  {
    std::lock_guard<std::mutex> lk(g_registry_mu);
    g_registry[env] = std::move(refs);
  }

  // env 销毁时释放，避免 worker 退出后泄漏
  napi_add_env_cleanup_hook(env, [](void* p) {
    auto e = static_cast<napi_env>(p);
    std::lock_guard<std::mutex> lk(g_registry_mu);
    g_registry.erase(e);
  }, env);
  return nullptr;
}
```

**JS 侧（兜底，改动最小）** —— 如果暂时改不动 native，先在 TS 侧挡住重复调用：

```typescript
// kop/src/main/ets/Kop.ts —— 改造后
import nativeKop from 'libkop.so';

export class Kop {
  // 注意：必须以 env 为键，不能用一个全局 boolean —— 每个 worker 的 env 都需要各自注册一次
  private static readonly registered = new WeakSet<KopEnv>();

  static ensureNative(env: KopEnv): void {
    if (Kop.registered.has(env)) {
      return;                          // ← 同一 context 只注册一次
    }
    Kop.registered.add(env);
    nativeKop.registerClasses(env);
  }
}
```

### 2.4 收益

去重到"每个 global_env 保留 1 份"（不是 1 份，跨 context 无法共享 prototype）：

| 应用 | W-app | 拷贝数 | env 数 | 去重后可回收 |
|------|-------|-------|-------|------------|
| kuaishou | 14.100 | 18 | 7 | **8.61 MiB** |
| meituan | 0.120 | 39 | — | 0.114 MiB |
| weibo | 0.043 | 11（LottieController） | — | 0.031 MiB |
| douyin | 0.286 | 1–2 | — | 0.010 MiB |
| 其余 9 个 | — | 1 | — | 0 |

kuaishou 单应用 **8.61 MiB**，改动集中在 1 个文件（`Kop.ts` + 对应 native 注册入口）。

> 如果 7 个 env 中有若干是同一 context 下的重复 —— 从"12 份共享同一 global_env"看
> 至少存在这种情况 —— 实际可回收会高于 8.61 MiB，上限为去重到 1 份的 12.84 MiB。

---

## 3. 改造点 2：系统模块惰性导入（手动 getter 替换）

### 3.1 适用判据

只对满足**全部**三条的类有效：

1. 类在快照中 **零实例**（prototype 已建，但没有任何对象以它为 hclass）
2. 其 `@ohos.*` 模块在本应用快照中**确实被加载**（`loaded` 列为真）
3. 该模块在**首屏路径上不必需**（人工判断，快照无法给出）

第 1、2 条已由脚本判定；第 3 条必须由业务确认，本文不替业务下结论。

### 3.2 W-sys 按模块分布（13 app 合计）

| `@ohos` 模块 | MiB | 其中重复拷贝 | 闭包数 | 命中 app | 已加载 | 拷贝中位数 |
|-------------|-----|------------|-------|---------|-------|-----------|
| `@ohos.multimedia.camera` | 5.480 | 4.597 | 40,029 | 13 | 13 | 6 |
| `@ohos.multimedia.audio` | 2.487 | 2.010 | 18,229 | 13 | 13 | 4 |
| `@ohos.rpc` | 1.441 | 1.191 | 10,500 | 13 | 10 | 6 |
| `@ohos.data.relationalStore` | 1.253 | 0.991 | 9,187 | 13 | 13 | 2 |
| `@ohos.multimedia.image` | 1.075 | 0.920 | 7,862 | 13 | 13 | 6 |
| `@ohos.file.photoAccessHelper` | 1.056 | 0.869 | 7,719 | 12 | 12 | 6 |
| `@ohos.web.webview` | 0.923 | 0.728 | 6,604 | 11 | 11 | 4 |
| `@ohos.zlib` | 0.778 | 0.646 | 5,698 | 13 | 13 | 6 |
| `@ohos.multimedia.media` | 0.528 | 0.379 | 3,864 | 13 | 13 | 1 |
| `@ohos.pasteboard` | 0.513 | 0.421 | 3,764 | 13 | 13 | 5 |
| `@ohos.abilityAccessCtrl` | 0.286 | 0.244 | 2,100 | 11 | 11 | 8 |
| `@ohos.data.distributedKVStore` | 0.173 | 0.125 | 1,269 | 13 | 9 | 1 |
| `@ohos.account.osAccount` | 0.135 | 0.000 | 988 | 13 | **0** | 1 |
| `@ohos.font` | 0.130 | 0.073 | 950 | 11 | 10 | 1 |
| `@ohos.data.dataSharePredicates` | 0.106 | 0.051 | 775 | 13 | 12 | 1 |
| `@ohos.account.appAccount` | 0.103 | 0.087 | 754 | 2 | 2 | 12 |
| `@ohos.graphics.text` | 0.078 | 0.026 | 570 | 10 | 10 | 1 |
| `@ohos.arkui.StateManagement` | 0.076 | 0.000 | 559 | 13 | 10 | 1 |
| `@ohos.distributedDeviceManager` | 0.051 | 0.033 | 378 | 5 | 5 | 1 |

`@ohos.account.osAccount` 的 `loaded=0`：13 个应用都有它的 prototype，但没有一个应用
的快照里出现该模块说明符 —— 属于运行时预置，**不是应用导入产生的，改应用代码无效**。

`@ohos.multimedia.camera` 一项就占 W-sys 的 33%，且 84% 是重复拷贝。

### 3.3 改造前

```typescript
// feat_scan/src/main/ets/ScanPage.ts —— 改造前
import camera from '@ohos.multimedia.camera';
import media from '@ohos.multimedia.media';
import photoAccessHelper from '@ohos.file.photoAccessHelper';

@Entry
@Component
struct ScanPage {
  private mgr?: camera.CameraManager;

  // 模块在文件被加载时就完成解析，camera 的 11 个类
  // （CameraManager / PhotoOutput / PreviewOutput / VideoSession / ...）
  // 的 prototype 及其全部方法闭包在此刻全部创建完毕，
  // 哪怕用户从未点开扫码页。
  aboutToAppear(): void { /* ... */ }

  private async startScan(): Promise<void> {
    this.mgr = camera.getCameraManager(getContext(this));
    // ...
  }
}
```

问题不在 `import` 语句本身，而在**顶层 import 会在模块求值时触发 NAPI 模块解析**，
从而materialize 全部导出类的 prototype。

### 3.4 改造后（自替换 getter）

核心手法：把顶层 `import` 换成一个**首次访问时才解析、解析后把自己替换掉**的
访问器，后续访问退化为普通数据属性读取，无额外开销。

```typescript
// common/src/main/ets/LazyNapi.ts —— 新增，全应用共用
/**
 * 惰性系统模块访问器。
 *
 * 第一次读取属性时才执行 loader（触发真正的模块解析 / prototype 建立），
 * 随后用 defineProperty 把 getter 自身替换为数据属性，
 * 因此只有首次访问付出一次 getter 调用的开销。
 *
 * 注意：loader 内部必须用动态 import() 或 requireNapi，
 * 不能用顶层 import —— 顶层 import 会被提升，惰性就失效了。
 */
export function lazyModule<T>(loader: () => T): { readonly value: T } {
  const box = {} as { value: T };
  Object.defineProperty(box, 'value', {
    configurable: true,
    enumerable: true,
    get(): T {
      const m = loader();
      Object.defineProperty(box, 'value', {
        value: m, writable: false, configurable: false, enumerable: true,
      });
      return m;
    },
  });
  return box;
}
```

```typescript
// feat_scan/src/main/ets/ScanPage.ts —— 改造后
import { lazyModule } from '@app/common/LazyNapi';

// 顶层不再直接 import 系统模块；requireNapi 在 getter 内部才执行
const Camera = lazyModule(() => requireNapi('multimedia.camera') as ESObject);
const Media = lazyModule(() => requireNapi('multimedia.media') as ESObject);
const PhotoHelper =
  lazyModule(() => requireNapi('file.photoAccessHelper') as ESObject);

@Entry
@Component
struct ScanPage {
  private mgr?: ESObject;

  // 不再触发 camera 模块解析
  aboutToAppear(): void { /* ... */ }

  private async startScan(): Promise<void> {
    // 第一次真正用到时才解析 camera 模块并建立 prototype
    this.mgr = Camera.value.getCameraManager(getContext(this));
    // ...
  }
}
```

若不希望引入 `requireNapi`，用动态 `import()` 的等价写法（异步）：

```typescript
// 改造后 —— 动态 import 版本
let cameraMod: ESObject | undefined;
async function getCamera(): Promise<ESObject> {
  if (cameraMod === undefined) {
    cameraMod = await import('@ohos.multimedia.camera');
  }
  return cameraMod;
}

private async startScan(): Promise<void> {
  const camera = await getCamera();
  this.mgr = camera.getCameraManager(getContext(this));
}
```

### 3.5 类型安全的写法

上面为了简洁用了 `ESObject`。生产代码应保留类型，用 `import type`（只做类型标注，
**不产生运行时导入**）：

```typescript
// 改造后 —— 保留完整类型
import type camera from '@ohos.multimedia.camera';   // ← type-only，编译后擦除

const Camera = lazyModule<typeof camera>(
  () => requireNapi('multimedia.camera') as typeof camera);

private async startScan(): Promise<void> {
  const mgr: camera.CameraManager =
    Camera.value.getCameraManager(getContext(this));  // 类型完整可用
}
```

### 3.6 三个必须避免的反模式

```typescript
// ✗ 反模式 1：顶层 import 只是"改成了变量"，模块照样在加载期解析
import camera from '@ohos.multimedia.camera';
const Camera = { value: camera };            // 无任何惰性效果

// ✗ 反模式 2：getter 不自替换，每次访问都走一遍 getter + 解析缓存查找
get camera() { return requireNapi('multimedia.camera'); }

// ✗ 反模式 3：在 EntryAbility.onCreate / 全局单例构造里"预热"
//   这等于把惰性又改回了饿汉式
onCreate(): void {
  Camera.value;                              // ← 首屏又把 prototype 建回来了
}
```

### 3.7 收益边界

W-sys 合计 16.67 MiB，但**不能全部计入**：

- 其中 **13.39 MiB（80%）是重复拷贝**。重复来自模块解析上下文的数量（每个
  context / worker 各解析一份），惰性 getter 只能消掉"该 context 从未用到"的那些份，
  消不掉"确实用到了"的那份。
- 首份合计仅 3.28 MiB —— 这是**即便全部改造也回收不掉**的部分（除非该模块整个不用）。

因此改造点 2 的现实收益 = 「从未使用的 context 中的拷贝」，**上限 13.39 MiB**，
实际值取决于各应用有多少 worker 加载了用不到的模块。要精确到应用，需要业务确认
每个模块在哪些 context 里是真的会用到的。

---

## 4. 逐应用改造清单

### 4.1 汇总

| 应用 | Bucket C | W-sys | 其中重复 | W-app | 其中重复 | NARROW | 首要改造点 |
|------|---------|-------|---------|-------|---------|--------|-----------|
| kuaishou | 25.716 | 0.301 | 0.061 | **14.100** | **12.836** | 8.552 | **1（注册去重）** |
| douyin | 6.448 | 2.481 | 2.222 | 0.286 | 0.010 | 2.674 | 2（惰性导入） |
| weibo | 6.435 | 2.850 | 2.585 | 0.043 | 0.031 | 2.421 | 2 |
| pinduoduo | 5.202 | 2.150 | 1.885 | 0.000 | — | 1.950 | 2 |
| jingdong | 4.976 | 1.999 | 1.730 | 0.009 | 0.000 | 2.045 | 2 |
| alipay | 4.511 | 1.874 | 1.619 | 0.003 | 0.000 | 1.663 | 2 |
| meituan | 3.948 | 1.312 | 1.050 | 0.120 | **0.114** | 1.698 | 2 + 1 |
| meituanzhongbao | 3.618 | 1.277 | 1.024 | 0.000 | — | 1.628 | 2 |
| jrtt | 3.236 | 1.200 | 0.955 | 0.030 | 0.000 | 1.327 | 2 |
| taobao | 1.218 | 0.273 | 0.059 | 0.020 | 0.000 | 0.635 | 3 |
| gaodeditu | 1.126 | 0.422 | 0.157 | 0.000 | — | 0.465 | 2 |
| wechat | 1.059 | 0.291 | 0.043 | 0.123 | 0.000 | 0.416 | 3 |
| bilibili | 1.043 | 0.244 | 0.000 | 0.022 | 0.000 | 0.650 | 3 |
| **合计** | **68.536** | **16.672** | **13.391** | **14.757** | **12.991** | **26.125** | |

（W-sys + W-app 之和小于 WIDE 38.69，差额 7.26 MiB 为未映射到具体 `@ohos` 模块的
系统类，手段同 W-sys。）

### 4.2 kuaishou —— 14.100 MiB，改 1 个文件

**结论：应用侧收益最大的单点，全部 281 个类由同一个文件注册，且每个类有 18 份拷贝。**

改造位置：

```
com.kuaishou.hmapp/kop@0.0.23/src/main/ets/Kop.ts        ← JS 侧注册入口
  · Kop(line:1)
  · checkBundleIntegrity(line:127)
libkop.so 的 napi_module_register / RegisterClasses      ← native 侧根因
```

Top 类（方法数 × 18 份拷贝）：

| 类 | 方法数 | 闭包数 | 拷贝 | MiB |
|----|-------|-------|------|-----|
| PrivateExportTaskStats | 373 | 6,732 | ×18 | 0.924 |
| ExportOptions | 213 | 3,852 | ×18 | 0.528 |
| AudioEngineWrapper | 148 | 2,682 | ×18 | 0.369 |
| ExternalFilterRequest | 134 | 2,430 | ×18 | 0.333 |
| KRtcEngineInner | 121 | 2,196 | ×18 | 0.303 |
| AE2AVLayer | 119 | 2,160 | ×18 | 0.296 |
| AE2Asset | 112 | 2,034 | ×18 | 0.279 |
| PrivateDecoderStats | 111 | 2,016 | ×18 | 0.276 |
| PrivateRendererStats | 109 | 1,980 | ×18 | 0.271 |
| ResourcePathConfig | 104 | 1,890 | ×18 | 0.259 |
| RealtimeStats | 96 | 1,746 | ×18 | 0.239 |
| AE2TextDocument | 87 | 1,584 | ×18 | 0.217 |
| KSAVClip | 86 | 1,566 | ×18 | 0.215 |
| （其余 203 个类） | | | ×18 | 9.59 |

按前缀分组，便于拆分注册批次：

| 前缀族 | MiB | 归属 |
|-------|-----|------|
| `AE2*` | 1.798 | After-Effects 特效引擎 |
| `Private*` | 2.398 | 埋点/统计上报 |
| `Export*` | 0.792 | 导出流水线 |
| `KS*` / `K*` | 0.545 | 通用 SDK |
| `KRtc*` | 0.300 | RTC |
| `Resource*` / `Realtime*` | 0.497 | 资源/实时统计 |
| 其余 | 9.689 | 混合 |

改造建议（按投入产出排序）：

1. **注册幂等**（改动最小，收益 8.61 MiB）：按 §2.3 给 `RegisterClasses` 加 env 级
   一次性保护。不改变任何业务语义。
2. **按业务域拆分注册**（收益额外若干 MiB）：`AE2*`（仅编辑器用）、`KRtc*`（仅直播用）、
   `Private*`（仅上报用）不应在 `Kop.ts` 加载时全量注册；拆成
   `registerEditorClasses()` / `registerRtcClasses()` / `registerStatsClasses()`，
   在对应业务入口调用。
3. **`Private*` 统计类审视**：`PrivateExportTaskStats` 单类 373 个方法，几乎必然是
   IDL 生成的 getter/setter 全集。若这些字段只在上报时被序列化一次，改为
   plain object + 一次性序列化可整体消除。

### 4.3 douyin —— 2.481 MiB（W-sys 为主）

W-app 仅 0.286 MiB 且基本无重复（拷贝数 1–2），主体是系统模块重复解析
（W-sys 重复率 90%，拷贝中位数 12 —— 12 个模块解析上下文）。

W-app 类清单（均 ×1，只能靠"不加载"而非"去重"）：

| 类 | 方法数 | MiB |
|----|-------|-----|
| LiveStreamKit | 175 | 0.0241 |
| NLEVideoEncodeSettings | 132 | 0.0182 |
| RendererFunctionNG | 129 | 0.0178 |
| LiveStreamBuilder | 119 | 0.0164 |
| NapiMDL | 49 (×2) | 0.0137 |
| IFilterManager | 97 | 0.0134 |
| AccountSaaSNetworkService | 72 | 0.0100 |
| KAdRouterBuilder | 65 | 0.0090 |
| NLESegmentAudio / NLESegmentVideo | 60 / 59 | 0.0165 |
| NapiVeLivePlayer | 51 | 0.0072 |
| ILiveEffectComposerManager | 46 | 0.0064 |
| NativeFlexDataNode | 44 | 0.0061 |
| KevaNativeImpl | 21 (×2) | 0.0060 |
| （其余 31 个） | | 0.113 |

`NLE*`（视频编辑）、`LiveStream*`（直播）、`VECameraCapture` 显然不属首屏；
按 §3.4 对其所在 HAR 的入口做惰性化。

**首要动作**：查清 12 个模块解析上下文各自真正需要哪些系统模块 —— 重复的
2.222 MiB 里，只要有 context 加载了用不到的 camera/audio，就是净收益。

### 4.4 weibo / pinduoduo / jingdong / alipay / meituanzhongbao / jrtt / gaodeditu

这 7 个应用的共同画像：W-app ≈ 0（无自有 native 类重复注册问题），
**全部收益都在系统模块惰性导入**。

| 应用 | W-sys | 重复占比 | 拷贝中位数 | 备注 |
|------|-------|---------|-----------|------|
| weibo | 2.850 | 91% | 12 | 另有 `LottieController` ×11（0.031 MiB 可去重） |
| pinduoduo | 2.150 | 88% | 11 | 纯系统模块 |
| jingdong | 1.999 | 87% | 9 | W-app 仅 2 类共 0.009 |
| alipay | 1.874 | 86% | 10 | W-app 仅 `LottieController` 0.003 |
| meituanzhongbao | 1.277 | 80% | 6 | 纯系统模块 |
| jrtt | 1.200 | 80% | 2 | W-app 4 类共 0.030 |
| gaodeditu | 0.422 | 37% | 2 | 重复率低，改造空间小 |

改造顺序：先 `@ohos.multimedia.camera`（各应用占比最高），再 `audio` / `rpc` /
`relationalStore` / `image`。

weibo 额外一项：`LottieController`（22 方法）有 11 份拷贝，与 alipay / bilibili
的同名类同源（第三方 Lottie SDK），属该 SDK 的重复注册，可按 §2.3 处理。

### 4.5 meituan —— 1.312 MiB + 一个 ×39 的异常

W-app 仅 0.120 MiB，但结构异常突出：

| 类 | 方法数 | 闭包数 | 拷贝 | MiB |
|----|-------|-------|------|-----|
| MRNBundleInfoWrapper | 21 | 858 | **×39** | 0.117 |
| PikeClientNapiClass | 22 | — | — | 0.003 |

`MRNBundleInfoWrapper` 39 份拷贝 —— 每加载一个 MRN 业务包就注册一次同名 wrapper 类。
按 §2.3 加幂等保护可回收 0.114 MiB（97%）。虽绝对值不大，但**这是注册逻辑缺陷的
明确信号**，MRN 容器的其他 native 类可能有同样问题，值得整体排查。

### 4.6 wechat —— 0.291 MiB，改造点精确到文件

wechat 的 W-app 类拷贝数全部为 1，无重复注册问题，但**持有链解析出了精确到行的导入点**，
是惰性化改造最容易落地的样本：

| 类 | 方法数 | MiB | 导入点 |
|----|-------|-----|-------|
| ZIDL_UvVzgghY | 157 | 0.0215 | — |
| TRTCCloud | 108 | 0.0148 | `liteavsdk@12.8.1009/src/main/ets/h/k/w1.ts` |
| V2TXLivePusher | 34 | 0.0048 | `liteavsdk@12.8.1009/src/main/ets/d/d1.ts#registerExtraClass(line:21)` |
| ZIDL_e9_My5kk / Mhxm4 / Mm2p1 / MIhzl / MH7U1s | 78/74/41/37/32 | 0.0295 | `aam_alita@1.0.0/src/main/ets/x12/a42.ts#ZIDL_EI(line:17)` |
| JPAGView / JPAGPlayer | 35 / 32 | 0.0094 | `@tencent/libpag@4.4.27/src/main/ets/PAG.js#PAG(line:2)` |
| WCPlayer | 35 | 0.0049 | `feat_weapp@1.0.0/src/main/ets/a/k84/r126.ts#activeAudioModule(line:819)` |

系统类的导入点同样精确：

| 系统类 | 导入点 |
|-------|-------|
| AudioCapturer / AudioVolumeGroupManager / AudioStreamManager / AudioSpatializationManager | `feat_liteapp@1.0.0/src/main/ets/liteapp/n64/d210.ts#LiteAppCallbackImpl(line:39)` |
| AudioManager / AudioVolumeManager | `lib_common@1.0.0/src/main/ets/d258.ts#doPlay(line:30)` |
| Canvas / Path / Font | `@tencentmap/map@2.4.2/src/main/ets/e/w1/c2.ts#MapControllerImpl(line:1)` |
| AVPlayer | `feat_emoticon@1.0.0/src/main/ets/h105/i105/j105.ts#buildResult(line:283)` |
| RdbPredicates | `@qq/wtlogin_sdk@5.3.7/src/main/ets/d/e/f/u.ts#getRdbStore(line:10)` |
| Paragraph | `feat_pay_core@1.0.0/src/main/ets/x64/w232.ts#QRCodeDrawInfo(line:377)` |

`liteavsdk` 的 `registerExtraClass(line:21)` 就是注册函数本身 —— 直播推流 SDK
在模块加载期注册全部类，而绝大多数用户不会开直播。这是惰性化的教科书案例。

### 4.7 bilibili / taobao —— 主体在 NARROW

两者 W-sys 重复率极低（bilibili 0%、taobao 22%），说明模块解析上下文只有 1 个，
系统模块惰性化收益有限。主体在 NARROW：

- **bilibili** NARROW 0.650 MiB，其中 protobuf 生成物占大头：
  `copy/equals/hashCode/toString` 家族 245 个 prototype 0.163 MiB，
  `equals/hashCode/toString`（枚举 UNRECOGNIZED 包装）263 个 prototype 0.139 MiB。
  → 走改造点 3。
- **taobao** NARROW 0.635 MiB。W-app 类的导入点已解析出：
  `FalcoServiceSpan` ← `@taobao-ohos/falco_engine_implement@5.0.21/.../SceneIdentifier.ts`，
  `PopRequest` ← `@taobao-ohos/pop_layer_sdk@1.0.44/src/main/ets/init/InitPopLayer.ts`，
  `AbilityContext` ← `@taobao-ohos/megability_idl_interface@2.5.24/.../Accelerometer.ts`。
  高德地图 HAR（`@amap/amap_lbs_map3d@11.1.100/.../AMapNativeDelegate.ts`）拉入了
  `Path` / `Font` / `Matrix` / `Pen` 等 drawing 类。

### 4.8 精确改造文件清单（13 app 实测，WIDE JS 可归因部分）

下表按应用列出持有链能溯源的 HAR 及其内最重要的文件。"MiB"是从该 HAR 发出的
系统/自有类 WIDE prototype 估算值（持有链法，仅 JS-site 部分）。

#### kuaishou — 15.797 MiB → 1 个 HAR，1 个文件

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `kop@0.0.23` | **15.797** | `ets/Kop.ts`（含所有 281 个 native 类注册，entry: `Kop(line:1)` + `checkBundleIntegrity(line:127)`） |
| `@kwai/frogruntime@0.1.0` | 0.267 | `ets/sdk/FrogOHSDK.ts`, `ets/components/FrogCanvas.ts` |
| `@kwai/location@1.0.11` | 0.267 | `ets/business/manager/CurrentLocationCityManager.js` |
| `@alipay/afservicesdk@1.0.1` | 0.064 | `ets/components/AFServiceWeb.js`, `ets/components/AFServerHelper.js` |
| `@kds/react-native-audio-toolkit@2.0.23` | 0.040 | `ets/RNAVPlayerModule.ts`, `ets/AVRecorder.ts` |

#### douyin — 2.758 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@timon/proxy@1.0.36` | **1.778** | `ets/proxy/CameraProxy.js`（0.854）, `ets/proxy/AudioProxy.ts`（0.438）—— 代理层在初始化时直接持有 camera/audio 类 |
| `@douyin/kmp@…` | 0.219 | `ets/compose/ComposeView.ts` |
| `@account/account_sdk@0.2.32` | 0.196 | `ets/AccountInitConfig.ts`（0.125）, `ets/impl/BDAccountManager.ts`（0.071） |
| `@amap/amap_lbs_map3d@2.2.5` | 0.153 | `ets/com/amap/mapcore/UnZipFile.ts`（0.121） |
| `@account/account_platform@0.2.32` | 0.125 | `ets/base/AuthorizeErrorResponse.ts` |
| `@douyin/ttnet@2.0.115` | 0.106 | `ets/cronet/CronetCall.ts` |

#### weibo — 2.940 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@facelive/camera@1.0.0` | **0.854** | `ets/manager/FaceLiveCameraManager.ts` —— 人脸直播模块在加载时拉入 camera |
| `@cashier_alipay/cashiersdk@15.8.27` | 0.536 | `ets/api/Pay.ts`（0.468）, `ets/components/h5page/AlipayH5Page.ts`（0.069） |
| `@weibo/player@2.5.4` | 0.512 | `ets/ohav/OHAVPlayerImpl.js`（0.507） |
| `@megvii/lv5_sdk@5.8.12` | 0.232 | `ets/sdk/view/AgreementPage.ts`, `ets/sdk/utils/IMediaPlayer.ts` |
| `@hadss/debug-db@1.0.0-rc.11` | 0.192 | `ets/utils/RdbStoreHelper.ts` |
| `@facelive/screen_recorder@1.0.0` | 0.110 | `ets/components/ScreenRecorder.ts` |

#### pinduoduo — 2.535 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `pdd_face_anti_spoofing@1.0.0` | **0.854** | `ets/capture/PddFaceDetectLivenessPage.ts` —— 人脸防伪模块拉入 camera |
| `@cashier_alipay/cashiersdk@15.8.25` | 0.490 | `ets/api/Pay.js`（0.397）, `ets/api/Log.js` |
| `@hms-core/textreaderhsp@2.70.6-202` | 0.439 | `ets/Helpers/AudioRenderHelper.ts`（0.275） |
| `entry@1.0.0` | 0.161 | `ets/widget/PddBackButton.ts`, `ets/utils/utils.ts` |
| `permission@1.0.0` | 0.124 | `ets/permission/PermissionRequester.ts` |
| `@ohos/protobufjs@2.1.0` | 0.122 | `ets/dist/protobuf.js` |

#### jingdong — 2.068 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@jd-oh/face-identify@1.2.34` | **0.641** | `ets/components/common/FaceCamera.js` —— 人脸识别拉入 camera |
| `@jd-oh/taro_cpp_library@0.1.104` | 0.420 | `ets/npm/@tarojs/runtime/dist/runtime.esm.js`（0.416）—— Taro 运行时 |
| `@edi/lottie@2.0.11` | 0.131 | `js/utils/jsonImage.js` |
| `@jd-oh/base-info@1.0.59` | 0.131 | `ets/function/BaseInfoConfig.ts` |
| `@alipay/blueshieldsdk@1.0.29` | 0.130 | `ets/components/edge/risk/EdgeRiskManager.ts` |
| `@jdrtc/webrtc@1.1.25` | 0.106 | `ets/runtime/JDRtcRunningState.ts`（0.103） |

#### alipay — 1.870 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@alipay/mpaas_beephoto@1.0.260319201039` | **0.649** | `ets/BeePhotoService.ts` —— 拍照服务拉入 camera |
| `@alipay/asr@1.0.260722201824` | 0.374 | `ets/core/asr_service_inner.ts` —— 语音识别拉入 audio |
| `@alipay/account_certify_api@1.0.260703192332` | 0.357 | `ets/tecla/callee/Certify.ts` —— 实名认证 |
| `@alipay/antuser_platform@1.0.260722112945` | 0.235 | `ets/adapters/cookies/CookiesProvider.ts` |
| `@alipay/antui@1.0.260717110558` | 0.102 | `ets/components/bar/TabBarItem.ts` |
| `@alipay/blueshieldsdk@1.0.260327134444` | 0.066 | `ets/components/collect/device/HD17_LocalDeviceId.ts` |

#### meituan — 1.483 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@edfu/core@1.0.48` | **0.427** | `ets/impl/EdfuCameraController.ts`（0.427）—— 美团/美图相机 SDK，与 meituanzhongbao 共用 |
| `@adp/ad@0.0.19-mt` | 0.274 | `ets/adModule/AdBannerModule.ts` —— 广告模块 |
| `@clcad/irmo@1.1.17` | 0.251 | `ets/render/engine/vap/VolumeControlComponent.ts`（0.231） |
| `@meituan/privacy@0.3.20` | 0.073 | `ets/def/DefPermissionFactory.ts`（0.052） |
| `@msi/api@12.62.20000` | 0.064 | `ets/network_s3/MssUploadMsiApi.ts` |
| `mtlauncher@12.61.201` | 0.058 | `ets/components/tasks/lvctasks/HMCipStorageConfigTask.ts` |

#### meituanzhongbao — 1.305 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@edfu/core@1.0.48` | **0.387** | `ets/impl/EdfuCameraController.ts`（0.387）—— 同 meituan，共用版本 |
| `@meituan/privacy@0.3.20` | 0.365 | `ets/def/DefPermissionFactory.ts`（0.283）, `ets/def/DefPasteBoard.ts`（0.048） |
| `@banma/banmaNet@1.0.6` | 0.274 | `ets/common/BaseResponse.ts`（0.274）, `ets/common/ApiInfoBuilder.ts` |
| `@meituan/cookie_manager@0.1.0` | 0.071 | `ets/cookieManager/CookieManager.ts` |
| `@map/location@0.1.43` | 0.033 | `ets/core/engine/storage/EngineLocationDBManager.ts` |

#### jrtt — 1.239 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@alipay/authbase@1.3.2-2502173` | **0.630** | `ets/c1/g1.ts`（0.569）, `ets/l/m/n.ts`（0.569）—— Alipay 跨端授权基础库 |
| `@account/account_sdk@0.2.26` | 0.094 | `ets/AccountInitConfig.ts` |
| `@account/account_platform@0.2.26` | 0.089 | `ets/base/AuthorizeErrorResponse.ts` |
| `@douyin/argus@1.5.1-alpha.28` | 0.081 | `ets/plugin/ArgusPluginADBlock.ts` |
| `@douyin/ttnet@2.0.107-doubao` | 0.062 | `ets/cronet/CronetCall.ts` |

#### taobao — 0.336 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@cro-ohos/rp_verify@1.0.7` | 0.087 | `ets/service/camera/CameraService.ts`（0.071）, `ets/service/media/AudioPlayer.ts` |
| `@alipay/afservicesdk@1.0.2` | 0.048 | `ets/components/AFServerHelper.js` |
| `@alipay/shareoutersdk@1.0.250903142633` | 0.048 | `ets/openapi/APAPIFactory.js` |
| `@amap/amap_lbs_map3d@11.1.100` | 0.034 | `ets/com/amap/mapcore/AMapNativeDelegate.ts` |
| `@ohos/gpu_transform@1.0.1` | 0.030 | `ets/gpu/filter/GPUImageBlurFilter.ts` |
| `@taobao-ohos/guangguang_home@1.1.264` | 0.019 | `ets/business/video/service/MuteService.ts` |

#### gaodeditu — 0.454 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@alipay/authbase@2.3.44-26020301` | **0.133** | `ets/l/m/n.ts`（0.129）, `ets/d1/h1.ts`（0.129）—— 同 jrtt 系列 |
| `@agenui/agenui@1.2.0+c082091` | 0.119 | `ets/agenui/AGenUIContainer.ts`（0.095）, `ets/agenui/hybrid/HybridWebView.ts` |
| `@amap/amap_bundle_ajx@1.0.0` | 0.048 | `ets/moduleAPI/ModuleAudio.Module.ts` |
| `@amap/amap_bundle_infoservice@1.0.0` | 0.033 | `ets/thirdparty/markdown/render/styled/build-in.ts` |
| `@dmslibrary/wear-engine-client@0.26.9` | 0.031 | `ets/p2p/P2pCallback.ts` |

#### wechat — 0.376 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@ohos/crypto-js@2.0.4` | 0.063 | `js/crypto-js.js` |
| `@tencentmap/map@2.4.2` | 0.058 | `ets/e/w1/e4/f4/t5.ts`（0.030）, `ets/e/w1/c2.ts` |
| `feat_liteapp@1.0.0` | 0.046 | `ets/liteapp/n64/d210.ts#LiteAppCallbackImpl(line:39)` —— 小程序宿主拉入 audio 类 |
| `aam_alita@1.0.0` | 0.044 | `ets/x12/a42.ts#ZIDL_EI(line:17)` —— IDL 自动生成的包装类 |
| `liteavsdk@12.8.1009` | 0.030 | `ets/e/m.ts`, `ets/e/f.ts`（含 `registerExtraClass(line:21)`） |
| `@ohos/flutter_ohos@1.0.0-5ecf7faf733` | 0.028 | `ets/embedding/engine/FlutterEngineConnectionRegistry.ts` |

#### bilibili — 0.250 MiB

| HAR | MiB | 关键文件 |
|-----|-----|---------|
| `@alipay/authbase@1.3.4-250324` | **0.095** | `ets/l/m/n.ts`（0.071）, `ets/d1/h1.ts`（0.071）|
| `@alipay/afservicesdk@1.0.241118203225` | 0.045 | `ets/components/AFServiceWeb.js`（0.023）, `ets/components/AFServerHelper.js` |
| `@alipay/blueshieldsdk@1.0.30` | 0.021 | `ets/components/edge/risk/EdgeRiskManager.ts` |
| `entry@1.0.0` | 0.019 | `ets/startup/AccountTask.ts` |
| `kntr_native@1.0.0` | 0.017 | `ets/ignet/http/HttpRequest.ts`, `ets/ignet/http/HttpEngine.ts` |
| `@tb-open/svga@1.3.9` | 0.015 | `ets/audio/index.ts`, `ets/utils/fileManager.ts` |

---

### 4.9 跨应用共现的 SDK（单一改动可受益多个应用）

| SDK | 版本（各应用） | 受益应用 | 合计 MiB | 核心问题文件 |
|-----|--------------|---------|---------|------------|
| `@alipay/authbase` | 1.3.2 / 1.3.4 / 2.3.44 | jrtt / bilibili / gaodeditu | 0.858 | `ets/l/m/n.ts`, `ets/d1/h1.ts`, `ets/c1/g1.ts` |
| `@cashier_alipay/cashiersdk` | 15.8.25 / 15.8.27 | weibo / pinduoduo | 1.026 | `ets/api/Pay.ts`, `ets/api/Pay.js` |
| `@edfu/core` | 1.0.48 | meituan / meituanzhongbao | 0.814 | `ets/impl/EdfuCameraController.ts` |
| `@alipay/afservicesdk` | 1.0.1 / 1.0.2 / 1.0.241118203225 | kuaishou / taobao / bilibili | 0.157 | `ets/components/AFServiceWeb.js` |
| `@alipay/blueshieldsdk` | 1.0.29 / 1.0.30 / 1.0.260… | jingdong / bilibili / alipay | 0.217 | `ets/components/edge/risk/EdgeRiskManager.ts` |
| `@amap/amap_lbs_map3d` | 2.2.5 / 11.1.100 | douyin / taobao | 0.187 | `ets/com/amap/mapcore/AMapNativeDelegate.ts` |
| Face SDK（pdd / jd / alipay / weibo） | 各自独立 | 4 个 | 2.498 | 各自相机入口文件 |

上述 SDK 由第三方维护，应用侧无法直接改 SDK 内部，但可在**调用 SDK 的业务入口**
处加惰性化包装，延迟 SDK 模块加载到真正需要时。

---

## 5. 改造点 3：NARROW（代码生成器产物）

26.13 MiB，特征是**大量 prototype 携带完全相同的小方法集**。按方法名指纹聚类
（跨应用合并，指纹相同即同一生成器模板）：

| 方法集指纹 | MiB | prototype 数 | 命中 app | 判定 |
|-----------|-----|-------------|---------|------|
| `clone/getAllProperties/getBlob/getProperties/setBlob/setProperties` | 0.596 | 640 | 11 | `@ohos.multimedia.image` Metadata |
| `toBinary` | 0.475 | 1,887 | 1 | kuaishou LiveActivityWidget* |
| `%%get-cause/%%get-code/%%get-message/%%get-name/%%get-stack/%%set-*` | 0.396 | 240 | 12 | Error 子类 |
| `at/includes/isWellFormed/lastIndexOf/match/matchAll` | 0.198 | 90 | 10 | String 方法 |
| `addEntry/getEntries/...` | 0.192 | 210 | 3 | UnifiedRecord |
| `addEventListener/cancelTasks/...` | 0.180 | 95 | 7 | Worker |
| `append/delete/entries/get/getAll/has` | 0.172 | 116 | 7 | URLSearchParams |
| `copy/equals/hashCode/toString` | 0.163 | 245 | 1 | bilibili protobuf message |
| `clone/toBinary` | 0.154 | 396 | 1 | kuaishou |
| `equals/hashCode/toString` | 0.139 | 263 | 1 | bilibili protobuf 枚举 |

改造方向：

```protobuf
// 改造前：每个 message 都生成全套 copy/equals/hashCode/toString
option optimize_for = SPEED;
```

```protobuf
// 改造后：只为确实需要的 message 生成，其余走反射/共享实现
option optimize_for = CODE_SIZE;
```

生成器侧的等价改法是把 `copy/equals/hashCode/toString` 从**每个 message 的
prototype 各挂一份**改为**挂在共享基类 prototype 上**：

```typescript
// 改造前 —— 生成器为每个 message 生成独立方法（N 个 prototype × 4 个闭包）
export class UserProfile {
  copy(): UserProfile { /* 生成的实现 */ }
  equals(o: object): boolean { /* 生成的实现 */ }
  hashCode(): number { /* 生成的实现 */ }
  toString(): string { /* 生成的实现 */ }
}

// 改造后 —— 共享基类，每个 message 只保留字段描述符（1 份闭包 + N 份元数据）
abstract class PbMessage {
  copy(): this { return PbRuntime.copy(this, this.descriptor); }
  equals(o: object): boolean { return PbRuntime.equals(this, o, this.descriptor); }
  hashCode(): number { return PbRuntime.hash(this, this.descriptor); }
  toString(): string { return PbRuntime.format(this, this.descriptor); }
}
export class UserProfile extends PbMessage {
  readonly descriptor = USER_PROFILE_DESCRIPTOR;   // 纯数据，无闭包
}
```

`%%get-*` 那一族（Error 子类，12 个应用共 0.396 MiB）是 ArkTS 为每个自定义 Error
子类生成完整 accessor 组，减少 Error 子类层级即可。

---

## 6. 验证方法

改造前后各抓一次快照，对比：

```bash
python scripts/measure_lazy_binding_targets.py before.heapsnapshot after.heapsnapshot
```

关注三项：

1. `WIDE` 的 MiB 下降 —— 惰性导入是否生效
2. 各类的 `xN`（prototype 拷贝数）是否降到 env 数 —— 注册去重是否生效
3. `NARROW families` 数量 —— 生成器改造是否生效

单独核对某个类的拷贝来源：

```bash
# 输出该类每份 prototype 的 global_env、方法名集合、持有者
python scripts/inspect_class_copies.py app.heapsnapshot PrivateExportTaskStats
```

---

## 7. 数据口径与已知局限

- **"零实例"是单点采样判定**：prototype 关联的 hclass 没有任何节点通过 hclass 边
  指向它。若某类在抓取快照之后才被实例化，其方法绑定仍属必需。落地前建议对
  top-3（kuaishou / weibo / douyin）用运行时插桩复核。
- **类 → `@ohos` 模块映射来自人工维护的表**（`SYS_CLASS_MODULE`，约 130 项），
  用于命名导入点；是否属 Bucket C 由快照判定，不依赖该表。未命中该表的系统类
  （7.26 MiB）归入"其余"，手段相同但未拆分到模块。
- **`loaded` 列的含义**：该 `@ohos:*` 模块说明符字符串在快照中确实出现。
  `loaded=0`（如 `@ohos.account.osAccount`）表示 prototype 由运行时预置而非应用导入，
  **改应用代码无效**。
- **导入点解析的边界**：从类构造器沿反向引用向上查找到的最近的
  `<bundle>/<har>@<ver>/src/main/...#fn(line:N)` 命名点。若路径先到达全局作用域
  （`_GLOBAL ...`），则不作为归属证据 —— 那只是全局对象上任意一个具名函数，
  与该类无因果关系。本文列出的导入点均已排除此类。
- **kuaishou 的 8.61 MiB 是保守值**：按"每个 global_env 保留 1 份"计算。已确认
  12 份 prototype 共享同一个 global_env，说明同 context 内确有重复；若这 7 个 env
  中还有其他同 context 重复，实际收益更高，上限 12.84 MiB（去重到 1 份）。
- **改造点 2 的 13.39 MiB 是上限而非预期值**：只有"该 context 从未用到该模块"的
  拷贝才能消掉，需业务逐模块确认。

<!-- BEGIN HERMES REVIEW APPENDIX 2026-08-12 -->
## 复核意见（2026-08-12）

- **结论**：WIDE/NARROW/BARE 的快照分桶和上限口径可用于定位候选；“只能是注册函数被调用 N 次”“改 1 个文件即可回收 8.61 MiB”超过快照证据强度，示例实现也存在并发与资源释放缺陷，不能直接交付应用团队照抄。
- **数据/源码事实**：相同方法集合、多份 prototype、global_env 归属和 `GlobalHandleRoot` 证明存在重复驻留及 native reference 持有，但最近 retainer 名称不是因果调用栈，不能唯一定位注册入口。零实例不等于方法从未读取，`loaded` 字符串出现也不证明由某个 import 触发。13.39/26.13 MiB 均为上限。
- **风险或反例**：示例 `g_registry` 在完成 refs 创建前已插入 env，第二线程会提前返回看到未完成状态；cleanup 仅 `erase`，没有逐个 `napi_delete_reference`。以 `napi_env` 为永久 map key 还需处理地址复用和 hook 注册失败。ArkTS `WeakSet<KopEnv>` 是否可用、`requireNapi`/动态 import 的产品 SDK 支持及 tree-shaking 行为均未 clean build 验证。
- **放行条件**：用运行时调用栈/注册计数验证 Top 候选的真实入口和每 env 调用次数；把 registry 改为一次性状态机并在 cleanup 删除所有 refs；在目标 SDK clean 构建每个示例，跑首屏/worker/功能/退出回归；用前后快照按同场景确认实际 materialize 数和净 PSS 后再给逐应用收益。
<!-- END HERMES REVIEW APPENDIX 2026-08-12 -->
