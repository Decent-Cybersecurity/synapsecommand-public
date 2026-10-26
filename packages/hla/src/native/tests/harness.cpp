// sc-hla-harness: test only, never installed (NAT-07 a).
//
//   sc-hla-harness --scenario=NAME --fom-dir=DIR --log=FILE [--stop-when-ready]
//                  (--version | --endpoint=... --federation-name=... --federate-name=...)
//
// It is the worker with its event loop replaced by a scenario: the same argument checks, the same
// status channel on fd 3, the same frame queue and writer on stdout, the same Observer, run
// against an RTIambassador on thread:// (OpenRTI in this process, no rtinode) wrapped in the
// recording decorator. A second federate of its own, the setup federate, creates the federation
// there from the five RPR FOM modules in DIR and supplies real handles (an attribute the observer
// does not subscribe to, a class it does not subscribe at, decoded object instance and retraction
// handles). The scenario then calls the observer's FederateAmbassador overloads directly with
// hand-built values and ends each batch as the event loop does, to produce the callbacks the
// pinned RTI never delivers (OPS-05, NAT-07). The endpoint token is checked like the worker's and
// then not used: the harness connects to thread://, except in real-rti (below).
//
// A few scenarios also have the decorator fail one of the observer's RTI calls (the table
// faults() below; CR-new-R7-10, CR-new-R7-16), and one, name-in-use, has the setup federate join
// under the observer's own federate name, so that the RTI itself refuses the observer's join.
//
// One scenario, real-rti, has no setup federate and no thread:// federation at all: the observer,
// still wrapped in the recording decorator, connects to the endpoint it was given (a real
// rtinode) and joins the federation another process created, then runs the worker's own event
// loop until SIGTERM. The decorator's log is then the record of every RTI call the observer made
// during a real session (A-NO-PUBLISH, A-NO-CREATE).
//
// After the scenario: a terminal condition is closed like the worker closes it; otherwise the
// harness writes {"event":"ready"} to the log and runs the worker's event loop until SIGTERM (or
// raises SIGTERM itself with --stop-when-ready), a gone parent or a broken channel. The exit
// status is the worker's. The log (JSON lines) holds the decorator's call log and the harness's
// own events; each start of the process claims the next attempt number (FILE.attempt-N).
//
// The assertions are not here: the tests read the frames, the status records, the log and the
// exit status (tests/test_hla_native.py).

// <memory> first, before any RTI header. Below C++17 the rti1516e headers hand out
// std::auto_ptr (RTI_UNIQUE_PTR) but never include <memory>: libc++ happens to declare it
// through other headers, libstdc++ (GCC 13, the reference compiler) does not, and the build
// fails there without this line (Linux reference run, finding F1).
#include <memory>

#include <RTI/NullFederateAmbassador.h>
#include <RTI/RTIambassador.h>
#include <RTI/RTIambassadorFactory.h>
#include <RTI/time/HLAfloat64Time.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>

#include <cstdint>
#include <functional>
#include <map>
#include <string>
#include <vector>

#include "channels.h"
#include "constants.h"
#include "observer.h"
#include "process.h"
#include "recording_ambassador.h"
#include "test_time.h"
#include "text.h"

namespace {

using sc_hla_test::CallLog;
using sc_hla_test::RecordingAmbassador;
using sc_hla_test::RecordingSource;
using sc_hla_test::TestTime;

// A failure of the harness itself (its setup federate), never one of the worker's statuses.
const int kExitHarness = 90;

// Thrown before the setup federate is made, for the scenario that has none (real-rti).
struct RealRti {};

struct HarnessOptions {
  std::string scenario;
  std::string fom_dir;
  std::string log;
  bool stop_when_ready = false;
};

bool take(const std::string& token, const char* prefix, std::string* value) {
  const std::string p(prefix);
  if (token.compare(0, p.size(), p) != 0) return false;
  *value = token.substr(p.size());
  return true;
}

// The harness's own tokens come first; what follows is the worker's argument vector.
bool parse_harness(std::vector<std::string>* tokens, HarnessOptions* options) {
  std::size_t used = 0;
  for (; used < tokens->size(); ++used) {
    const std::string& token = (*tokens)[used];
    if (take(token, "--scenario=", &options->scenario)) continue;
    if (take(token, "--fom-dir=", &options->fom_dir)) continue;
    if (take(token, "--log=", &options->log)) continue;
    if (token == "--stop-when-ready") {
      options->stop_when_ready = true;
      continue;
    }
    break;
  }
  tokens->erase(tokens->begin(), tokens->begin() + static_cast<std::ptrdiff_t>(used));
  return !options->scenario.empty() && !options->fom_dir.empty() && !options->log.empty();
}

std::string bytes_from_hex(const std::string& hex) {
  std::string out;
  for (std::size_t i = 0; i + 1 < hex.size(); i += 2) {
    out.push_back(static_cast<char>(std::stoi(hex.substr(i, 2), nullptr, 16)));
  }
  return out;
}

std::string repeated(std::size_t count, unsigned char byte) {
  return std::string(count, static_cast<char>(byte));
}

// 00 01 02 ... ff.
std::string every_byte() {
  std::string out;
  for (int i = 0; i < 256; ++i) out.push_back(static_cast<char>(i));
  return out;
}

rti1516e::VariableLengthData data(const std::string& bytes) {
  return rti1516e::VariableLengthData(bytes.data(), bytes.size());
}

std::string big_endian(std::uint64_t value, std::size_t length) {
  std::string out(length, '\0');
  for (std::size_t i = 0; i < length; ++i) {
    out[length - 1 - i] = static_cast<char>((value >> (8 * i)) & 0xFFu);
  }
  return out;
}

std::wstring wide(const char* ascii) { return sc_hla::widen_ascii(ascii); }

// The values the scenarios send, the same as the bundled capture's where they can be (SPEC:66).
const char kEntityIdentifier[] = "000100020003";
const char kEntityType[] = "010100e101020304";
// The bundled capture's first Spatial (DRM_FPW at 6378137, 0, 0 moving 10 m/s along y), with
// its uninterpreted bytes 1..7 and 33..35 set to a1..a7 and b1..b3: padding the worker must
// copy, not clear (R16, R18).
const char kSpatialPadded[] =
    "02a1a2a3a4a5a6a7415854a6400000000000000000000000000000000000000000b1b2b3"
    "000000000000000000000000000000004120000000000000";

// The FOM of the missing-name scenario: PhysicalEntity with three of the four attributes, given
// to the RTI as a data: module (NAT-19), so no file of the harness's own is needed.
const char kReducedFom[] =
    "data:text/plain,<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
    "<objectModel xmlns=\"http://standards.ieee.org/IEEE1516-2010\">"
    "<modelIdentification><name>HarnessReducedFom</name><type>FOM</type><version>1</version>"
    "</modelIdentification><objects><objectClass><name>HLAobjectRoot</name>"
    "<objectClass><name>BaseEntity</name><sharing>PublishSubscribe</sharing>"
    "<attribute><name>EntityType</name><dataType>HLAopaqueData</dataType>"
    "<updateType>Static</updateType><ownership>NoTransfer</ownership>"
    "<sharing>PublishSubscribe</sharing><transportation>HLAreliable</transportation>"
    "<order>Receive</order></attribute>"
    "<attribute><name>EntityIdentifier</name><dataType>HLAopaqueData</dataType>"
    "<updateType>Static</updateType><ownership>NoTransfer</ownership>"
    "<sharing>PublishSubscribe</sharing><transportation>HLAreliable</transportation>"
    "<order>Receive</order></attribute>"
    "<objectClass><name>PhysicalEntity</name><sharing>PublishSubscribe</sharing>"
    "<attribute><name>ForceIdentifier</name><dataType>HLAopaqueData</dataType>"
    "<updateType>Static</updateType><ownership>NoTransfer</ownership>"
    "<sharing>PublishSubscribe</sharing><transportation>HLAreliable</transportation>"
    "<order>Receive</order></attribute>"
    "</objectClass></objectClass></objectClass></objects></objectModel>";

class SetupAmbassador : public rti1516e::NullFederateAmbassador {
 public:
  explicit SetupAmbassador(CallLog& log) : log_(log) {}
  void provideAttributeValueUpdate(rti1516e::ObjectInstanceHandle,
                                   rti1516e::AttributeHandleSet const& theAttributes,
                                   rti1516e::VariableLengthData const& theUserSuppliedTag)
      RTI_THROW((rti1516e::FederateInternalError)) override {
    provided += 1;
    log_.line("{\"attributes\":" + std::to_string(theAttributes.size()) +
              ",\"setup\":\"provideAttributeValueUpdate\",\"tag_bytes\":" +
              std::to_string(theUserSuppliedTag.size()) + "}");
  }
  int provided = 0;

