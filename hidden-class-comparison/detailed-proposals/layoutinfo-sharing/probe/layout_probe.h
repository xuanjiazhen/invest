#pragma once
// Drop-in probe for tracing LayoutInfo creation sites.
// Build with -DLAYOUT_PROBE=ON (see CMakeLists.txt snippet in README.md).
// At process exit, results are written to layout_probe_out.json.

#ifdef LAYOUT_PROBE

#include <cstdint>
#include <string>
#include <vector>

namespace panda::ecmascript {
class JSThread;
class LayoutInfo;
}  // namespace panda::ecmascript

namespace layout_probe {

// Called immediately after JSHClass::SetLayout(thread, layout).
// layout must be a valid, fully initialised LayoutInfo.
void OnSetLayout(panda::ecmascript::JSThread *thread,
                 panda::ecmascript::LayoutInfo *layout);

// Loads whitelist from path; called once on first OnSetLayout invocation.
// Reads evidence/{app}-layout-whitelist.json produced by Phase 1.
void LoadWhitelist(const std::string &json_path);

// Dumps collected stacks to layout_probe_out.json; registered with atexit.
void DumpResults();

}  // namespace layout_probe

#endif  // LAYOUT_PROBE
