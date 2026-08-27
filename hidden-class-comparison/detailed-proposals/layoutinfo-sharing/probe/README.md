# Phase 2 drop-in probe — integration instructions

Copy `layout_probe.h` and `layout_probe.cpp` into
`ecmascript/` alongside `js_hclass.h` / `js_hclass.cpp`.

---

## 1. CMakeLists.txt

In the `ecmascript` target (or wherever `js_hclass.cpp` is listed):

```cmake
option(LAYOUT_PROBE "Capture LayoutInfo creation call stacks" OFF)

if(LAYOUT_PROBE)
    target_compile_definitions(arkruntime PRIVATE LAYOUT_PROBE)
    target_sources(arkruntime PRIVATE ecmascript/layout_probe.cpp)
endif()
```

Build with `-DLAYOUT_PROBE=ON` to enable; default OFF leaves no code difference.

---

## 2. js_hclass.cpp — call site in JSHClass::SetLayout()

Find the existing call (approximately):

```cpp
void JSHClass::SetLayout(const JSThread *thread, const JSHandle<JSHClass> &hclass,
                         const JSHandle<LayoutInfo> &layout)
{
    // ... existing body ...
    hclass->SetLayout(layout.GetTaggedValue());
    // existing post-set logic ...
}
```

Add the probe call immediately after `hclass->SetLayout(...)`:

```cpp
#ifdef LAYOUT_PROBE
    layout_probe::OnSetLayout(const_cast<JSThread *>(thread),
                              LayoutInfo::Cast(layout.GetTaggedValue().GetTaggedObject()));
#endif
```

Add the include near the top of `js_hclass.cpp` (inside the `#ifdef` guard to
keep non-probe builds pristine):

```cpp
#ifdef LAYOUT_PROBE
#include "ecmascript/layout_probe.h"
#endif
```

---

## 3. Whitelist path

Before running the instrumented binary, set the path to the Phase 1 whitelist:

```cpp
// In your app init (e.g., EcmaVM constructor or a one-time setup path):
#ifdef LAYOUT_PROBE
    layout_probe::LoadWhitelist("/path/to/evidence/meituanzhongbao-layout-whitelist.json");
#endif
```

Alternatively, export `LAYOUT_PROBE_WHITELIST=/path/...` and have
`layout_probe.cpp` read it from the environment in `EnsureWhitelistLoaded` —
swap out the hardcoded path call with:

```cpp
const char *env = std::getenv("LAYOUT_PROBE_WHITELIST");
if (env) EnsureWhitelistLoaded(std::string(env));
```

---

## 4. Output

`layout_probe_out.json` is written to the process working directory on exit.
Format:

```json
[
  {
    "fingerprint": "8:propA:131073:propB:131073",
    "capacity": 8,
    "stacks": [
      ["com/example/Foo#init@12", "com/example/Bar#create@34"]
    ]
  }
]
```

Each entry holds up to 5 distinct call stacks for that fingerprint.
Feed this into the Phase 3 aggregation script.

---

## 5. API surface notes

`layout_probe.cpp` assumes the following ArkVM APIs — verify against your
source tree and adjust if needed:

| Usage in probe | Expected ArkVM symbol |
|---|---|
| `layout->NumberOfElements()` | `LayoutInfo::NumberOfElements()` → `int` |
| `layout->GetCapacity()` | `LayoutInfo::GetCapacity()` → `int` |
| `layout->GetKey(i)` | `LayoutInfo::GetKey(int)` → `JSTaggedValue` |
| `layout->GetAttr(i).GetValue()` | `LayoutInfo::GetAttr(int)` → `PropertyAttributes`; `.GetValue()` → `uint32_t` |
| `EcmaString::Cast(tv.GetTaggedObject())` | standard tagged-value cast |
| `StringHelper::ToStdString(str)` | `ecmascript/string_helper.h` |
| `FrameHandler handler(thread)` | `ecmascript/interpreter/frame_handler.h` |
| `handler.HasFrame()` / `handler.IsJSFrame()` | standard frame iteration |
| `handler.GetMethod()` | returns `Method *` or `JSMethod *` |
| `method->GetRecordName()` / `method->GetMethodName()` | returns `const char *` |
| `handler.GetBytecodeOffset()` | returns `uint32_t` |