 private:
  CallLog& log_;
};

// A callback the harness calls itself, as the RTI calls one from inside evokeMultipleCallbacks:
// while it runs the decorator refuses every RTI call (R12).
class Direct {
 public:
  Direct(rti1516e::FederateAmbassador& target, RecordingAmbassador& recorder)
      : target_(target), recorder_(recorder) {
    recorder_.set_in_callback(true);
  }
  ~Direct() { recorder_.set_in_callback(false); }
  Direct(const Direct&) = delete;
  Direct& operator=(const Direct&) = delete;
  rti1516e::FederateAmbassador* operator->() { return &target_; }

 private:
  rti1516e::FederateAmbassador& target_;
  RecordingAmbassador& recorder_;
};

struct World {
  sc_hla::Observer& observer;
  sc_hla::FrameQueue& frames;
  rti1516e::RTIambassador& setup;
  SetupAmbassador& setup_ambassador;
  RecordingAmbassador& recorder;
  CallLog& log;
  int attempt;
  rti1516e::ObjectClassHandle physical_entity;
  rti1516e::ObjectClassHandle ground_vehicle;
  std::map<std::string, rti1516e::AttributeHandle> attribute;
  rti1516e::FederateHandle setup_federate;

  rti1516e::ObjectInstanceHandle object(std::uint64_t number) {
    return setup.decodeObjectInstanceHandle(data(big_endian(number, 8)));
  }
  rti1516e::MessageRetractionHandle retraction(std::uint64_t number) {
    return setup.decodeMessageRetractionHandle(
        data(big_endian(1, 4) + big_endian(number, 8)));
  }
  // A handle that is no attribute of PhysicalEntity: getAttributeName refuses it.
  rti1516e::AttributeHandle undefined_attribute() {
    return setup.decodeAttributeHandle(data(big_endian(4000, 8)));
  }
  rti1516e::AttributeHandleValueMap values(
      const std::vector<std::pair<std::string, std::string> >& pairs) {
    rti1516e::AttributeHandleValueMap out;
    for (const auto& pair : pairs) out[attribute.at(pair.first)] = data(pair.second);
    return out;
  }

  void discover(std::uint64_t number, const std::wstring& name) {
    Direct(observer, recorder)->discoverObjectInstance(object(number), physical_entity, name);
  }
  void reflect(std::uint64_t number, const rti1516e::AttributeHandleValueMap& map,
               const std::string& tag = std::string(),
               rti1516e::OrderType sent = rti1516e::RECEIVE,
               rti1516e::TransportationType transport = rti1516e::RELIABLE) {
    Direct(observer, recorder)->reflectAttributeValues(
        object(number), map, data(tag), sent, transport, rti1516e::SupplementalReflectInfo());
  }
  void reflect_timed(std::uint64_t number, const rti1516e::AttributeHandleValueMap& map,
                     const std::string& tag, rti1516e::OrderType sent,
                     rti1516e::TransportationType transport, const rti1516e::LogicalTime& time,
                     rti1516e::OrderType received) {
    Direct(observer, recorder)->reflectAttributeValues(object(number), map, data(tag), sent,
                                                       transport, time, received,
                                                       rti1516e::SupplementalReflectInfo());
  }
  void remove(std::uint64_t number, const std::string& tag = std::string(),
              rti1516e::OrderType sent = rti1516e::RECEIVE) {
    Direct(observer, recorder)->removeObjectInstance(object(number), data(tag), sent,
                                                     rti1516e::SupplementalRemoveInfo());
  }
  void remove_timed(std::uint64_t number, const std::string& tag,
                    const rti1516e::LogicalTime& time, rti1516e::OrderType received) {
    Direct(observer, recorder)->removeObjectInstance(object(number), data(tag), rti1516e::RECEIVE,
                                                     time, received,
                                                     rti1516e::SupplementalRemoveInfo());
  }
  void end_batch() { observer.end_batch(); }
};

// ---- the scenarios ------------------------------------------------------------------------------

void idle(World&) {}

// Bytes copied unchanged: a tag and an attribute value with every byte value, padding, orders,
// transports, logical times of both kinds, every overload (R12, R13, R16, NAT-17). The map and
// the tag of the first reflection are overwritten after the callback returned and before the
// batch ends: the frame must still carry what the callback was given (R12: copied in the
// callback, never referenced).
void bytes(World& w) {
  Direct(w.observer, w.recorder)
      ->discoverObjectInstance(w.object(1), w.physical_entity, L"bytes-object", w.setup_federate);
  rti1516e::AttributeHandleValueMap map =
      w.values({{"Spatial", bytes_from_hex(kSpatialPadded)},
                {"EntityIdentifier", bytes_from_hex(kEntityIdentifier)}});
  rti1516e::VariableLengthData tag = data(every_byte());
  Direct(w.observer, w.recorder)
      ->reflectAttributeValues(w.object(1), map, tag, rti1516e::RECEIVE, rti1516e::BEST_EFFORT,
                               rti1516e::SupplementalReflectInfo());
  const std::string overwrite = repeated(256, 0xee);
  for (auto& entry : map) entry.second.setData(overwrite.data(), overwrite.size());
  tag.setData(overwrite.data(), overwrite.size());
  w.reflect(1, w.values({{"EntityType", every_byte()}}), std::string(), rti1516e::TIMESTAMP,
            rti1516e::RELIABLE);
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}),
                  bytes_from_hex("ff"), rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  rti1516e::HLAfloat64Time(5.0), rti1516e::TIMESTAMP);
  w.reflect_timed(1, w.values({{"EntityType", bytes_from_hex(kEntityType)}}), std::string(),
                  rti1516e::RECEIVE, rti1516e::BEST_EFFORT,
                  TestTime(L"Harness-Time", every_byte()), rti1516e::RECEIVE);
  w.end_batch();
  Direct(w.observer, w.recorder)
      ->removeObjectInstance(w.object(1), data(bytes_from_hex("beef")), rti1516e::TIMESTAMP,
                             rti1516e::HLAfloat64Time(7.0), rti1516e::TIMESTAMP,
                             rti1516e::SupplementalRemoveInfo());
  w.discover(2, L"bytes-object-2");
  w.remove(2, bytes_from_hex("00"), rti1516e::TIMESTAMP);
  w.end_batch();
}

