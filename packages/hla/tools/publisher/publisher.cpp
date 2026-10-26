// sc-hla-publisher: the synthetic publisher of `synapse-hla demo` (R38, R39, NAT-01, NAT-19).
//
//   sc-hla-publisher --version
//   sc-hla-publisher --endpoint=rti://ADDRESS:PORT --federation-name=NAME --fom-dir=DIRECTORY
//                    --module-sha256=HEX (five times, R04 order) --scenario=main|perf:O:H:S
//
// It is the only federate of the demo that creates, publishes, updates, deletes or destroys
// anything (R38). It reads the five RPR FOM modules from DIRECTORY, checks each one's SHA-256
// against the pin it is given, and creates the federation from exactly those bytes, handed to
// the RTI as `data:text/plain,` module designators in R04 order with the logical time
// implementation HLAfloat64Time (NAT-19); the digests it reports are therefore the digests of the
// bytes that created the federation (R11). It joins, publishes the four attributes on BOTH
// PhysicalEntity and GroundVehicle (NAT-01: the pinned OpenRTI forwards a subscription at
// PhysicalEntity only to a federate publishing that class), registers its object at GroundVehicle
// and sends fixed bytes: the packaged vectors, never an encoder (R39).
//
// Scenario `main` (R38's order): EntityIdentifier with EntityType; ForceIdentifier; Spatial
// DRM_FPW on the equator moving east; Spatial DRM_FPW 10 m higher; the removal. Scenario
// `perf:O:H:S` (R42's load shape): O objects, an identity reflection each, then S seconds of one
// Spatial reflection per object H times a second, then O removals.
//
// The orchestration paces it through an out-of-band barrier: before each next step the
// publisher announces `waiting` for a numbered barrier on stdout and reads that number, one line,
// from stdin, the pipe the orchestration gave it, which writes it once the observer's capture
// shows the step. A barrier not acknowledged within 5 seconds is a failure (R38); no sleep is a
// correctness condition. While it waits it answers provideAttributeValueUpdate with the current
// values it has (an extra refresh reflection, tagged `refresh`, which the evidence lists). The
// last barrier says the observer has resigned: the publisher resigns, destroys the federation
// it created (and never another: a name that already exists is a failure, R38/SPEC:211), and
// disconnects.
//
// stdout carries one JSON event per line, ASCII, for the orchestration and the evidence; stderr
// carries nothing but a fixed usage line. No text the RTI supplies is written anywhere: a failure
// names the stage and a fixed label of the exception. Exit status 0 when the scenario ran to the
// destroyed federation, 1 for a failure, a stop (SIGTERM) or a closed barrier pipe (after resigning
// and destroying what it created), 64 for any other argument vector.

// <memory> first, before any RTI header. Below C++17 the rti1516e headers hand out
// std::auto_ptr (RTI_UNIQUE_PTR) but never include <memory>: libc++ happens to declare it
// through other headers, libstdc++ (GCC 13, the reference compiler) does not, and the build
// fails there without this line (Linux reference run, finding F1).
#include <memory>

#include <RTI/NullFederateAmbassador.h>
#include <RTI/RTIambassador.h>
#include <RTI/RTIambassadorFactory.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "channels.h"
#include "process.h"
#include "sha256.h"
#include "text.h"

