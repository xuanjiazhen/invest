#ifdef LAYOUT_PROBE

#include "layout_probe.h"

#include <atexit.h>
#include <algorithm>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

// ArkVM headers — adjust include paths to match your source tree layout.
#include "ecmascript/js_hclass.h"
#include "ecmascript/layout_info.h"
#include "ecmascript/interpreter/frame_handler.h"
#include "ecmascript/js_thread.h"
#include "ecmascript/property_attributes.h"
#include "ecmascript/tagged_value.h"
#include "ecmascript/string_helper.h"

namespace layout_probe {

namespace {

constexpr int kMaxStacksPerFingerprint = 5;
constexpr int kMaxFramesPerStack = 32;

struct WhitelistSlot {
    std::string key;
    uint32_t    attr;  // PropertyAttributes raw value (tagged word from Attr node)
};

struct WhitelistEntry {
    int                      capacity;
    std::vector<WhitelistSlot> slots;
};

struct CapturedStack {
    std::vector<std::string> frames;
};

struct HitRecord {
    WhitelistEntry               entry;
    std::vector<CapturedStack>   stacks;
};

// fingerprint key → recorded hits
std::unordered_map<std::string, HitRecord> g_hits;
std::mutex                                 g_mu;
bool                                       g_dumped = false;

// ---- minimal JSON parser for the whitelist format -------------------------
// Parses only the subset we emit: objects, arrays, strings, numbers.

static std::string JsonString(const std::string &s, size_t &pos) {
    ++pos;  // skip opening "
    std::string out;
    while (pos < s.size() && s[pos] != '"') {
        if (s[pos] == '\\') { ++pos; }
        out += s[pos++];
    }
    ++pos;  // skip closing "
    return out;
}

static void SkipWs(const std::string &s, size_t &pos) {
    while (pos < s.size() && (s[pos] == ' ' || s[pos] == '\n' ||
                               s[pos] == '\r' || s[pos] == '\t'))
        ++pos;
}

static long long JsonInt(const std::string &s, size_t &pos) {
    bool neg = s[pos] == '-';
    if (neg) ++pos;
    long long v = 0;
    while (pos < s.size() && std::isdigit(static_cast<unsigned char>(s[pos])))
        v = v * 10 + (s[pos++] - '0');
    return neg ? -v : v;
}

static std::vector<WhitelistEntry> ParseWhitelist(const std::string &json) {
    std::vector<WhitelistEntry> result;
    // Find "entries" array
    size_t pos = json.find("\"entries\"");
    if (pos == std::string::npos) return result;
    pos = json.find('[', pos);
    if (pos == std::string::npos) return result;
    ++pos;

    while (pos < json.size()) {
        SkipWs(json, pos);
        if (json[pos] == ']') break;
        if (json[pos] != '{') { ++pos; continue; }
        ++pos;

        WhitelistEntry e;
        while (pos < json.size() && json[pos] != '}') {
            SkipWs(json, pos);
            if (json[pos] != '"') { ++pos; continue; }
            std::string key = JsonString(json, pos);
            SkipWs(json, pos);
            if (pos < json.size() && json[pos] == ':') ++pos;
            SkipWs(json, pos);

            if (key == "capacity") {
                e.capacity = static_cast<int>(JsonInt(json, pos));
            } else if (key == "slots") {
                // array of {key, attr}
                if (json[pos] == '[') ++pos;
                while (pos < json.size()) {
                    SkipWs(json, pos);
                    if (json[pos] == ']') { ++pos; break; }
                    if (json[pos] != '{') { ++pos; continue; }
                    ++pos;
                    WhitelistSlot slot;
                    while (pos < json.size() && json[pos] != '}') {
                        SkipWs(json, pos);
                        if (json[pos] != '"') { ++pos; continue; }
                        std::string sk = JsonString(json, pos);
                        SkipWs(json, pos);
                        if (pos < json.size() && json[pos] == ':') ++pos;
                        SkipWs(json, pos);
                        if (sk == "key") {
                            if (json[pos] == '"')
                                slot.key = JsonString(json, pos);
                            else if (json[pos] == 'n')  // null
                                { pos += 4; slot.key = ""; }
                        } else if (sk == "attr") {
                            slot.attr = static_cast<uint32_t>(JsonInt(json, pos));
                        }
                        SkipWs(json, pos);
                        if (pos < json.size() && json[pos] == ',') ++pos;
                    }
                    if (pos < json.size() && json[pos] == '}') ++pos;
                    e.slots.push_back(std::move(slot));
                    SkipWs(json, pos);
                    if (pos < json.size() && json[pos] == ',') ++pos;
                }
            } else {
                // skip value
                if (json[pos] == '"') { JsonString(json, pos); }
                else { while (pos < json.size() && json[pos] != ',' && json[pos] != '}') ++pos; }
            }
            SkipWs(json, pos);
            if (pos < json.size() && json[pos] == ',') ++pos;
        }
        if (pos < json.size() && json[pos] == '}') ++pos;
        result.push_back(std::move(e));
        SkipWs(json, pos);
        if (pos < json.size() && json[pos] == ',') ++pos;
    }
    return result;
}

// ---- fingerprint helpers --------------------------------------------------

static std::string MakeKey(int capacity, const std::vector<WhitelistSlot> &slots) {
    std::ostringstream ss;
    ss << capacity;
    for (const auto &s : slots)
        ss << ':' << s.key << ':' << s.attr;
    return ss.str();
}

// Whitelist map: fingerprint string → WhitelistEntry
std::unordered_map<std::string, WhitelistEntry> g_whitelist;
bool g_whitelist_loaded = false;

static void EnsureWhitelistLoaded(const std::string &path) {
    if (g_whitelist_loaded) return;
    g_whitelist_loaded = true;
    std::ifstream f(path);
    if (!f) return;
    std::string json((std::istreambuf_iterator<char>(f)),
                      std::istreambuf_iterator<char>());
    for (auto &e : ParseWhitelist(json)) {
        std::string k = MakeKey(e.capacity, e.slots);
        g_whitelist.emplace(std::move(k), std::move(e));
    }
}

std::string g_whitelist_path;

// ---- stack capture --------------------------------------------------------

static CapturedStack CaptureStack(panda::ecmascript::JSThread *thread) {
    CapturedStack cs;
    panda::ecmascript::FrameHandler handler(thread);
    int count = 0;
    for (; handler.HasFrame() && count < kMaxFramesPerStack;
         handler.PrevJSFrame(), ++count) {
        if (!handler.IsJSFrame()) continue;
        auto method = handler.GetMethod();
        if (method == nullptr) continue;
        std::ostringstream ss;
        // method->GetRecordName() and method->GetMethodName() are available
        // in ArkVM's Method/JSMethod; adjust if your API differs.
        const char *record = method->GetRecordName();
        const char *name   = method->GetMethodName();
        uint32_t offset    = handler.GetBytecodeOffset();
        ss << (record ? record : "?") << '#'
           << (name   ? name   : "?") << '@' << offset;
        cs.frames.push_back(ss.str());
    }
    return cs;
}

// ---- atexit dump ----------------------------------------------------------

static void DumpResultsInternal() {
    std::lock_guard<std::mutex> lk(g_mu);
    if (g_dumped) return;
    g_dumped = true;

    std::ofstream f("layout_probe_out.json");
    if (!f) return;

    f << "[\n";
    bool first_entry = true;
    for (const auto &kv : g_hits) {
        if (!first_entry) f << ",\n";
        first_entry = false;
        const auto &rec = kv.second;
        f << "  {\n";
        f << "    \"fingerprint\": \"" << kv.first << "\",\n";
        f << "    \"capacity\": " << rec.entry.capacity << ",\n";
        f << "    \"stacks\": [\n";
        bool first_stack = true;
        for (const auto &cs : rec.stacks) {
            if (!first_stack) f << ",\n";
            first_stack = false;
            f << "      [";
            bool first_frame = true;
            for (const auto &fr : cs.frames) {
                if (!first_frame) f << ", ";
                first_frame = false;
                // Escape quotes in frame strings
                f << '"';
                for (char c : fr) {
                    if (c == '"') f << '\\';
                    f << c;
                }
                f << '"';
            }
            f << "]";
        }
        f << "\n    ]\n";
        f << "  }";
    }
    f << "\n]\n";
}

}  // namespace

// ---- public API -----------------------------------------------------------

void LoadWhitelist(const std::string &json_path) {
    std::lock_guard<std::mutex> lk(g_mu);
    g_whitelist_path = json_path;
    EnsureWhitelistLoaded(g_whitelist_path);
}

void DumpResults() {
    DumpResultsInternal();
}

void OnSetLayout(panda::ecmascript::JSThread *thread,
                 panda::ecmascript::LayoutInfo *layout) {
    static std::once_flag init_flag;
    std::call_once(init_flag, []() {
        EnsureWhitelistLoaded(g_whitelist_path);
        std::atexit(DumpResultsInternal);
    });

    if (g_whitelist.empty()) return;

    // Build runtime fingerprint.
    int num = layout->NumberOfElements();
    // capacity mirrors the offline formula: (self_size - 16) / 16
    // At runtime, derive from the backing array length: capacity = length / 2
    // (each slot is key+attr pair).  Use NumberOfElements as the effective count.
    int capacity = layout->GetCapacity();  // or (layout->GetLength() / 2)

    std::vector<WhitelistSlot> slots;
    slots.reserve(num);
    for (int i = 0; i < num; ++i) {
        WhitelistSlot s;
        // GetKey(i) returns JSTaggedValue; extract string content.
        panda::ecmascript::JSTaggedValue key_tv = layout->GetKey(i);
        if (key_tv.IsString()) {
            auto *str = panda::ecmascript::EcmaString::Cast(key_tv.GetTaggedObject());
            s.key = panda::ecmascript::StringHelper::ToStdString(str);
        }
        // GetAttr(i) returns PropertyAttributes; GetValue() is the raw tagged word.
        s.attr = layout->GetAttr(i).GetValue();
        slots.push_back(std::move(s));
    }

    std::string fprint = MakeKey(capacity, slots);
    auto it = g_whitelist.find(fprint);
    if (it == g_whitelist.end()) return;

    std::lock_guard<std::mutex> lk(g_mu);
    auto &rec = g_hits[fprint];
    if (rec.stacks.empty()) rec.entry = it->second;
    if (static_cast<int>(rec.stacks.size()) < kMaxStacksPerFingerprint)
        rec.stacks.push_back(CaptureStack(thread));
}

}  // namespace layout_probe

#endif  // LAYOUT_PROBE