// A-ATTRIBUTE-LIMIT: 4096 bytes are captured (the decoder refuses the length), 4097 never.
void limit_value(World& w) {
  w.discover(1, L"limit-object");
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4096, 0x5a)}}));
  w.end_batch();
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4097, 0x5a)}}));
  w.end_batch();
}

// A-TAG-LIMIT on a reflection, then on a removal.
void limit_tag_reflect(World& w) {
  w.discover(1, L"limit-object");
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), repeated(4096, 0x7e));
  w.end_batch();
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), repeated(4097, 0x7e));
  w.end_batch();
}

void limit_tag_remove(World& w) {
  w.discover(1, L"limit-object");
  w.remove(1, repeated(4096, 0x7e));
  w.end_batch();
  w.remove(1, repeated(4097, 0x7e));
  w.end_batch();
}

// The encoded logical time: 256 bytes captured, 257 refused.
void limit_time(World& w) {
  w.discover(1, L"limit-object");
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(L"Harness-Time", repeated(256, 0x11)), rti1516e::TIMESTAMP);
  w.end_batch();
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(L"Harness-Time", repeated(257, 0x11)), rti1516e::TIMESTAMP);
  w.end_batch();
}

// The object name is counted in UTF-8 bytes: 512 two-byte characters are 1024 bytes, and one
// more ASCII character is over the limit.
void limit_name(World& w) {
  w.discover(1, std::wstring(512, static_cast<wchar_t>(0xE9)));
  w.end_batch();
  w.discover(2, std::wstring(512, static_cast<wchar_t>(0xE9)) + L"a");
  w.end_batch();
}

// NAT-06 (1): more than four supplied attributes, nothing copied.
void limit_attributes(World& w) {
  w.discover(1, L"limit-object");
  w.reflect(1, w.values({{"EntityIdentifier", bytes_from_hex(kEntityIdentifier)},
                         {"EntityType", bytes_from_hex(kEntityType)},
                         {"Spatial", bytes_from_hex(kSpatialPadded)},
                         {"ForceIdentifier", bytes_from_hex("01")},
                         {"DamageState", bytes_from_hex("00000001")}}));
  w.end_batch();
}

// A-UNSUBSCRIBED, the native half: an attribute the observer did not subscribe to beside known
// ones is captured under the name the RTI gives it after the evoke call, sorted by name; four
// supplied with one unknown are captured too. The second lookup of the same handle is cached.
void unsubscribed(World& w) {
  w.discover(1, L"unsubscribed-object");
  w.reflect(1, w.values({{"EntityIdentifier", bytes_from_hex(kEntityIdentifier)},
                         {"DamageState", bytes_from_hex("00000001")}}));
  w.end_batch();
  w.reflect(1, w.values({{"EntityType", bytes_from_hex(kEntityType)},
                         {"ForceIdentifier", bytes_from_hex("01")},
                         {"Spatial", bytes_from_hex(kSpatialPadded)},
                         {"DamageState", bytes_from_hex("00000002")}}));
  w.end_batch();
}

// A-RETRACT, the native half: both retraction-handle overloads are captured as retractable.
void retract(World& w) {
  w.discover(1, L"retract-object");
  Direct(w.observer, w.recorder)
      ->reflectAttributeValues(w.object(1), w.values({{"ForceIdentifier", bytes_from_hex("01")}}),
                               data(std::string()), rti1516e::TIMESTAMP, rti1516e::BEST_EFFORT,
                               rti1516e::HLAfloat64Time(1.5), rti1516e::TIMESTAMP,
                               w.retraction(7), rti1516e::SupplementalReflectInfo());
  Direct(w.observer, w.recorder)
      ->removeObjectInstance(w.object(1), data(std::string()), rti1516e::TIMESTAMP,
                             rti1516e::HLAfloat64Time(2.5), rti1516e::TIMESTAMP, w.retraction(8),
                             rti1516e::SupplementalRemoveInfo());
  w.end_batch();
}

// A-RETRACT: requestRetraction has no object mapping and ends the generation (SPEC:281).
void retraction_request(World& w) {
  w.discover(1, L"retract-object");
  Direct(w.observer, w.recorder)->requestRetraction(w.retraction(9));
  w.end_batch();
}

// A-EMPTY, the native half: an empty map is a captured empty reflection (SPEC:279).
void empty(World& w) {
  w.discover(1, L"empty-object");
  w.reflect(1, rti1516e::AttributeHandleValueMap(), std::string());
  w.end_batch();
}

// NAT-11, R25: a handle keeps its token after removal; a new discovery of it is a new object.
void reuse(World& w) {
  w.discover(1, L"first-life");
  w.end_batch();
  w.remove(1);
  w.end_batch();
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}));
  w.remove(1);
  w.end_batch();
  w.discover(1, L"second-life");
  w.discover(1, L"second-life");
  w.end_batch();
  w.remove(1);
  w.reflect(2, w.values({{"ForceIdentifier", bytes_from_hex("02")}}));
  w.discover(2, L"late-discovery");
  w.end_batch();
}

// NAV-04 and R12: a request for each object discovered in a batch, after the callbacks; the RTI
// does not know these handles, and ObjectInstanceNotKnown is no failure. A repeated discovery
// asks nothing.
void requests(World& w) {
  w.discover(1, L"requested-1");
  w.discover(2, L"requested-2");
  w.remove(2);
  w.end_batch();
  w.discover(1, L"requested-1");
  w.end_batch();
}

// SPEC:289: a name with a code point no UTF-8 can carry ends the session.
void name_surrogate(World& w) {
  w.discover(1, L"valid-name");
  w.end_batch();
  w.discover(2, L"bad-" + std::wstring(1, static_cast<wchar_t>(0xD800)) + L"-name");
  w.end_batch();
}

void name_beyond(World& w) {
  w.discover(1, L"big-" + std::wstring(1, static_cast<wchar_t>(0x110000)));
  w.end_batch();
}

// Names are data: control characters, quotes, reverse solidus, DEL and characters beyond the
// BMP reach the frame exactly.
void name_text(World& w) {
  std::wstring name = L"a";
  name.push_back(static_cast<wchar_t>(0x01));
  name.push_back(static_cast<wchar_t>(0x1F));
  name += L"\"q\\";
  name.push_back(static_cast<wchar_t>(0x7F));
  name.push_back(static_cast<wchar_t>(0xE9));
  name.push_back(static_cast<wchar_t>(0x1F600));
  name.push_back(static_cast<wchar_t>(0x0A));
  w.discover(1, name);
  w.end_batch();
}

// NAT-06 (2): the name of an unknown handle, looked up after the evoke call.
void attribute_name_refused(World& w) {
  w.discover(1, L"named-object");
  rti1516e::AttributeHandleValueMap map =
      w.values({{"EntityIdentifier", bytes_from_hex(kEntityIdentifier)}});
  map[w.undefined_attribute()] = data(bytes_from_hex("01"));
  w.reflect(1, map);
  w.end_batch();
}

void attribute_name_injected(World& w, const std::wstring& name,
                             const std::vector<std::pair<std::string, std::string> >& values) {
  w.recorder.inject_name(w.attribute.at("DamageState"), name);
  w.discover(1, L"named-object");
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}));
  w.reflect(1, w.values(values));
  w.end_batch();
}

void attribute_name_long(World& w) {
  attribute_name_injected(w, std::wstring(129, L'N'), {{"DamageState", bytes_from_hex("01")}});
}

void attribute_name_128(World& w) {
  attribute_name_injected(w, std::wstring(64, static_cast<wchar_t>(0xE9)),
                          {{"DamageState", bytes_from_hex("01")}});
}

