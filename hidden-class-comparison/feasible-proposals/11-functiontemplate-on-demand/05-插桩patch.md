# 插桩 Patch：FunctionTemplate 实例化率验证

目的：验证「未实例化函数声明的 template 驻留」比例——template 创建数 vs 转换为 JSFunction 数，得到按需创建的收益折算基数。系统参数 `persist.ark.propf.tmplprobe`（示例名）开关。

## 创建侧

**文件**：`arkcompiler/ets_runtime/ecmascript/jspandafile/literal_data_extractor.cpp`

**位置**：`DefineFunctionTemplate`（:241，两条创建分支 :281 `NewSFunctionTemplate` / :283 `NewFunctionTemplate`）。

```cpp
// 创建处（共享分支后统一打点）：
if (UNLIKELY(TmplProbe::Enabled())) {
    // key = (pandaFileHash, methodId)；登记 created 计数与时刻
    TmplProbe::OnCreate(jsPandaFile->GetFileNameHash(), methodId);
}
```

注意：template 在字面量**首次 resolve**时创建（`GetClassLiteralFromCache` 惰性链），因此 created 基数本身已是「被触达的字面量」子集，不含从未 resolve 的声明。

## 消费侧（template → JSFunction 转换）

**文件**：`arkcompiler/ets_runtime/ecmascript/jspandafile/class_info_extractor.cpp`

**位置**：`CreateJSFunctionFromTemplate` 的全部调用点（:422-425 原型方法、:446-449 静态方法、:528/:553 一带 accessor 与其他分支）。

```cpp
if (propValue->IsFunctionTemplate()) {
    auto literalFunc = JSHandle<FunctionTemplate>::Cast(propValue);
    if (UNLIKELY(TmplProbe::Enabled())) {
        TmplProbe::OnInstantiate(literalFunc->GetMethod(thread));  // 以 Method 反查登记 key
    }
    propValue.Update(CreateJSFunctionFromTemplate(thread, literalFunc, prototype, lexenv));
}
```

另覆盖函数模板经 `JSFunction` 复制路径消费的场合（`js_function.cpp:1379-1407` 的 template 复制分支）——该处同样以 `OnInstantiate` 标记。

## 输出

```text
tmplprobe: created=<n1> instantiated=<n2> neverInstantiated=<x%>
           perAbc top10: <pandaFileHash, created, instantiated, ratio>
           neverInstantiatedBytes=<n1-n2>×40B=<MiB>
```

`neverInstantiatedBytes` 即按需创建的浅层收益模型（40 B/template，Top13 存量 954,059 个 / 36.39 MiB 为上界基数）。

## 验证思路

1. 原型实现「template 惰性驻留：literal 数据保留 (methodId, module, length) 三元组的紧凑记录（Smi/数组），首次 `CreateJSFunctionFromTemplate` 需要时重建 template」后，复跑本 probe：created 数应大幅下降，快照 `function_template` 节点数对照下降量 × 40 B 得实测收益；
2. 重建成本：template 重建只依赖 Method 指针（对象已驻留），重建为 O(1) 字段填充，冷启动与首次类定义延迟实测；
3. 与 snapshot/AOT 的交互：template 不进入序列化契约（`base_serializer` 对 FunctionTemplate 的处理以目标 revision 核对），无版本 bump 需求。