namespace {

// CR-L16: exactly what `--version` prints.
const char kVersionLine[] =
    "{\"name\":\"sc-hla-publisher\",\"profile\":\"SC-HLA-RPR2-OBS-1\",\"version\":\"1.0.0\"}\n";

enum ExitStatus : int { kExitDone = 0, kExitFailed = 1, kExitUsage = 64 };

// R04's order of the five modules.
const char* const kModules[5] = {"RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml",
                                 "RPR-Base_v2.0.xml", "RPR-Physical_v2.0.xml",
                                 "RPR-Switches_v2.0.xml"};
// OPS-12: no module is larger.
const std::size_t kMaxModuleBytes = 2u * 1024u * 1024u;

// The fixed bytes (R39), copied from the packaged vectors: V-ID-123 (site 1, application 2,
// entity 3), V-TYPE-PLATFORM, V-FORCE-1, and the bundled capture's two Spatial values (seq 5:
// DRM_FPW at x = 6378137 m moving 10 m/s along y; seq 6: the same at x = 6378147 m). A test
// holds each literal to the packaged fixture it is copied from.
const char kEntityIdentifier[] = "000100020003";
const char kEntityType[] = "010100e101020304";
const char kForceIdentifier[] = "01";
const char kSpatialEquator[] =
    "0200000000000000415854a64000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000004120000000000000";
const char kSpatialSecond[] =
    "0200000000000000415854a8c000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000004120000000000000";

// R38: each barrier is acknowledged within 5 seconds, or the run fails.
const std::int64_t kBarrierNanoseconds = 5000000000;
// How long one turn of a wait polls the barrier pipe before it evokes callbacks again.
const int kPollMilliseconds = 5;

const char kObjectName[] = "SYNTHETIC-001";
const char kFederateName[] = "SC_DEMO_PUBLISHER";
const char kFederateType[] = "SynapseCommandSyntheticPublisher";
const wchar_t kPhysicalEntity[] = L"HLAobjectRoot.BaseEntity.PhysicalEntity";
const wchar_t kGroundVehicle[] = L"HLAobjectRoot.BaseEntity.PhysicalEntity.Platform.GroundVehicle";
// The qualified names the two class handles were resolved with: the `ready` event names the class
// the RTI holds its objects at by the one whose handle it is (SPEC:50, NAT-01, NAT-04).
const char kPhysicalEntityName[] = "HLAobjectRoot.BaseEntity.PhysicalEntity";
const char kGroundVehicleName[] = "HLAobjectRoot.BaseEntity.PhysicalEntity.Platform.GroundVehicle";
const wchar_t* const kAttributes[4] = {L"EntityIdentifier", L"EntityType", L"Spatial",
                                       L"ForceIdentifier"};
enum Attribute { kIdentifier = 0, kType = 1, kSpatial = 2, kForce = 3 };

// The user tags of the updates and removals: which planned step, or an answer to a request.
const char kRefreshTag[] = "refresh";

// ---- the argument vector ------------------------------------------------------------------------

struct Scenario {
  bool perf = false;
  unsigned objects = 0;
  unsigned hz = 0;
  unsigned seconds = 0;
};

struct Arguments {
  std::string endpoint;
  std::string federation;
  std::string fom_dir;
  std::vector<std::string> pins;
  Scenario scenario;
};

bool take(const std::string& token, const char* prefix, std::string* value) {
  const std::string p(prefix);
  if (token.compare(0, p.size(), p) != 0) return false;
  *value = token.substr(p.size());
  return true;
}

bool all_of(const std::string& text, const char* allowed) {
  for (char c : text) {
    if (std::string(allowed).find(c) == std::string::npos) return false;
  }
  return true;
}

const char kDigits[] = "0123456789";
const char kNameCharacters[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-";

// The configuration schema's endpoint pattern, the worker's rule (CR-new-R7-02).
bool valid_endpoint(const std::string& value) {
  const std::string scheme = "rti://";
  if (value.size() > 64 || value.compare(0, scheme.size(), scheme) != 0) return false;
  const std::string rest = value.substr(scheme.size());
  const std::size_t colon = rest.rfind(':');
  if (colon == std::string::npos || colon == 0 || colon + 1 == rest.size()) return false;
  return all_of(rest.substr(0, colon), "0123456789.") && all_of(rest.substr(colon + 1), kDigits);
}

bool valid_name(const std::string& value) {
  return !value.empty() && value.size() <= 64 && all_of(value, kNameCharacters);
}

bool valid_directory(const std::string& value) {
  return !value.empty() && value[0] == '/' && value.size() <= 4096;
}

bool valid_digest(const std::string& value) {
  return value.size() == 64 && all_of(value, "0123456789abcdef");
}

// A decimal of one to `digits` digits without a leading zero, within [low, high].
bool decimal(const std::string& text, std::size_t digits, unsigned low, unsigned high,
             unsigned* value) {
  if (text.empty() || text.size() > digits || !all_of(text, kDigits) || text[0] == '0') {
    return false;
  }
  unsigned long parsed = 0;
  for (char c : text) parsed = parsed * 10u + static_cast<unsigned long>(c - '0');
  if (parsed < low || parsed > high) return false;
  *value = static_cast<unsigned>(parsed);
  return true;
}

// `main`, or `perf:O:H:S`: up to 65535 objects (each one's EntityIdentifier entity number is
// its 1-based index, a 16-bit field), 1 to 1000 reflections per object per second, 1 to 86400
// seconds.
bool parse_scenario(const std::string& value, Scenario* scenario) {
  if (value == "main") return true;
  const std::string prefix = "perf:";
  if (value.compare(0, prefix.size(), prefix) != 0) return false;
  const std::string rest = value.substr(prefix.size());
  const std::size_t first = rest.find(':');
  if (first == std::string::npos) return false;
  const std::size_t second = rest.find(':', first + 1);
  if (second == std::string::npos) return false;
  scenario->perf = true;
  return decimal(rest.substr(0, first), 5, 1, 65535, &scenario->objects) &&
         decimal(rest.substr(first + 1, second - first - 1), 4, 1, 1000, &scenario->hz) &&
         decimal(rest.substr(second + 1), 5, 1, 86400, &scenario->seconds);
}

// Exactly the nine tokens, in this order; anything else is a usage error (OPS-08's rule for
// the worker, applied to its counterpart).
bool parse_arguments(const std::vector<std::string>& tokens, Arguments* out) {
  if (tokens.size() != 9) return false;
  if (!take(tokens[0], "--endpoint=", &out->endpoint) || !valid_endpoint(out->endpoint)) {
    return false;
  }
  if (!take(tokens[1], "--federation-name=", &out->federation) ||
      !valid_name(out->federation)) {
    return false;
  }
  if (!take(tokens[2], "--fom-dir=", &out->fom_dir) || !valid_directory(out->fom_dir)) {
    return false;
  }
  for (std::size_t i = 3; i < 8; ++i) {
    std::string pin;
    if (!take(tokens[i], "--module-sha256=", &pin) || !valid_digest(pin)) return false;
    out->pins.push_back(pin);
  }
  std::string scenario;
  return take(tokens[8], "--scenario=", &scenario) && parse_scenario(scenario, &out->scenario);
}

// ---- bytes and text -----------------------------------------------------------------------------

std::string bytes_of_hex(const char* hex) {
  std::string out;
  const std::string text(hex);
  for (std::size_t i = 0; i + 1 < text.size(); i += 2) {
    out.push_back(static_cast<char>(std::stoi(text.substr(i, 2), nullptr, 16)));
  }
  return out;
}

rti1516e::VariableLengthData data(const std::string& bytes) {
  return rti1516e::VariableLengthData(bytes.data(), bytes.size());
}

// Strict UTF-8 to UTF-32: no overlong form, no surrogate, nothing above U+10FFFF, no truncated
// sequence and no U+0000 (the designator is handed on as a C string). The RTI turns the
// designator back into UTF-8 (`ucsToUtf8`), so a module that is valid UTF-8 reaches it byte for
// byte; one that is not is refused rather than repaired.
bool decode_utf8(const std::string& in, std::wstring* out) {
  std::size_t i = 0;
  while (i < in.size()) {
    const unsigned char lead = static_cast<unsigned char>(in[i]);
    std::uint32_t code = 0;
    std::size_t extra = 0;
    std::uint32_t minimum = 0;
    if (lead < 0x80u) {
      code = lead;
    } else if (lead >= 0xC2u && lead <= 0xDFu) {
      code = lead & 0x1Fu;
      extra = 1;
      minimum = 0x80u;
    } else if (lead >= 0xE0u && lead <= 0xEFu) {
      code = lead & 0x0Fu;
      extra = 2;
      minimum = 0x800u;
    } else if (lead >= 0xF0u && lead <= 0xF4u) {
      code = lead & 0x07u;
      extra = 3;
      minimum = 0x10000u;
    } else {
      return false;
    }
    if (extra > 0 && i + extra >= in.size()) return false;
    for (std::size_t k = 1; k <= extra; ++k) {
      const unsigned char next = static_cast<unsigned char>(in[i + k]);
      if ((next & 0xC0u) != 0x80u) return false;
      code = (code << 6) | (next & 0x3Fu);
    }
    if (code < minimum || code > 0x10FFFFu || (code >= 0xD800u && code <= 0xDFFFu) ||
        code == 0u) {
      return false;
    }
    out->push_back(static_cast<wchar_t>(code));
    i += extra + 1;
  }
  return true;
}

std::string quoted(const std::string& ascii) {
  std::string out;
  sc_hla::append_json_string(&out, ascii);
  return out;
}

// ---- the federate -------------------------------------------------------------------------------

// The callbacks only note what arrived; every RTI call is made after the evoke call returns.
class Ambassador : public rti1516e::NullFederateAmbassador {
 public:
  void connectionLost(std::wstring const&) RTI_THROW((rti1516e::FederateInternalError)) override {
    lost = true;
  }
  void objectInstanceNameReservationSucceeded(std::wstring const& name)
      RTI_THROW((rti1516e::FederateInternalError)) override {
    try {
      reserved.insert(name);
    } catch (...) {
      fault = true;
    }
  }
  void objectInstanceNameReservationFailed(std::wstring const& name)
      RTI_THROW((rti1516e::FederateInternalError)) override {
    try {
      refused.insert(name);
    } catch (...) {
      fault = true;
    }
  }
  void provideAttributeValueUpdate(rti1516e::ObjectInstanceHandle object,
                                   rti1516e::AttributeHandleSet const& attributes,
                                   rti1516e::VariableLengthData const&)
      RTI_THROW((rti1516e::FederateInternalError)) override {
    try {
      requests.push_back(std::make_pair(object, attributes));
    } catch (...) {
      fault = true;
    }
  }

  bool lost = false;
  bool fault = false;
  std::set<std::wstring> reserved;
  std::set<std::wstring> refused;
  std::vector<std::pair<rti1516e::ObjectInstanceHandle, rti1516e::AttributeHandleSet> > requests;
};

// A fixed label for an RTI exception: its type, never its text.
const char* label(const rti1516e::Exception& e) {
  if (dynamic_cast<const rti1516e::FederationExecutionAlreadyExists*>(&e)) {
    return "FederationExecutionAlreadyExists";
  }
  if (dynamic_cast<const rti1516e::FederationExecutionDoesNotExist*>(&e)) {
    return "FederationExecutionDoesNotExist";
  }
  if (dynamic_cast<const rti1516e::FederatesCurrentlyJoined*>(&e)) {
    return "FederatesCurrentlyJoined";
  }
  if (dynamic_cast<const rti1516e::FederateNameAlreadyInUse*>(&e)) {
    return "FederateNameAlreadyInUse";
  }
  if (dynamic_cast<const rti1516e::ConnectionFailed*>(&e)) return "ConnectionFailed";
  if (dynamic_cast<const rti1516e::CouldNotOpenFDD*>(&e)) return "CouldNotOpenFDD";
  if (dynamic_cast<const rti1516e::ErrorReadingFDD*>(&e)) return "ErrorReadingFDD";
  if (dynamic_cast<const rti1516e::InconsistentFDD*>(&e)) return "InconsistentFDD";
  if (dynamic_cast<const rti1516e::CouldNotCreateLogicalTimeFactory*>(&e)) {
    return "CouldNotCreateLogicalTimeFactory";
  }
  if (dynamic_cast<const rti1516e::NameNotFound*>(&e)) return "NameNotFound";
  if (dynamic_cast<const rti1516e::NotConnected*>(&e)) return "NotConnected";
  if (dynamic_cast<const rti1516e::RTIinternalError*>(&e)) return "RTIinternalError";
  return "RTIexception";
}

class Publisher {
 public:
  explicit Publisher(const Arguments& arguments) : arguments_(arguments) {}

  int run() {
    const bool done = arguments_.scenario.perf ? perf() : main_scenario();
    if (done) {
      finish();
    } else {
      abandon();
    }
    return done && !failed_ ? kExitDone : kExitFailed;
  }

 private:
  // ---- events

  void emit(const std::string& json) {
    if (!sc_hla::write_all(1, json + "\n")) stdout_broken_ = true;
  }

  // The first failure of the run, reported once; everything after it is cleanup.
  bool fail(const char* reason) {
    if (!failed_) {
      failed_ = true;
      emit("{\"event\":\"failure\",\"reason\":" + quoted(reason) + ",\"stage\":" +
           quoted(stage_) + "}");
    }
    return false;
  }

  bool fail(const rti1516e::Exception& e) { return fail(label(e)); }

  // ---- the barrier and the callbacks

  // Callbacks that arrived, and the answers to update requests (outside any callback).
  bool service() {
    try {
      ambassador_.requests.clear();
      rti_->evokeMultipleCallbacks(0.0, 0.0);
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    if (ambassador_.fault) return fail("callback");
    if (ambassador_.lost) return fail("connection_lost");
    for (const auto& request : ambassador_.requests) {
      if (!answer(request.first, request.second)) return false;
    }
    if (sc_hla::stop_requested()) return fail("stopped");
    if (stdout_broken_) return fail("stdout");
    return true;
  }

  // provideAttributeValueUpdate: the current values of the requested attributes, as one update
  // tagged `refresh`; nothing when the object has none of them yet or is gone.
  bool answer(rti1516e::ObjectInstanceHandle object,
              const rti1516e::AttributeHandleSet& attributes) {
    std::size_t index = 0;
    for (; index < objects_.size(); ++index) {
      if (objects_[index] == object) break;
    }
    if (index == objects_.size() || deleted_[index]) {
      emit("{\"attributes\":0,\"event\":\"refresh\"}");
      return true;
    }
    rti1516e::AttributeHandleValueMap values;
    for (int a = 0; a < 4; ++a) {
      if (attributes.count(handles_[a]) != 0 && !current_[index][a].empty()) {
        values[handles_[a]] = data(current_[index][a]);
      }
    }
    if (!values.empty()) {
      try {
        rti_->updateAttributeValues(object, values, data(kRefreshTag));
      } catch (const rti1516e::Exception& e) {
        return fail(e);
      }
    }
    emit("{\"attributes\":" + std::to_string(values.size()) + ",\"event\":\"refresh\"}");
    return true;
  }

  // Polls the barrier pipe for up to `milliseconds`; false when it has ended or failed.
  bool read_barrier_pipe(int milliseconds) {
    pollfd pipe = {0, POLLIN, 0};
    const int ready = ::poll(&pipe, 1, milliseconds);
    if (ready < 0) {
      if (errno == EINTR) return true;
      return fail("barrier_pipe");
    }
    if (ready == 0) return true;
    char chunk[256];
    const ssize_t got = ::read(0, chunk, sizeof chunk);
    if (got < 0) {
      if (errno == EINTR || errno == EAGAIN) return true;
      return fail("barrier_pipe");
    }
    if (got == 0) return fail("barrier_closed");
    input_.append(chunk, static_cast<std::size_t>(got));
    if (input_.size() > 1024) return fail("barrier_protocol");
    return true;
  }

  // R38: announce the barrier, then serve callbacks until its number arrives on stdin, for at
  // most 5 seconds.
  bool barrier(int number) {
    stage_ = "barrier";
    emit("{\"barrier\":" + std::to_string(number) + ",\"event\":\"waiting\"}");
    const std::int64_t deadline =
        static_cast<std::int64_t>(sc_hla::monotonic_ns()) + kBarrierNanoseconds;
    while (true) {
      const std::size_t end = input_.find('\n');
      if (end != std::string::npos) {
        const std::string line = input_.substr(0, end);
        input_.erase(0, end + 1);
        if (line != std::to_string(number)) return fail("barrier_protocol");
        emit("{\"barrier\":" + std::to_string(number) + ",\"event\":\"acknowledged\"}");
        return true;
      }
      if (!service()) return false;
      if (static_cast<std::int64_t>(sc_hla::monotonic_ns()) >= deadline) {
        return fail("barrier_timeout");
      }
      if (!read_barrier_pipe(kPollMilliseconds)) return false;
    }
  }

  // ---- the federation

  bool load_modules(std::vector<std::wstring>* designators) {
    stage_ = "modules";
    std::string digests;
    for (std::size_t m = 0; m < 5; ++m) {
      const std::string path = arguments_.fom_dir + "/" + kModules[m];
      const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
      if (fd < 0) return fail("module_unreadable");
      struct stat info;
      std::string bytes;
      bool readable = ::fstat(fd, &info) == 0 && S_ISREG(info.st_mode);
      char chunk[65536];
      while (readable) {
        const ssize_t got = ::read(fd, chunk, sizeof chunk);
        if (got < 0 && errno == EINTR) continue;
        if (got < 0) readable = false;
        if (got <= 0) break;
        bytes.append(chunk, static_cast<std::size_t>(got));
        if (bytes.size() > kMaxModuleBytes) readable = false;
      }
      ::close(fd);
      if (!readable) return fail("module_unreadable");
      const std::string digest = sc_hla_publisher::sha256_hex(bytes);
      if (digest != arguments_.pins[m]) return fail("module_pin");
      std::wstring text;
      if (!decode_utf8(bytes, &text) || sc_hla::to_utf8(text) != bytes) {
        return fail("module_encoding");
      }
      designators->push_back(L"data:text/plain," + text);
      digests += (m == 0 ? "" : ",") + quoted(kModules[m]) + ":" + quoted(digest);
    }
    emit("{\"event\":\"modules\",\"sha256\":{" + digests + "}}");
    return true;
  }

  bool open() {
    std::vector<std::wstring> designators;
    if (!load_modules(&designators)) return false;
    const std::wstring federation = sc_hla::widen_ascii(arguments_.federation);
    try {
      stage_ = "connect";
      rti_ = rti1516e::RTIambassadorFactory().createRTIambassador();
      rti_->connect(ambassador_, rti1516e::HLA_EVOKED, sc_hla::widen_ascii(arguments_.endpoint));
      connected_ = true;
      stage_ = "create";
      rti_->createFederationExecution(federation, designators, L"HLAfloat64Time");
      created_ = true;
      emit("{\"event\":\"created\",\"federation\":" + quoted(arguments_.federation) + "}");
      stage_ = "join";
      rti_->joinFederationExecution(sc_hla::widen_ascii(kFederateName),
                                    sc_hla::widen_ascii(kFederateType), federation);
      joined_ = true;
      stage_ = "publish";
      const rti1516e::ObjectClassHandle physical = rti_->getObjectClassHandle(kPhysicalEntity);
      physical_ = physical;
      ground_vehicle_ = rti_->getObjectClassHandle(kGroundVehicle);
      rti1516e::AttributeHandleSet four;
      for (int a = 0; a < 4; ++a) {
        handles_[a] = rti_->getAttributeHandle(physical, kAttributes[a]);
        four.insert(handles_[a]);
      }
      // NAT-01: both classes, so that the observer's subscription at PhysicalEntity is
      // forwarded to this federate and the GroundVehicle object reaches it.
      rti_->publishObjectClassAttributes(physical, four);
      rti_->publishObjectClassAttributes(ground_vehicle_, four);
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    return true;
  }

  bool register_object(const std::wstring* name) {
    stage_ = "register";
    try {
      objects_.push_back(name == nullptr
                             ? rti_->registerObjectInstance(ground_vehicle_)
                             : rti_->registerObjectInstance(ground_vehicle_, *name));
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    deleted_.push_back(false);
    current_.push_back(std::vector<std::string>(4));
    return true;
  }

  // The class the RTI holds its objects at, read back from the RTI rather than assumed (the
  // evidence of A-CLASS's registration at GroundVehicle), named by the qualified name this process
  // resolved that handle with; every object must be held at the same class, and at one of the two
  // it resolved.
  bool registered_class(std::string* name) {
    stage_ = "register";
    try {
      const rti1516e::ObjectClassHandle known = rti_->getKnownObjectClassHandle(objects_[0]);
      for (std::size_t i = 1; i < objects_.size(); ++i) {
        if (rti_->getKnownObjectClassHandle(objects_[i]) != known) {
          return fail("registered_class");
        }
      }
      if (known == ground_vehicle_) {
        *name = kGroundVehicleName;
        return true;
      }
      if (known == physical_) {
        *name = kPhysicalEntityName;
        return true;
      }
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    return fail("registered_class");
  }

  // The object name of the bundled capture, reserved before it is registered.
  bool reserve(const std::wstring& name) {
    stage_ = "reserve";
    try {
      rti_->reserveObjectInstanceName(name);
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    const std::int64_t deadline =
        static_cast<std::int64_t>(sc_hla::monotonic_ns()) + kBarrierNanoseconds;
    while (ambassador_.reserved.count(name) == 0) {
      if (ambassador_.refused.count(name) != 0) return fail("name_reservation");
      if (!service()) return false;
      if (static_cast<std::int64_t>(sc_hla::monotonic_ns()) >= deadline) {
        return fail("name_reservation");
      }
      if (!read_barrier_pipe(kPollMilliseconds)) return false;
    }
    return true;
  }

  bool update(std::size_t index, const std::vector<std::pair<Attribute, std::string> >& values,
              const std::string& tag) {
    rti1516e::AttributeHandleValueMap map;
    for (const auto& value : values) {
      map[handles_[value.first]] = data(value.second);
      current_[index][value.first] = value.second;
    }
    try {
      rti_->updateAttributeValues(objects_[index], map, data(tag));
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    return true;
  }

  bool remove(std::size_t index, const std::string& tag) {
    try {
      rti_->deleteObjectInstance(objects_[index], data(tag));
    } catch (const rti1516e::Exception& e) {
      return fail(e);
    }
    deleted_[index] = true;
    return true;
  }

  void sent(int step) {
    emit("{\"event\":\"sent\",\"step\":" + std::to_string(step) + "}");
  }

  // ---- the scenarios

  bool main_scenario() {
    if (!open()) return false;
    const std::wstring name = sc_hla::widen_ascii(kObjectName);
    std::string registered;
    if (!reserve(name) || !register_object(&name) || !registered_class(&registered)) return false;
    emit("{\"class\":" + quoted(registered) + ",\"event\":\"ready\",\"object_name\":" +
         quoted(kObjectName) + ",\"objects\":1}");
    // Barrier 0: the observer has discovered the object.
    if (!barrier(0)) return false;
    stage_ = "step";
    if (!update(0, {{kIdentifier, bytes_of_hex(kEntityIdentifier)},
                    {kType, bytes_of_hex(kEntityType)}}, "step-1")) {
      return false;
    }
    sent(1);
    if (!barrier(1)) return false;
    stage_ = "step";
    if (!update(0, {{kForce, bytes_of_hex(kForceIdentifier)}}, "step-2")) return false;
    sent(2);
    if (!barrier(2)) return false;
    stage_ = "step";
    if (!update(0, {{kSpatial, bytes_of_hex(kSpatialEquator)}}, "step-3")) return false;
    sent(3);
    if (!barrier(3)) return false;
    stage_ = "step";
    if (!update(0, {{kSpatial, bytes_of_hex(kSpatialSecond)}}, "step-4")) return false;
    sent(4);
    if (!barrier(4)) return false;
    stage_ = "step";
    if (!remove(0, "step-5")) return false;
    sent(5);
    if (!barrier(5)) return false;
    // Barrier 6: the observer has resigned; only now may the federation be destroyed.
    return barrier(6);
  }

  // The EntityIdentifier of perf object `index`: site 1, application 2 (as V-ID-123), entity
  // number index + 1, each an unsigned 16-bit big-endian field written out byte by byte.
  static std::string perf_identifier(std::size_t index) {
    const unsigned entity = static_cast<unsigned>(index + 1);
    std::string out = bytes_of_hex("00010002");
    out.push_back(static_cast<char>((entity >> 8) & 0xFFu));
    out.push_back(static_cast<char>(entity & 0xFFu));
    return out;
  }

  bool perf() {
    if (!open()) return false;
    const Scenario& s = arguments_.scenario;
    for (unsigned i = 0; i < s.objects; ++i) {
      if (!register_object(nullptr)) return false;
    }
    std::string registered;
    if (!registered_class(&registered)) return false;
    emit("{\"class\":" + quoted(registered) +
         ",\"event\":\"ready\",\"object_name\":null,\"objects\":" + std::to_string(s.objects) +
         "}");
    if (!barrier(0)) return false;
    stage_ = "identity";
    for (std::size_t i = 0; i < objects_.size(); ++i) {
      if (!update(i, {{kIdentifier, perf_identifier(i)}, {kType, bytes_of_hex(kEntityType)},
                      {kForce, bytes_of_hex(kForceIdentifier)}}, "perf-identity")) {
        return false;
      }
    }
    sent(1);
    if (!barrier(1)) return false;
    stage_ = "load";
    const std::string spatial = bytes_of_hex(kSpatialEquator);
    const std::uint64_t ticks = static_cast<std::uint64_t>(s.seconds) * s.hz;
    const std::uint64_t period = 1000000000u / s.hz;
    const std::uint64_t start = sc_hla::monotonic_ns();
    for (std::uint64_t tick = 0; tick < ticks; ++tick) {
      const std::uint64_t due = start + tick * period;
      while (sc_hla::monotonic_ns() < due) {
        if (!service()) return false;
        const std::uint64_t left = due - sc_hla::monotonic_ns();
        const int wait = left > 5000000u ? kPollMilliseconds : 0;
        if (!read_barrier_pipe(wait)) return false;
      }
      for (std::size_t i = 0; i < objects_.size(); ++i) {
        if (!update(i, {{kSpatial, spatial}}, "perf")) return false;
      }
      if (!service()) return false;
    }
    sent(2);
    if (!barrier(2)) return false;
    stage_ = "remove";
    for (std::size_t i = 0; i < objects_.size(); ++i) {
      if (!remove(i, "perf-remove")) return false;
    }
    sent(3);
    if (!barrier(3)) return false;
    return barrier(4);
  }

  // ---- the end

  // After the last barrier: resign, destroy the federation this process created, disconnect.
  void finish() {
    try {
      stage_ = "resign";
      rti_->resignFederationExecution(rti1516e::NO_ACTION);
      joined_ = false;
      emit("{\"event\":\"resigned\"}");
      stage_ = "destroy";
      rti_->destroyFederationExecution(sc_hla::widen_ascii(arguments_.federation));
      created_ = false;
      emit("{\"event\":\"destroyed\",\"federation\":" + quoted(arguments_.federation) + "}");
      stage_ = "disconnect";
      rti_->disconnect();
      connected_ = false;
      emit("{\"event\":\"disconnected\"}");
    } catch (const rti1516e::Exception& e) {
      fail(e);
      abandon();
    }
  }

  // After a failure, a stop or a closed pipe: take back what this process made, in order, and
  // say what each step did. A federation is destroyed only if this process created it.
  void abandon() {
    if (joined_) {
      stage_ = "resign";
      try {
        rti_->resignFederationExecution(rti1516e::DELETE_OBJECTS);
        emit("{\"event\":\"resigned\"}");
      } catch (const rti1516e::Exception& e) {
        emit("{\"event\":\"cleanup\",\"reason\":" + quoted(label(e)) + ",\"stage\":\"resign\"}");
      }
      joined_ = false;
    }
    if (created_) {
      try {
        rti_->destroyFederationExecution(sc_hla::widen_ascii(arguments_.federation));
        emit("{\"event\":\"destroyed\",\"federation\":" + quoted(arguments_.federation) + "}");
      } catch (const rti1516e::Exception& e) {
        emit("{\"event\":\"cleanup\",\"reason\":" + quoted(label(e)) + ",\"stage\":\"destroy\"}");
      }
      created_ = false;
    }
    if (connected_) {
      try {
        rti_->disconnect();
        emit("{\"event\":\"disconnected\"}");
      } catch (const rti1516e::Exception& e) {
        emit("{\"event\":\"cleanup\",\"reason\":" + quoted(label(e)) +
             ",\"stage\":\"disconnect\"}");
      }
      connected_ = false;
    }
  }

  const Arguments& arguments_;
  Ambassador ambassador_;
  RTI_UNIQUE_PTR<rti1516e::RTIambassador> rti_;
  rti1516e::ObjectClassHandle physical_;
  rti1516e::ObjectClassHandle ground_vehicle_;
  rti1516e::AttributeHandle handles_[4];
  std::vector<rti1516e::ObjectInstanceHandle> objects_;
  std::vector<bool> deleted_;
  std::vector<std::vector<std::string> > current_;
  std::string input_;
  std::string stage_ = "start";
  bool connected_ = false;
  bool created_ = false;
  bool joined_ = false;
  bool failed_ = false;
  bool stdout_broken_ = false;
};

}  // namespace

int main(int argc, char** argv) {
  // NAV-01: OpenRTI would write its log to stdout, the event channel.
  sc_hla::clear_openrti_debug_variables();
  const std::vector<std::string> tokens(argv + 1, argv + argc);
  if (tokens.size() == 1 && tokens[0] == "--version") {
    return sc_hla::write_all(1, kVersionLine) ? kExitDone : kExitFailed;
  }
  Arguments arguments;
  if (!parse_arguments(tokens, &arguments)) {
    sc_hla::write_all(2, "sc-hla-publisher: usage: sc-hla-publisher --version | "
                         "--endpoint=rti://ADDRESS:PORT --federation-name=NAME "
                         "--fom-dir=DIRECTORY --module-sha256=HEX (5 times) "
                         "--scenario=main|perf:OBJECTS:HZ:SECONDS\n");
    return kExitUsage;
  }
  // SIGPIPE ignored (a closed event pipe is an EPIPE the run ends on), SIGTERM a flag.
  sc_hla::install_signal_handlers();
  Publisher publisher(arguments);
  return publisher.run();
}