void attribute_name_invalid(World& w) {
  attribute_name_injected(w, L"Damage" + std::wstring(1, static_cast<wchar_t>(0xD800)),
                          {{"DamageState", bytes_from_hex("01")}});
}

void attribute_name_collision(World& w) {
  attribute_name_injected(w, L"Spatial", {{"Spatial", bytes_from_hex(kSpatialPadded)},
                                          {"DamageState", bytes_from_hex("01")}});
}

// The logical time's implementation name: 128 bytes kept, 129 refused, not Unicode refused.
void time_name_long(World& w) {
  w.discover(1, L"timed-object");
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(std::wstring(128, L'T'), bytes_from_hex("0102")), rti1516e::TIMESTAMP);
  w.end_batch();
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(std::wstring(129, L'T'), bytes_from_hex("0102")), rti1516e::TIMESTAMP);
  w.end_batch();
}

void time_name_invalid(World& w) {
  w.discover(1, L"timed-object");
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(L"T" + std::wstring(1, static_cast<wchar_t>(0xDFFF)),
                           bytes_from_hex("0102")),
                  rti1516e::TIMESTAMP);
  w.end_batch();
}

// NAT-04: a discovery at any class but PhysicalEntity.
void class_other(World& w) {
  Direct(w.observer, w.recorder)
      ->discoverObjectInstance(w.object(1), w.ground_vehicle, L"vehicle");
  w.end_batch();
}

// Metadata outside the HLA enumerations cannot be represented in a frame.
void order_invalid(World& w) {
  w.discover(1, L"ordered-object");
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
            static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

// R12: connectionLost is terminal (E_RTI_CONNECT); the next attempt of the host plays idle.
void connection_lost(World& w) {
  if (w.attempt > 1) return;
  w.discover(1, L"lost-object");
  Direct(w.observer, w.recorder)->connectionLost(L"the harness dropped the connection");
  w.end_batch();
}

// A-OVERFLOW by count: one batch of 4097 records; the queue holds 4096 (the discover and 4095
// reflections) and refuses the next. Each reflection's tag is its number (4 bytes, big-endian,
// from 0), so that the frames show which ones were kept.
void overflow_count(World& w) {
  w.frames.wait_drained();
  w.discover(1, L"c");
  for (std::uint64_t i = 0; i < 4096; ++i) {
    w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(i, 4));
  }
  w.end_batch();
}

// A-OVERFLOW by bytes: one batch of reflections with 16388 copied bytes each (four values of
// 4096 bytes and the 4-byte number as tag) after a discover of one byte: 1 + 1023 * 16388 =
// 16764925 bytes fit 16 MiB (16777216), the 1024th reflection does not; the 12291 bytes left
// would hold a diagnostic, which the worker still does not send through the queue that has just
// refused a record.
void overflow_bytes(World& w) {
  w.frames.wait_drained();
  w.discover(1, L"b");
  for (std::uint64_t i = 0; i < 4096; ++i) {
    w.reflect(1, w.values({{"EntityIdentifier", repeated(4096, 0x01)},
                           {"EntityType", repeated(4096, 0x02)},
                           {"ForceIdentifier", repeated(4096, 0x03)},
                           {"Spatial", repeated(4096, 0x04)}}),
              big_endian(i, 4));
  }
  w.end_batch();
}

// A-OVERFLOW with a reader that does not read: one numbered reflection per batch, each handed to
// the writer, until the pipe and then the queue are full.
void overflow_stalled(World& w) {
  w.discover(1, L"stalled-object");
  w.end_batch();
  for (std::uint64_t i = 0; i < 1000000 && !w.observer.has_condition(); ++i) {
    w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(i, 4));
    w.end_batch();
  }
}

// NAT-11: 100000 tokens, then one more. Reflections of handles nobody discovered each take a
// token; the batches are kept below the queue's bound by waiting for the writer.
void tokens(World& w) {
  for (std::uint64_t number = 1; number <= 100001 && !w.observer.has_condition(); ++number) {
    w.reflect(number, w.values({{"ForceIdentifier", bytes_from_hex("01")}}));
    if (number % 1000 == 0) {
      w.end_batch();
      w.frames.wait_drained();
    }
  }
  w.end_batch();
}

// The RTI's own callbacks, in this process: the setup federate registers an object, the observer's
// event loop discovers it and asks for its values (the setup federate is asked for exactly the
// four attributes with an empty tag), the setup federate updates and then deletes it.
void live(World& w) {
  rti1516e::AttributeHandleSet four;
  four.insert(w.attribute.at("EntityIdentifier"));
  four.insert(w.attribute.at("EntityType"));
  four.insert(w.attribute.at("Spatial"));
  four.insert(w.attribute.at("ForceIdentifier"));
  w.setup.publishObjectClassAttributes(w.physical_entity, four);
  const rti1516e::ObjectInstanceHandle object = w.setup.registerObjectInstance(w.physical_entity);
  const std::uint64_t start = sc_hla::monotonic_ns();
  const std::uint64_t limit = 10000000000u;
  while (w.setup_ambassador.provided == 0 && sc_hla::monotonic_ns() - start < limit) {
    if (!w.observer.step()) return;
    w.setup.evokeMultipleCallbacks(0.0, 0.01);
  }
  w.setup.updateAttributeValues(
      object,
      w.values({{"EntityIdentifier", bytes_from_hex(kEntityIdentifier)},
                {"EntityType", bytes_from_hex(kEntityType)},
                {"ForceIdentifier", bytes_from_hex("01")}}),
      data(bytes_from_hex("cafe")));
  std::uint64_t seen = w.observer.callbacks();
  while (w.observer.callbacks() == seen && sc_hla::monotonic_ns() - start < limit) {
    if (!w.observer.step()) return;
  }
  w.setup.deleteObjectInstance(object, data(bytes_from_hex("beef")));
  seen = w.observer.callbacks();
  while (w.observer.callbacks() == seen && sc_hla::monotonic_ns() - start < limit) {
    if (!w.observer.step()) return;
  }
}

// R12, SPEC:291: a still-active handle discovered again with another name keeps its token; the
// host's reducer, not the worker, judges the changed metadata (E_CAPTURE_SCHEMA, terminal).
void rediscover_changed(World& w) {
  w.discover(1, L"first-name");
  w.discover(1, L"second-name");
  w.end_batch();
}

// R14: SIGTERM arrives in the middle of a batch; the batch is finished (all its records are
// written), then the observer resigns, disconnects and exits 0 by itself.
void stop_mid_batch(World& w) {
  w.discover(1, L"stopping-object");
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}));
  ::kill(::getpid(), SIGTERM);
  while (!sc_hla::stop_requested()) sc_hla::pause_for(1000000);
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("02")}}));
  w.remove(1);
  w.end_batch();
}

// R10: a federation whose FOM has no Spatial at PhysicalEntity. The observer joins it (no module
// of its own), and resolving the four names fails: E_FOM_PROFILE (the federation is made by the
// setup federate from kReducedFom below instead of the five modules).
void missing_name(World&) {}

// The worker's parent rule itself (ParentWatch::changed), for a parent pid that is neither the
// recorded one nor 1: what an orphan of a subreaper sees on Linux, which macOS never shows.
void parent_rule(World& w) {
  std::string line = "{\"changed\":[";
  const int cases[][2] = {{4242, 4243}, {4242, 1}, {4242, 4242}, {1, 1}};
  for (std::size_t i = 0; i < 4; ++i) {
    if (i > 0) line += ",";
    line += sc_hla::ParentWatch::changed(cases[i][0], cases[i][1]) ? "true" : "false";
  }
  w.log.line(line + "],\"event\":\"parent-rule\"}");
}

