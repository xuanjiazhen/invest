# OpenHarmony 7.0 Native Interop Bucket C lightweight patch

## Frozen bases

- `arkcompiler/ets_runtime`: `f04900cf951c66c2ea18b2bab5b591d5336c34b9`
- `foundation/arkui/napi`: `464170c9c1faba39f56549a13d232d51740a49d3`

`ets_runtime.patch` is intentionally empty. The implementation is confined to `arkui_napi`; it does not modify ArkVM/JSThread glue layout, property-read paths, rawheap, translator, or GC.

## Enablement

Collection requires all of the following:

1. The target is compiled with `ENABLE_HITRACE`.
2. `hiviewdfx.hiprofiler.nativeinterop.enabled=true`.
3. `hiviewdfx.hiprofiler.nativeinterop.bundle` exactly equals the current VM bundle name.

The parameters are non-persistent and must be set before the target application starts. The implementation registers a process-lifetime parameter watcher only after a target VM first matches. Turning `enabled` off, clearing the bundle, or changing it to another bundle immediately deletes the active VM registries. The watcher is retained to avoid unregister/callback teardown races; all statistics entries, class groups, VM nodes, and the 16K bucket table are reclaimed.

## Scope

Included:

- Ordinary `napi_define_class` constructor.
- Prototype methods, getters, and setters.
- Constructor/callback call state.
- Zero-instance classes.
- Bucket C closure and never-called closure aggregates.

Excluded:

- Static properties.
- Sendable classes.
- Ordinary `napi_create_function`.
- Proxy and BoundFunction.
- Property-read tracking; read-but-not-called cannot be distinguished.

No business name, class name, method name, bundle name, or raw pointer is logged.

## Checkpoints

The patch emits one aggregate `NAPI` HiLog line at:

- `checkpoint=napi_pre_heapdump` for the three `ArkNativeEngine::DumpHeapSnapshot` entry points.
- `checkpoint=final` after cleanup hooks have run during normal main-environment teardown.

The heap-dump line is pre-GC active-closure state. It is not aligned with the post-GC live set and must not be interpreted as such. Ability Runtime paths that call `DFXJSNApi::DumpHeapSnapshot` directly do not pass through these checkpoints.

Turning the parameter off is a stop operation: the registry is deleted immediately and no final aggregate for the deleted state is retained. Capture a N-API checkpoint before disabling when a result is required.

## Device use

Keep collection disabled for the first boot. After confirming normal boot, set the parameters before launching only the target application:

```sh
param set hiviewdfx.hiprofiler.nativeinterop.bundle <exact.bundle.name>
param set hiviewdfx.hiprofiler.nativeinterop.enabled true
```

Verify:

```sh
param get hiviewdfx.hiprofiler.nativeinterop.bundle
param get hiviewdfx.hiprofiler.nativeinterop.enabled
```

Emergency stop:

```sh
param set hiviewdfx.hiprofiler.nativeinterop.enabled false
```

The exact command that causes an `ArkNativeEngine::DumpHeapSnapshot` call is product/DFX-path dependent and must be confirmed on the target image. Generic hidumper/process dump paths can bypass this patch.

View matching HiLog records with the image's `hilog` CLI, for example:

```sh
hilog | grep 'NativeInteropUsage'
```

If supported by that `hilog` build, filtering the `NAPI` domain/tag first reduces noise. The authoritative match string is `NativeInteropUsage checkpoint=`.

## Verification completed

- Source contract and `git diff --check`: passed.
- `ets_runtime` frozen worktree: clean.
- arm64 rk3568 debug graph, current source, `ENABLE_HITRACE`: both `ark_native_engine.o` and `native_interop_usage_registry.o` rebuilt successfully.
- Same arm64 commands with `-DENABLE_HITRACE` removed: both objects compiled successfully to temporary outputs.
- Registry lifecycle harness: registration, call state, constructor collection with retained prototype closures, complete group reclamation, runtime bundle stop, VM-address reuse, final checkpoint, and Disable passed (`NATIVE_INTEROP_REGISTRY_LIFECYCLE_PASS logs=5`).
- Host JS to ABC, disassembly, and `ark_js_vm` execution previously passed (`HOST_ABC_SMOKE_PASS`).
- Frozen-base clean apply and post-apply `git diff --check`: required by the archive generation script.

## Verification boundary

The existing Ninja graph is `ohos_build_type="debug"` with `runtime_mode="release"`; this is not a clean Release product build. Object compilation and host execution do not load the device `arkui_napi` lifecycle and cannot prove phone boot safety. No full image link, flash, phone boot, target application run, or device HiLog collection was performed.
