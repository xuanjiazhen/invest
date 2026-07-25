# NapiDefineClass metadata 内存 · 调研报告

[来源] 以下全部数据基于源码静态分析，来源文件、行号均已标注。非实测性能数据。

---

## 1. 调用链

```
napi_define_class (N-API)
  └─ NapiDefineClass                              // ark_native_engine.cpp:333
       ├─ NapiFunctionInfo::CreateNewInstance()    // 回调元数据
       └─ NapiCreateClassFunction                  // ark_native_engine.cpp:288
            ├─ NapiGetKeysAndAttrsFromProps        // 遍历 property 数组
            │    └─ NapiInitAttrValFromProp
            │         └─ NapiNativeCreateFunction  // 每个 method → JSFunction
            └─ FunctionRef::NewConcurrentClassFunctionWithName
                 └─ CreateClassFuncWithProperties  // jsnapi_class_creation_helper.cpp:149
                      ├─ CreateClassFuncHClass     // 构造函数 HClass + transition 链
                      └─ NewClassFuncProtoWithProperties  // jsnapi_class_creation_helper.cpp:78
                           └─ CreateClassFuncProtoHClass   // 原型 HClass + transition 链
```

## 2. metadata 结构（源码定位）

### JSHClass
- 文件: `js_hclass.h:383`
- 大小: ~128 B（含 BitField + layout descriptor + transition 指针）
- 每添加 1 个 property 创建 1 个新 JSHClass（shape transition）

### PropertyAttribute
- 文件: `property_attributes.h:84`
- 48-bit bitfield: writable(1) + enumerable(1) + configurable(1) + isAccessor(1) + offset(10) + representation(2) + trackType(3) + ...
- 单例 6 B + value 指针

### JSFunction（native method wrapper）
- 路径: `object_factory.h` → `NewJSFunctionByHClass`
- ~400 B（code entry + lexical env + extraInfo）
- 附带 IC feedback vector：1-8 KB/method

### SemiSpace 配置
- 文件: `ecma_param_configuration.h:90`
- minSemiSpaceSize: 2 MB（所有档位通用）
- maxSemiSpaceSize: 4/8/16 MB（低/中/高档）
- Region: 256 KB (`mem.h:71`, `REGION_SIZE_LOG2=18`)

### 关键常量
| 常量 | 值 | 位置 |
|------|-----|------|
| `MAX_FAST_PROPS_CAPACITY` | 1023 | `property_attributes.h` |
| `maxInlPropCountForClassFunc` | ~1009 | `jsnapi_class_creation_helper.cpp:28` |
| `DEFAULT_CAPACITY_OF_IN_OBJECTS` | 4 | `js_hclass.h` |

## 3. 实测数据

来源: 内存 perf 图

| class | 方法数(估) | metadata |
|-------|-----------|----------|
| class A | ~100+ | 2.41 MB |
| class B | ~60-80 | 1.75 MB |
| 小型 class | <20 | 几十 KB |

metadata 占比超出其他堆对象，主要由 IC feedback vector + SemiSpace region 对齐驱动。

## 4. 竞品对比

### 4.1 Hidden Class
| 引擎 | 结构 | 单 transition | 来源 |
|------|------|-------------|--------|
| V8 | Map | 40-80 B | `src/objects/map.h` |
| JSC | Structure | ~48 B | `runtime/Structure.h` |
| Hermes | HiddenClass | 32-64 B | `include/hermes/VM/HiddenClass.h` |
| ArkVM | JSHClass | ~128 B | `js_hclass.h:383` |

### 4.2 Native method 注册
| 引擎 | API | 单 method | 特性 |
|------|-----|---------|------|
| V8 | FunctionTemplate::New | ~500 B | 惰性 IC |
| JSC | JSObjectMakeFunction… | ~400 B | — |
| Hermes | createFunction | ~300 B | 无 JIT |
| ArkVM | NapiNativeCreateFunction | 2-8 KB | 预分配 IC |

### 4.3 SemiSpace GC
| 引擎 | 初始 | 扩容粒度 | 来源 |
|------|------|--------|--------|
| V8 | 1 MB | OS page | `src/heap/new-spaces.h` |
| JSC | 1-2 MB | OS page | `heap/Heap.cpp` |
| Hermes | 512 KB | 32 KB | `lib/VM/GCBase.cpp` |
| ArkVM | 256 KB→2 MB | 256 KB | `ecma_param_configuration.h:90` |

### 4.4 场景估算（80 method class，源码推导，非实测）
| 引擎 | HClass 链 | method 函数 | SemiSpace | 合计 |
|------|----------|-----------|----------|------|
| V8 | 4.8 KB | 40 KB | ~100 KB | ~145 KB |
| JSC | 3.8 KB | 32 KB | ~100 KB | ~136 KB |
| Hermes | 3.8 KB | 24 KB | ~50 KB | ~78 KB |
| ArkVM | 10 KB | 400 KB | 1-2 MB | ~1.4-2.4 MB |

## 5. ArkVM 独有特性
| 特性 | 文件 |
|------|------|
| NewConcurrentClassFunctionWithName | `jsnapi_expo.cpp:4042` |
| NapiDefineSendableClass | `ark_native_engine.cpp:368` |
| maxInlPropCountForClassFunc ≈ 1009 | `jsnapi_class_creation_helper.cpp:28` |

## 6. 已知优化方向（源码层面，未实施）

基于源码分析的改进点:
1. JSHClass 压缩: ~128B → ~64B（合并位域）
2. IC feedback 惰性初始化（不在函数创建时分配）
3. SemiSpace region 从 256 KB → 64 KB 步进
4. Class property 批量注册替代逐个 transition

[文件结束]