// The decorator itself: a forbidden service, and an allowed one with arguments the observer
// never uses, each abort the process.
void decorator_forbidden(World& w) {
  rti1516e::AttributeHandleSet none;
  w.recorder.publishObjectClassAttributes(w.physical_entity, none);
}

void decorator_arguments(World& w) {
  w.recorder.resignFederationExecution(rti1516e::DELETE_OBJECTS);
}

// ---- what follows a terminal condition (R41: no record after a refused one) -----------------

// Three callbacks the observer accepts on their own: an empty reflection of object 1 numbered
// 9999 (tag 0000270f), a discovery of a new handle named "after", a removal of object 1 numbered
// 9999. 13 bytes and 3 frames: room any of the refusals below leaves. After a terminal condition
// in the same batch none of them may be captured: a record that merely fits after the refused
// one would leave a silent gap in the evidence.
void acceptable_after(World& w) {
  w.reflect(1, rti1516e::AttributeHandleValueMap(), big_endian(9999, 4));
  w.discover(9999, L"after");
  w.remove(1, big_endian(9999, 4));
}

void four_maximal_values(World& w, std::uint64_t number) {
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4096, 0x01)},
                         {"EntityType", repeated(4096, 0x02)},
                         {"ForceIdentifier", repeated(4096, 0x03)},
                         {"Spatial", repeated(4096, 0x04)}}),
            big_endian(number, 4));
}

// The queue refuses by bytes (the 1024th maximal reflection, as overflow-bytes), then three
// records that would fit the 12291 bytes left.
void after_overflow_bytes(World& w) {
  w.frames.wait_drained();
  w.discover(1, L"b");
  for (std::uint64_t i = 0; i < 1024; ++i) four_maximal_values(w, i);
  acceptable_after(w);
  w.end_batch();
}

// The queue refuses by frames while the reader does not read (as overflow-stalled), the batch
// of the refused reflection still open; the harness logs the refused number, waits until the
// test has read everything written so far (the queue has room again), and only then makes the
// three acceptable callbacks in that same batch.
void after_overflow_frames(World& w) {
  w.discover(1, L"stalled-object");
  w.end_batch();
  std::uint64_t number = 0;
  for (; number < 1000000; ++number) {
    w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(number, 4));
    if (w.observer.has_condition()) break;
    w.end_batch();
  }
  w.log.line("{\"event\":\"refused\",\"number\":" + std::to_string(number) + "}");
  w.frames.wait_drained();
  acceptable_after(w);
  w.end_batch();
}

// E_LIMIT for a value, a tag and an object name, each followed in its batch by the three.
void after_limit_value(World& w) {
  w.discover(1, L"limit-object");
  w.end_batch();
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4097, 0x5a)}}));
  acceptable_after(w);
  w.end_batch();
}

void after_limit_tag(World& w) {
  w.discover(1, L"limit-object");
  w.end_batch();
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), repeated(4097, 0x7e));
  acceptable_after(w);
  w.end_batch();
}

void after_limit_name(World& w) {
  w.discover(1, L"limit-object");
  w.end_batch();
  w.discover(2, std::wstring(1025, L'n'));
  acceptable_after(w);
  w.end_batch();
}

// ---- which code wins when one callback has two faults (CR-new-R7-06) ---------------------------

// The queue holding 4096 frames: the discover of object 1 and 4095 numbered reflections.
void fill_queue(World& w) {
  w.frames.wait_drained();
  w.discover(1, L"c");
  for (std::uint64_t i = 0; i < 4095; ++i) {
    w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(i, 4));
  }
}

// Reflect: five supplied attributes and a sent order outside the enumeration: the count first.
void precedence_count_order(World& w) {
  w.discover(1, L"precedence-object");
  w.reflect(1, w.values({{"EntityIdentifier", bytes_from_hex(kEntityIdentifier)},
                         {"EntityType", bytes_from_hex(kEntityType)},
                         {"Spatial", bytes_from_hex(kSpatialPadded)},
                         {"ForceIdentifier", bytes_from_hex("01")},
                         {"DamageState", bytes_from_hex("00000001")}}),
            std::string(), static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

// A 4097-byte value with a time whose implementation name is no Unicode: sizes before names.
void precedence_value_time_name(World& w) {
  w.discover(1, L"precedence-object");
  w.reflect_timed(1, w.values({{"EntityIdentifier", repeated(4097, 0x5a)}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(L"T" + std::wstring(1, static_cast<wchar_t>(0xD800)),
                           bytes_from_hex("0102")),
                  rti1516e::TIMESTAMP);
  w.end_batch();
}

// A transportation type that is no enumerator but inside the enumeration's range (Enums.h: RELIABLE
// 1 and BEST_EFFORT 2, so its values are 0..3): a value outside the range would be undefined
// behaviour in this test's own cast (review finding R7-r2-F1).
const rti1516e::TransportationType kNoTransport = static_cast<rti1516e::TransportationType>(3);

// A 4097-byte tag with a transportation type outside the enumeration: sizes before enumerations.
void precedence_tag_transport(World& w) {
  w.discover(1, L"precedence-object");
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), repeated(4097, 0x7e),
            rti1516e::RECEIVE, kNoTransport);
  w.end_batch();
}

// A 257-byte time whose implementation name is no Unicode: the time's size before its name.
void precedence_time_length_name(World& w) {
  w.discover(1, L"precedence-object");
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(L"T" + std::wstring(1, static_cast<wchar_t>(0xD800)),
                           repeated(257, 0x11)),
                  rti1516e::TIMESTAMP);
  w.end_batch();
}

// A received order outside the enumeration on a full queue: the enumerations before the queue.
void precedence_order_queue(World& w) {
  fill_queue(w);
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE, rti1516e::HLAfloat64Time(1.0),
                  static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

// Discover: a class other than PhysicalEntity under a 1025-byte name: the class first.
void precedence_class_name(World& w) {
  Direct(w.observer, w.recorder)
      ->discoverObjectInstance(w.object(1), w.ground_vehicle, std::wstring(1025, L'n'));
  w.end_batch();
}

// A 1025-byte object name on a full queue: the name's size before the queue.
void precedence_name_queue(World& w) {
  fill_queue(w);
  w.discover(2, std::wstring(1025, L'n'));
  w.end_batch();
}

// Remove: a 4097-byte tag with a received order outside the enumeration: the tag first.
void precedence_remove_tag_order(World& w) {
  w.discover(1, L"precedence-object");
  w.remove_timed(1, repeated(4097, 0x7e), rti1516e::HLAfloat64Time(1.0),
                 static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

// A removal with a received order outside the enumeration on a full queue.
void precedence_remove_order_queue(World& w) {
  fill_queue(w);
  w.remove_timed(1, std::string(), rti1516e::HLAfloat64Time(1.0),
                 static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

// 100000 tokens taken by reflections of handles nobody discovered (as tokens), the queue
// drained; then `last`.
void at_token_bound(World& w, const std::function<void(World&)>& last) {
  for (std::uint64_t number = 1; number <= 100000; ++number) {
    w.reflect(number, w.values({{"ForceIdentifier", bytes_from_hex("01")}}));
    if (number % 1000 == 0) {
      w.end_batch();
      w.frames.wait_drained();
    }
  }
  last(w);
  w.end_batch();
}

// A new handle (the 100001st token) with a received order outside the enumeration: the
// enumerations before the token budget.
void precedence_order_token(World& w) {
  at_token_bound(w, [](World& v) {
    v.reflect_timed(100001, v.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                    rti1516e::TIMESTAMP, rti1516e::RELIABLE, rti1516e::HLAfloat64Time(1.0),
                    static_cast<rti1516e::OrderType>(3));
  });
}

// A new handle on a full queue: the token budget before the queue. The queue is filled with
// 4096 reflections of handle 1, which holds token o1 already.
void precedence_token_queue(World& w) {
  at_token_bound(w, [](World& v) {
    for (std::uint64_t i = 0; i < 4096; ++i) {
      v.reflect(1, v.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(i, 4));
    }
    v.reflect(100001, v.values({{"ForceIdentifier", bytes_from_hex("01")}}));
  });
}

// The queue filled with 4096 reflections of handle 1 (token o1 already), as above.
void fill_with_o1(World& v) {
  for (std::uint64_t i = 0; i < 4096; ++i) {
    v.reflect(1, v.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(i, 4));
  }
}

// NAT-11's bound on the discover arm (review finding R7-r2-F2): a discovery of a new handle when
// 100000 tokens are spent is E_LIMIT; with the queue full as well, still E_LIMIT (the token
// budget before the queue, CR-new-R7-06).
void token_bound_discover(World& w) {
  at_token_bound(w, [](World& v) { v.discover(100001, L"one-too-many"); });
}

void token_bound_discover_queue(World& w) {
  at_token_bound(w, [](World& v) {
    fill_with_o1(v);
    v.discover(100001, L"one-too-many");
  });
}

// The remove arm: a removal of a new handle at the bound is E_LIMIT; a timed one whose received
// order is outside the enumeration is E_CAPTURE_SCHEMA (the enumeration before the token); with
// the queue full, E_LIMIT (the token before the queue).
void token_bound_remove(World& w) {
  at_token_bound(w, [](World& v) { v.remove(100001); });
}

void token_bound_remove_order(World& w) {
  at_token_bound(w, [](World& v) {
    v.remove_timed(100001, std::string(), rti1516e::HLAfloat64Time(1.0),
                   static_cast<rti1516e::OrderType>(3));
  });
}

void token_bound_remove_queue(World& w) {
  at_token_bound(w, [](World& v) {
    fill_with_o1(v);
    v.remove(100001);
  });
}

// ---- a naming fault and another condition in one batch (CR-new-R7-13) --------------------------

// The unknown attribute's name (129 bytes) is looked up after the evoke call, when the 4097-byte
// value of the next callback has already set E_LIMIT: the naming fault, earlier in callback
// order, is the condition reported; the discover before it is written, nothing after.
void naming_then_limit(World& w) {
  w.recorder.inject_name(w.attribute.at("DamageState"), std::wstring(129, L'N'));
  w.discover(1, L"named-object");
  w.reflect(1, w.values({{"DamageState", bytes_from_hex("01")}}));
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4097, 0x5a)}}));
  w.end_batch();
}

// The other order: E_LIMIT first; the reflection with the unknown attribute after it is never
// captured, so its name is never looked up.
void limit_then_naming(World& w) {
  w.recorder.inject_name(w.attribute.at("DamageState"), std::wstring(129, L'N'));
  w.discover(1, L"named-object");
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4097, 0x5a)}}));
  w.reflect(1, w.values({{"DamageState", bytes_from_hex("01")}}));
  w.end_batch();
}

// ---- refusals of metadata and logical times (CR-new-R7-07, CR-new-R7-08) -----------------------

void transport_invalid(World& w) {
  w.discover(1, L"ordered-object");
  w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
            rti1516e::RECEIVE, kNoTransport);
  w.end_batch();
}

void received_order_invalid(World& w) {
  w.discover(1, L"ordered-object");
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE, rti1516e::HLAfloat64Time(1.0),
                  static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

void remove_order_invalid(World& w) {
  w.discover(1, L"ordered-object");
  w.remove_timed(1, std::string(), rti1516e::HLAfloat64Time(1.0),
                 static_cast<rti1516e::OrderType>(3));
  w.end_batch();
}

void timed_with(World& w, TestTime::Fault fault) {
  w.discover(1, L"timed-object");
  w.end_batch();
  w.reflect_timed(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), std::string(),
                  rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  TestTime(L"Harness-Time", bytes_from_hex("0102"), fault), rti1516e::TIMESTAMP);
  w.end_batch();
}

// ---- the byte bound, both sides (16 MiB exactly) ------------------------------------------------

// 1 (the name "b") + 1023 * 16388 = 16764925 bytes; the next reflection has `last` bytes in its
// third value and a 4-byte tag: 4095 makes 12291, which fills 16 MiB exactly, and is followed by
// an empty reflection with a 1-byte tag (one byte more than the bound); 4096 makes 12292, one
// byte more than fits.
void overflow_bytes_edge(World& w, std::size_t last) {
  w.frames.wait_drained();
  w.discover(1, L"b");
  for (std::uint64_t i = 0; i < 1023; ++i) four_maximal_values(w, i);
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4096, 0x01)},
                         {"EntityType", repeated(4096, 0x02)},
                         {"ForceIdentifier", repeated(last, 0x03)}}),
            big_endian(1023, 4));
  w.reflect(1, rti1516e::AttributeHandleValueMap(), bytes_from_hex("ff"));
  w.end_batch();
}

// The same 16764925 bytes, then a timed reflection whose logical time counts too (review finding
// R7-r2-F3): 4096 + 4096 + `third` value bytes, a 4-byte tag and HLAfloat64Time(1.0), whose
// encoding is 8 bytes and whose implementation name "HLAfloat64Time" is 14: `third` 4073 makes
// 8192 + 4073 + 4 + 22 = 12291, exactly what is left (then the 1-byte empty reflection is one byte
// over); 4074 is one byte more than fits.
void overflow_bytes_time_edge(World& w, std::size_t third) {
  w.frames.wait_drained();
  w.discover(1, L"b");
  for (std::uint64_t i = 0; i < 1023; ++i) four_maximal_values(w, i);
  w.reflect_timed(1, w.values({{"EntityIdentifier", repeated(4096, 0x01)},
                               {"EntityType", repeated(4096, 0x02)},
                               {"ForceIdentifier", repeated(third, 0x03)}}),
                  big_endian(1023, 4), rti1516e::TIMESTAMP, rti1516e::RELIABLE,
                  rti1516e::HLAfloat64Time(1.0), rti1516e::TIMESTAMP);
  w.reflect(1, rti1516e::AttributeHandleValueMap(), bytes_from_hex("ff"));
  w.end_batch();
}

// The removal's tag and time count: after the 16764925 bytes, a reflection of 4096 + 4096 + 73
// value bytes and a 4-byte tag (8269) leaves 4022; a timed removal with a `tag`-byte tag and
// HLAfloat64Time(1.0) (22 bytes) then fills it exactly with a 4000-byte tag, and is one byte over
// with 4001.
void overflow_bytes_remove_edge(World& w, std::size_t tag) {
  w.frames.wait_drained();
  w.discover(1, L"b");
  for (std::uint64_t i = 0; i < 1023; ++i) four_maximal_values(w, i);
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4096, 0x01)},
                         {"EntityType", repeated(4096, 0x02)},
                         {"ForceIdentifier", repeated(73, 0x03)}}),
            big_endian(1023, 4));
  w.remove_timed(1, repeated(tag, 0x7e), rti1516e::HLAfloat64Time(1.0), rti1516e::TIMESTAMP);
  w.reflect(1, rti1516e::AttributeHandleValueMap(), bytes_from_hex("ff"));
  w.end_batch();
}

// ---- broken channels (NAT-09: EPIPE ends the worker) --------------------------------------------

// How many turns of the event loop a streaming scenario makes at most: far more than a test
// needs before it closes its end, and still an end for a worker that would not stop.
const std::uint64_t kStreamTurns = 20000;

// One numbered reflection per turn of the worker's own event loop (Observer::step). The test
// closes its end of stdout after a few frames; the writer's next write fails with EPIPE, the
// next turn ends the loop, and the observer resigns and disconnects.
void stream_frames(World& w) {
  w.discover(1, L"streaming-object");
  for (std::uint64_t number = 0; number < kStreamTurns; ++number) {
    w.reflect(1, w.values({{"ForceIdentifier", bytes_from_hex("01")}}), big_endian(number, 4));
    if (!w.observer.step()) return;
  }
}

// One new object per turn, so that each turn writes request_update and running on fd 3. The test
// closes its end of fd 3; the next stage record fails with EPIPE.
void stream_objects(World& w) {
  for (std::uint64_t number = 1; number <= kStreamTurns; ++number) {
    w.discover(number, L"streaming-object");
    if (!w.observer.step()) return;
  }
}

// ---- the decorator failing one of the observer's RTI calls (see faults()) ------------------------

// One turn of the worker's event loop: the evoke call.
void one_turn(World& w) { w.observer.step(); }

// A discovery, so that the batch ends with a request for the object's values.
void one_discovery(World& w) {
  w.discover(1, L"requested-object");
  w.end_batch();
}

// A condition (E_LIMIT) before the close whose resign or disconnect then fails.
void condition_then_close(World& w) {
  w.discover(1, L"limit-object");
  w.reflect(1, w.values({{"EntityIdentifier", repeated(4097, 0x5a)}}));
  w.end_batch();
}

const std::map<std::string, std::function<void(World&)> >& scenarios() {
  static const std::map<std::string, std::function<void(World&)> > table = {
      {"idle", idle},
      {"bytes", bytes},
      {"limit-value", limit_value},
      {"limit-tag-reflect", limit_tag_reflect},
      {"limit-tag-remove", limit_tag_remove},
      {"limit-time", limit_time},
      {"limit-name", limit_name},
      {"limit-attributes", limit_attributes},
      {"unsubscribed", unsubscribed},
      {"retract", retract},
      {"retraction-request", retraction_request},
      {"empty", empty},
      {"reuse", reuse},
      {"requests", requests},
      {"name-surrogate", name_surrogate},
      {"name-beyond", name_beyond},
      {"name-text", name_text},
      {"attribute-name-refused", attribute_name_refused},
      {"attribute-name-long", attribute_name_long},
      {"attribute-name-128", attribute_name_128},
      {"attribute-name-invalid", attribute_name_invalid},
      {"attribute-name-collision", attribute_name_collision},
      {"time-name-long", time_name_long},
      {"time-name-invalid", time_name_invalid},
      {"class-other", class_other},
      {"order-invalid", order_invalid},
      {"connection-lost", connection_lost},
      {"overflow-count", overflow_count},
      {"overflow-bytes", overflow_bytes},
      {"overflow-stalled", overflow_stalled},
      {"tokens", tokens},
      {"live", live},
      {"rediscover-changed", rediscover_changed},
      {"stop-mid-batch", stop_mid_batch},
      {"missing-name", missing_name},
      {"parent-rule", parent_rule},
      {"decorator-forbidden", decorator_forbidden},
      {"decorator-arguments", decorator_arguments},
      {"after-overflow-bytes", after_overflow_bytes},
      {"after-overflow-frames", after_overflow_frames},
      {"after-limit-value", after_limit_value},
      {"after-limit-tag", after_limit_tag},
      {"after-limit-name", after_limit_name},
      {"precedence-count-order", precedence_count_order},
      {"precedence-value-time-name", precedence_value_time_name},
      {"precedence-tag-transport", precedence_tag_transport},
      {"precedence-time-length-name", precedence_time_length_name},
      {"precedence-order-queue", precedence_order_queue},
      {"precedence-class-name", precedence_class_name},
      {"precedence-name-queue", precedence_name_queue},
      {"precedence-remove-tag-order", precedence_remove_tag_order},
      {"precedence-remove-order-queue", precedence_remove_order_queue},
      {"precedence-order-token", precedence_order_token},
      {"precedence-token-queue", precedence_token_queue},
      {"naming-then-limit", naming_then_limit},
      {"limit-then-naming", limit_then_naming},
      {"transport-invalid", transport_invalid},
      {"received-order-invalid", received_order_invalid},
      {"remove-order-invalid", remove_order_invalid},
      {"time-encode-refused", [](World& w) { timed_with(w, TestTime::Fault::kEncodeRefuses); }},
      {"time-encode-short", [](World& w) { timed_with(w, TestTime::Fault::kEncodeShort); }},
      {"callback-no-memory", [](World& w) { timed_with(w, TestTime::Fault::kLengthNoMemory); }},
      {"callback-other-exception",
       [](World& w) { timed_with(w, TestTime::Fault::kLengthOther); }},
      {"overflow-bytes-exact", [](World& w) { overflow_bytes_edge(w, 4095); }},
      {"overflow-bytes-over", [](World& w) { overflow_bytes_edge(w, 4096); }},
      {"overflow-bytes-time-exact", [](World& w) { overflow_bytes_time_edge(w, 4073); }},
      {"overflow-bytes-time-over", [](World& w) { overflow_bytes_time_edge(w, 4074); }},
      {"overflow-bytes-remove-exact", [](World& w) { overflow_bytes_remove_edge(w, 4000); }},
      {"overflow-bytes-remove-over", [](World& w) { overflow_bytes_remove_edge(w, 4001); }},
      {"token-bound-discover", token_bound_discover},
      {"token-bound-discover-queue", token_bound_discover_queue},
      {"token-bound-remove", token_bound_remove},
      {"token-bound-remove-order", token_bound_remove_order},
      {"token-bound-remove-queue", token_bound_remove_queue},
      {"fault-create", idle},
      {"stream-frames", stream_frames},
      {"stream-objects", stream_objects},
      {"name-in-use", idle},
      {"fault-connect-stop", idle},
      {"fault-join-stop", idle},
      {"fault-join-time-factory", idle},
      {"fault-join-inconsistent-fdd", idle},
      {"fault-join-error-reading-fdd", idle},
      {"fault-join-could-not-open-fdd", idle},
      {"fault-join-other", idle},
      {"fault-class-name", idle},
      {"fault-attribute-other", idle},
      {"fault-subscribe-class", idle},
      {"fault-subscribe-attribute", idle},
      {"fault-subscribe-other", idle},
      {"fault-evoke", one_turn},
      {"fault-request-attribute", one_discovery},
      {"fault-request-other", one_discovery},
      {"fault-resign-after-stop", idle},
      {"fault-disconnect-after-stop", idle},
      {"fault-resign-after-condition", condition_then_close},
      {"fault-disconnect-after-condition", condition_then_close},
      {"real-rti", idle},
  };
  return table;
}

// The scenarios whose decorator fails one call, planned before the observer opens: the call, and
// the exception it throws instead of answering (or SIGTERM, a stop while the call blocks).
const std::map<std::string, std::pair<std::string, std::string> >& faults() {
  static const std::map<std::string, std::pair<std::string, std::string> > table = {
      {"fault-connect-stop", {"connect", "SIGTERM"}},
      {"fault-join-stop", {"joinFederationExecution", "SIGTERM"}},
      {"fault-join-time-factory",
       {"joinFederationExecution", "CouldNotCreateLogicalTimeFactory"}},
      {"fault-join-inconsistent-fdd", {"joinFederationExecution", "InconsistentFDD"}},
      {"fault-join-error-reading-fdd", {"joinFederationExecution", "ErrorReadingFDD"}},
      {"fault-join-could-not-open-fdd", {"joinFederationExecution", "CouldNotOpenFDD"}},
      {"fault-join-other", {"joinFederationExecution", "RTIinternalError"}},
      {"fault-class-name", {"getObjectClassHandle", "NameNotFound"}},
      {"fault-attribute-other", {"getAttributeHandle", "InvalidObjectClassHandle"}},
      {"fault-subscribe-class", {"subscribeObjectClassAttributes", "ObjectClassNotDefined"}},
      {"fault-subscribe-attribute", {"subscribeObjectClassAttributes", "AttributeNotDefined"}},
      {"fault-subscribe-other", {"subscribeObjectClassAttributes", "RTIinternalError"}},
      {"fault-evoke", {"evokeMultipleCallbacks", "RTIinternalError"}},
      {"fault-request-attribute", {"requestAttributeValueUpdate", "AttributeNotDefined"}},
      {"fault-request-other", {"requestAttributeValueUpdate", "RTIinternalError"}},
      {"fault-resign-after-stop", {"resignFederationExecution", "RTIinternalError"}},
      {"fault-disconnect-after-stop", {"disconnect", "RTIinternalError"}},
      {"fault-resign-after-condition", {"resignFederationExecution", "RTIinternalError"}},
      {"fault-disconnect-after-condition", {"disconnect", "RTIinternalError"}},
      {"fault-create", {"create", "RTIinternalError"}},
  };
  return table;
}

int claim_attempt(const std::string& log) {
  for (int number = 1;; ++number) {
    const std::string path = log + ".attempt-" + std::to_string(number);
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd >= 0) {
      ::close(fd);
      return number;
    }
  }
}

int fail_harness(const std::string& what) {
  sc_hla::write_all(2, "sc-hla-harness: " + what + "\n");
  return kExitHarness;
}

}  // namespace

int main(int argc, char** argv) {
  sc_hla::clear_openrti_debug_variables();
  std::vector<std::string> tokens(argv + 1, argv + argc);
  HarnessOptions harness;
  if (!parse_harness(&tokens, &harness)) return fail_harness("usage: see harness.cpp");
  const auto scenario = scenarios().find(harness.scenario);
  if (scenario == scenarios().end()) return fail_harness("unknown scenario");

  // From here on, exactly the worker's own start (worker/main.cpp).
  sc_hla::Options options;
  switch (sc_hla::parse_arguments(tokens, &options)) {
    case sc_hla::Invocation::kVersion:
      return sc_hla::write_all(1, sc_hla::kVersionLine) ? sc_hla::kExitStopped
                                                         : sc_hla::kExitFailure;
    case sc_hla::Invocation::kUsage:
      return sc_hla::kExitUsage;
    case sc_hla::Invocation::kRun:
      break;
  }
  if (!sc_hla::status_channel_present()) return sc_hla::kExitStatusChannel;
  sc_hla::install_signal_handlers();

  const int log_fd = ::open(harness.log.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
  if (log_fd < 0) return fail_harness("cannot open the log");
  CallLog log(log_fd);
  const int attempt = claim_attempt(harness.log);
  log.line("{\"attempt\":" + std::to_string(attempt) + ",\"event\":\"start\",\"pid\":" +
           std::to_string(::getpid()) + "}");

  // The setup federate: the federation, from the five modules, in this process.
  SetupAmbassador setup_ambassador(log);
  rti1516e::RTIambassadorFactory factory;
  RTI_UNIQUE_PTR<rti1516e::RTIambassador> setup = factory.createRTIambassador();
  const std::wstring federation = sc_hla::widen_ascii(options.federation_name);
  rti1516e::ObjectClassHandle physical_entity;
  rti1516e::ObjectClassHandle ground_vehicle;
  std::map<std::string, rti1516e::AttributeHandle> attribute;
  rti1516e::FederateHandle setup_federate;
  const bool reduced = harness.scenario == "missing-name";
  const bool real = harness.scenario == "real-rti";
  try {
    if (real) throw RealRti();
    setup->connect(setup_ambassador, rti1516e::HLA_EVOKED, L"thread://");
    std::vector<std::wstring> modules;
    if (reduced) {
      modules.push_back(sc_hla::widen_ascii(kReducedFom));
    } else {
      const char* const names[] = {"RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml",
                                   "RPR-Base_v2.0.xml", "RPR-Physical_v2.0.xml",
                                   "RPR-Switches_v2.0.xml"};
      for (const char* name : names) {
        modules.push_back(sc_hla::widen_ascii(harness.fom_dir + "/" + name));
      }
    }
    setup->createFederationExecution(federation, modules, L"HLAfloat64Time");
    // name-in-use: the setup federate takes the observer's own federate name first.
    const std::wstring setup_name = harness.scenario == "name-in-use"
                                        ? sc_hla::widen_ascii(options.federate_name)
                                        : std::wstring(L"sc-hla-harness-setup");
    setup_federate =
        setup->joinFederationExecution(setup_name, L"SynapseCommandHarness", federation);
    physical_entity = setup->getObjectClassHandle(sc_hla::kPhysicalEntityClassWide);
    if (!reduced) {
      ground_vehicle = setup->getObjectClassHandle(
          L"HLAobjectRoot.BaseEntity.PhysicalEntity.Platform.GroundVehicle");
      for (const char* name : {"EntityIdentifier", "EntityType", "Spatial", "ForceIdentifier",
                               "DamageState"}) {
        attribute[name] = setup->getAttributeHandle(physical_entity, wide(name));
      }
    }
  } catch (const RealRti&) {
    // No setup federate: the federation is another process's, on the configured endpoint.
  } catch (const rti1516e::Exception&) {
    return fail_harness("the setup federate could not create and join the federation");
  }

  sc_hla::ParentWatch parent;
  sc_hla::StatusChannel status(3);
  sc_hla::FrameQueue frames(1);
  frames.start();
  int exit_status = sc_hla::kExitFailure;
  {
    sc_hla::Observer observer(options, status, frames, parent);
    RecordingSource source(log);
    const auto fault = faults().find(harness.scenario);
    if (fault != faults().end()) source.plan_fault(fault->second.first, fault->second.second);
    const std::wstring designator =
        real ? sc_hla::widen_ascii(options.endpoint) : std::wstring(L"thread://");
    if (!observer.open(source, designator)) {
      exit_status = observer.close();
    } else if (real) {
      log.line("{\"event\":\"ready\"}");
      observer.event_loop();
      exit_status = observer.close();
    } else {
      frames.wait_drained();
      World w{observer, frames, *setup, setup_ambassador, *source.made(), log, attempt,
              physical_entity, ground_vehicle, attribute, setup_federate};
      scenario->second(w);
      if (!observer.has_condition()) {
        log.line("{\"event\":\"ready\"}");
        if (harness.stop_when_ready) ::kill(::getpid(), SIGTERM);
        observer.event_loop();
      }
      exit_status = observer.close();
    }
  }
  try {
    if (!real) {
      setup->resignFederationExecution(rti1516e::DELETE_OBJECTS);
      setup->destroyFederationExecution(federation);
      setup->disconnect();
    }
  } catch (const rti1516e::Exception&) {
    // The harness's own federation in this process; nothing outside it depends on its end.
  }
  log.line("{\"event\":\"exit\",\"status\":" + std::to_string(exit_status) + "}");
  return exit_status;
}
