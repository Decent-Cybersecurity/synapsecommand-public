#include "observer.h"

#include <RTI/LogicalTime.h>
#include <RTI/RTIambassadorFactory.h>

#include <new>
#include <utility>

#include "constants.h"
#include "text.h"

namespace sc_hla {

namespace {

// OPS-30: the codes a worker reports.
const char kRtiConnect[] = "E_RTI_CONNECT";
const char kFomProfile[] = "E_FOM_PROFILE";
const char kFederateName[] = "E_FEDERATE_NAME";
const char kQueueOverflow[] = "E_QUEUE_OVERFLOW";
const char kLimit[] = "E_LIMIT";
const char kCaptureSchema[] = "E_CAPTURE_SCHEMA";
const char kRetractionUnsupported[] = "E_RETRACTION_UNSUPPORTED";

// Fixed messages (R37): no RTI text and no input is ever quoted, so a message is always
// ASCII, one line and far below 1024 bytes.
const char kCreateFailed[] = "the RTI ambassador could not be created";
const char kConnectFailed[] =
    "connect failed: the RTI refused or could not establish the connection";
const char kNoFederation[] = "join failed: the federation execution does not exist";
const char kNameInUse[] = "join failed: the federate name is already in use in the federation";
const char kTimeFactory[] =
    "join failed: the federation's logical time implementation is not available";
const char kFomUnreadable[] = "join failed: the RTI could not read the federation's FOM";
const char kJoinFailed[] = "join failed: the RTI refused the join";
const char kNameNotFound[] =
    "resolve failed: PhysicalEntity or one of its four attributes is not in the federation's FOM";
const char kNotDefined[] =
    "resolve failed: the RTI does not define the class or attributes to subscribe";
const char kResolveFailed[] = "resolve failed: the RTI refused a name lookup or the subscription";
const char kEvokeFailed[] = "the RTI failed while delivering callbacks";
const char kConnectionLost[] = "the RTI reported that the connection was lost";
const char kRetractionRequested[] =
    "the RTI requested a retraction, which this profile does not support";
const char kOtherClass[] = "an object was discovered at a class other than PhysicalEntity";
const char kBadObjectName[] = "an object name is not a string of Unicode scalar values";
const char kLongObjectName[] = "an object name is longer than 1024 UTF-8 bytes";
const char kTooManyTokens[] = "the worker would allocate more than 100000 object tokens";
const char kTooManyAttributes[] = "a reflection supplies more than 4 attributes";
const char kLongValue[] = "an attribute value is longer than 4096 bytes";
const char kLongTag[] = "a user-supplied tag is longer than 4096 bytes";
const char kLongTime[] = "an encoded logical time is longer than 256 bytes";
const char kBadTimeName[] =
    "a logical time implementation name is not a string of Unicode scalar values";
const char kLongTimeName[] = "a logical time implementation name is longer than 128 UTF-8 bytes";
const char kBadTime[] = "a logical time could not be encoded";
const char kBadMetadata[] =
    "a callback supplied an order or transportation type outside the HLA enumerations";
const char kQueueFull[] = "the callback queue is full (4096 frames or 16 MiB)";
const char kNameLookupFailed[] = "the RTI could not name an attribute supplied in a reflection";
const char kBadAttributeName[] = "an attribute name is not a string of Unicode scalar values";
const char kLongAttributeName[] = "an attribute name is longer than 128 UTF-8 bytes";
const char kDuplicateAttribute[] = "two attributes supplied in one reflection have the same name";
const char kRequestUndefined[] = "the RTI does not define the attributes requested for an object";
const char kRequestFailed[] = "the RTI refused a request for attribute values";
const char kResignFailed[] = "resign failed: the RTI refused to resign the federate";
const char kDisconnectFailed[] = "disconnect failed: the RTI refused to disconnect";
const char kNoMemory[] = "the worker could not allocate memory for a callback";
const char kUncapturable[] = "a callback could not be captured";

// The four attributes the observer resolves at PhysicalEntity (R10).
const wchar_t* const kAttributeNames[] = {L"EntityIdentifier", L"EntityType", L"Spatial",
                                          L"ForceIdentifier"};

bool valid_order(rti1516e::OrderType order) {
  return order == rti1516e::RECEIVE || order == rti1516e::TIMESTAMP;
}

bool valid_transport(rti1516e::TransportationType transport) {
  return transport == rti1516e::RELIABLE || transport == rti1516e::BEST_EFFORT;
}

Order order_of(rti1516e::OrderType order) {
  return order == rti1516e::RECEIVE ? Order::kReceive : Order::kTimestamp;
}

Transport transport_of(rti1516e::TransportationType transport) {
  return transport == rti1516e::RELIABLE ? Transport::kReliable : Transport::kBestEffort;
}

// VariableLengthData's bytes, copied (R12). data() of an empty value may be null.
std::string copy_bytes(rti1516e::VariableLengthData const& data) {
  if (data.size() == 0) return std::string();
  return std::string(static_cast<const char*>(data.data()), data.size());
}

}  // namespace

AmbassadorSource::~AmbassadorSource() {}

RTI_UNIQUE_PTR<rti1516e::RTIambassador> FactorySource::create() {
  rti1516e::RTIambassadorFactory factory;
  return factory.createRTIambassador();
}

Observer::Observer(const Options& options, StatusChannel& status, FrameQueue& frames,
                   const ParentWatch& parent)
    : options_(options), status_(status), frames_(frames), parent_(parent) {}

Observer::~Observer() RTI_NOEXCEPT {}

int Observer::run(AmbassadorSource& source, const std::wstring& local_settings_designator) {
  if (open(source, local_settings_designator)) event_loop();
  return close();
}

// --- the lifecycle (R10, R14, NAT-15) ----------------------------------------------------------

bool Observer::stage(const char* name) {
  if (!status_.stage(name)) lost_ = true;
  return !lost_;
}

bool Observer::open(AmbassadorSource& source, const std::wstring& local_settings_designator) {
  try {
    rti_ = source.create();
  } catch (const rti1516e::Exception&) {
    fail(kRtiConnect, kCreateFailed);
    report();
    return false;
  }
  if (!stage("connect")) return false;
  try {
    // Only HLA_EVOKED: callbacks arrive inside evokeMultipleCallbacks, on this thread.
    rti_->connect(*this, rti1516e::HLA_EVOKED, local_settings_designator);
    connected_ = true;
  } catch (const rti1516e::Exception&) {
    fail(kRtiConnect, kConnectFailed);
  }
  if (!stage("running")) return false;
  if (has_condition_) {
    report();
    return false;
  }
  if (stop_requested()) return false;

  if (!stage("join")) return false;
  try {
    // R10: the configured names, the fixed federate type, and NO additional FOM module: the
    // observer never brings its own FOM into a federation it joins.
    rti_->joinFederationExecution(widen_ascii(options_.federate_name), widen_ascii(kFederateType),
                                  widen_ascii(options_.federation_name),
                                  std::vector<std::wstring>());
    joined_ = true;
  } catch (const rti1516e::FederateNameAlreadyInUse&) {
    fail(kFederateName, kNameInUse);
  } catch (const rti1516e::FederationExecutionDoesNotExist&) {
    fail(kRtiConnect, kNoFederation);
  } catch (const rti1516e::CouldNotCreateLogicalTimeFactory&) {
    fail(kFomProfile, kTimeFactory);
  } catch (const rti1516e::InconsistentFDD&) {
    fail(kFomProfile, kFomUnreadable);
  } catch (const rti1516e::ErrorReadingFDD&) {
    fail(kFomProfile, kFomUnreadable);
  } catch (const rti1516e::CouldNotOpenFDD&) {
    fail(kFomProfile, kFomUnreadable);
  } catch (const rti1516e::Exception&) {
    fail(kRtiConnect, kJoinFailed);
  }
  if (!stage("running")) return false;
  if (has_condition_) {
    report();
    return false;
  }
  // SPEC:275: the generation starts with the join, before anything can be evoked.
  enqueue_generation_start();
  if (has_condition_) {
    report();
    return false;
  }
  if (stop_requested()) return false;

  if (!stage("resolve")) return false;
  try {
    physical_entity_ = rti_->getObjectClassHandle(kPhysicalEntityClassWide);
    for (const wchar_t* name : kAttributeNames) {
      const rti1516e::AttributeHandle handle = rti_->getAttributeHandle(physical_entity_, name);
      subscribed_[handle] = to_utf8(name);
      four_.insert(handle);
    }
    // Active, at the common ancestor, without regions (R10, R16).
    rti_->subscribeObjectClassAttributes(physical_entity_, four_, true);
  } catch (const rti1516e::NameNotFound&) {
    fail(kFomProfile, kNameNotFound);
  } catch (const rti1516e::ObjectClassNotDefined&) {
    fail(kFomProfile, kNotDefined);
  } catch (const rti1516e::AttributeNotDefined&) {
    fail(kFomProfile, kNotDefined);
  } catch (const rti1516e::Exception&) {
    fail(kRtiConnect, kResolveFailed);
  }
  if (!stage("running")) return false;
  if (has_condition_) {
    report();
    return false;
  }
  return true;
}

void Observer::enqueue_generation_start() {
  Record record;
  record.kind = Record::Kind::kGenerationStart;
  record.monotonic_ns = monotonic_ns();
  record.text = options_.federation_name;
  record.queue_bytes = record.text.size();
  if (!frames_.reserve(record.queue_bytes)) {
    fail(kQueueOverflow, kQueueFull);
    return;
  }
  std::vector<Record> one;
  one.push_back(std::move(record));
  frames_.hand_over(&one);
}

bool Observer::step() {
  if (has_condition_ || lost_ || stop_requested()) return false;
  if (frames_.broken() || status_.broken()) {
    lost_ = true;
    return false;
  }
  const std::uint64_t before = callbacks_;
  try {
    rti_->evokeMultipleCallbacks(kEvokeMinimumSeconds, kEvokeMaximumSeconds);
  } catch (const rti1516e::Exception&) {
    fail(kRtiConnect, kEvokeFailed);
  }
  end_batch();
  if (callbacks_ == before && !has_condition_) {
    // NAT-05: nothing was dispatched and end_batch() left no request pending.
    pause_for(kIdlePauseNanoseconds);
    if (parent_.gone()) {
      orphaned_ = true;
      return false;
    }
  }
  return true;
}

void Observer::event_loop() {
  while (step()) {
  }
}

int Observer::close() {
  if (has_condition_ && !reported_) report();
  // R14: resign with NO_ACTION (the observer owns nothing) and disconnect. A failure here after
  // an orderly stop is the session's condition, reported right after the running of its stage
  // like any other (CR-new-R7-11); after an earlier condition it changes nothing.
  if (joined_) {
    stage("resign");
    try {
      rti_->resignFederationExecution(rti1516e::NO_ACTION);
      joined_ = false;
    } catch (const rti1516e::Exception&) {
      if (!has_condition_) fail(kRtiConnect, kResignFailed);
    }
    stage("running");
    if (has_condition_ && !reported_) report();
  }
  if (connected_) {
    stage("disconnect");
    try {
      rti_->disconnect();
      connected_ = false;
    } catch (const rti1516e::Exception&) {
      if (!has_condition_) fail(kRtiConnect, kDisconnectFailed);
    }
    stage("running");
    if (has_condition_ && !reported_) report();
  }
  // Every frame accepted before the end reaches the pipe before the process exits, or the
  // channel has broken and nobody can read it.
  frames_.wait_drained();
  frames_.finish();
  if (has_condition_) return kExitFailure;
  if (orphaned_) return kExitParentGone;
  if (lost_ || frames_.broken() || status_.broken()) return kExitChannelLost;
  return kExitStopped;
}

void Observer::fail(const char* code, const char* message) {
  if (has_condition_) return;
  has_condition_ = true;
  condition_.code = code;
  condition_.message = message;
  condition_ns_ = monotonic_ns();
}

void Observer::report() {
  reported_ = true;
  // NAT-08: the same code as a diagnostic frame when the queue can take it. Never after an
  // overflow: the queue has just refused a record, and the status channel carries the failure
  // the queue cannot (SPEC:277).
  if (condition_.code != kQueueOverflow && frames_.reserve(condition_.message.size())) {
    Record record;
    record.kind = Record::Kind::kDiagnostic;
    record.monotonic_ns = condition_ns_;
    record.code = condition_.code;
    record.text = condition_.message;
    record.queue_bytes = condition_.message.size();
    std::vector<Record> one;
    one.push_back(std::move(record));
    frames_.hand_over(&one);
  }
  if (!status_.failure(condition_.code, condition_.message)) lost_ = true;
}

// --- the end of one evoke call (NAT-06, R12, NAV-04) --------------------------------------------

void Observer::end_batch() {
  std::size_t keep = batch_.size();
  for (std::size_t i = 0; i < batch_.size(); ++i) {
    Record& record = batch_[i];
    if (record.kind != Record::Kind::kReflect) continue;
    std::string fault;
    for (CapturedAttribute& attribute : record.attributes) {
      if (!attribute.named && !name_attribute(&attribute, &fault)) break;
    }
    if (lost_) {
      keep = i;
      break;
    }
    if (fault.empty() && !sort_attributes(&record.attributes)) fault = kDuplicateAttribute;
    if (!fault.empty()) {
      // This record precedes any condition a later callback raised, so its fault is the first
      // in callback order and the one reported.
      has_condition_ = false;
      fail(kCaptureSchema, fault.c_str());
      keep = i;
      break;
    }
  }
  for (std::size_t i = keep; i < batch_.size(); ++i) frames_.release(batch_[i].queue_bytes);
  batch_.erase(batch_.begin() + static_cast<std::ptrdiff_t>(keep), batch_.end());
  frames_.hand_over(&batch_);
  if (has_condition_ || lost_) {
    requests_.clear();
  } else {
    request_updates();
  }
  if (has_condition_ && !reported_) report();
}

bool Observer::name_attribute(CapturedAttribute* attribute, std::string* fault) {
  std::map<rti1516e::AttributeHandle, std::string>::const_iterator known =
      named_.find(attribute->handle);
  if (known == named_.end()) {
    // NAT-15: these lookups belong to the request_update stage.
    if (!stage("request_update")) return false;
    std::wstring name;
    bool looked_up = true;
    try {
      name = rti_->getAttributeName(physical_entity_, attribute->handle);
    } catch (const rti1516e::Exception&) {
      looked_up = false;
    }
    if (!stage("running")) return false;
    std::size_t bytes = 0;
    if (!looked_up) {
      *fault = kNameLookupFailed;
      return false;
    }
    if (!utf8_length(name, &bytes)) {
      *fault = kBadAttributeName;
      return false;
    }
    if (bytes > kMaxAttributeNameBytes) {
      *fault = kLongAttributeName;
      return false;
    }
    known = named_.insert(std::make_pair(attribute->handle, to_utf8(name))).first;
  }
  attribute->name = known->second;
  attribute->named = true;
  return true;
}

void Observer::request_updates() {
  for (const rti1516e::ObjectInstanceHandle& object : requests_) {
    if (!stage("request_update")) break;
    try {
      // R12: the same four attributes, an empty tag, after the callbacks returned.
      rti_->requestAttributeValueUpdate(object, four_, rti1516e::VariableLengthData());
    } catch (const rti1516e::ObjectInstanceNotKnown&) {
      // NAV-04: the object was removed in the same batch; its removal is already captured.
    } catch (const rti1516e::AttributeNotDefined&) {
      fail(kFomProfile, kRequestUndefined);
    } catch (const rti1516e::Exception&) {
      fail(kRtiConnect, kRequestFailed);
    }
    if (!stage("running") || has_condition_) break;
  }
  requests_.clear();
}

// --- callbacks ---------------------------------------------------------------------------------

template <typename Body>
void Observer::guarded(Body body) {
  ++callbacks_;
  // After a terminal condition nothing more is captured: the session ends with that condition.
  if (has_condition_ || lost_) return;
  // Nothing may escape a callback (OpenRTI's wrappers are declared not to throw, so an escape
  // would end the process unreported). An exception here is reported as the terminal condition
  // it causes, and the observer stops.
  try {
    body();
  } catch (const std::bad_alloc&) {
    fail(kLimit, kNoMemory);
  } catch (...) {
    fail(kCaptureSchema, kUncapturable);
  }
}

std::string Observer::allocate_token() {
  allocated_ += 1;
  return "o" + std::to_string(allocated_);
}

bool Observer::reserve(const Record& record) {
  if (frames_.reserve(record.queue_bytes)) return true;
  fail(kQueueOverflow, kQueueFull);
  return false;
}

void Observer::append(Record* record) {
  try {
    batch_.push_back(std::move(*record));
  } catch (...) {
    frames_.release(record->queue_bytes);
    throw;
  }
}

void Observer::connectionLost(std::wstring const&) RTI_THROW((rti1516e::FederateInternalError)) {
  // R12: a terminal flag and its reason. The RTI's description is not kept: it is RTI text.
  guarded([this] { fail(kRtiConnect, kConnectionLost); });
}

void Observer::requestRetraction(rti1516e::MessageRetractionHandle)
    RTI_THROW((rti1516e::FederateInternalError)) {
  // R13, SPEC:281: no object mapping in this profile; the generation ends with this code.
  guarded([this] { fail(kRetractionUnsupported, kRetractionRequested); });
}

void Observer::discoverObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                                      rti1516e::ObjectClassHandle theObjectClass,
                                      std::wstring const& theObjectInstanceName)
    RTI_THROW((rti1516e::FederateInternalError)) {
  const std::uint64_t now = monotonic_ns();
  guarded([&] { on_discover(theObject, theObjectClass, theObjectInstanceName, now); });
}

void Observer::discoverObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                                      rti1516e::ObjectClassHandle theObjectClass,
                                      std::wstring const& theObjectInstanceName,
                                      rti1516e::FederateHandle)
    RTI_THROW((rti1516e::FederateInternalError)) {
  // The producing federate is not captured (R16).
  const std::uint64_t now = monotonic_ns();
  guarded([&] { on_discover(theObject, theObjectClass, theObjectInstanceName, now); });
}

void Observer::reflectAttributeValues(rti1516e::ObjectInstanceHandle theObject,
                                      rti1516e::AttributeHandleValueMap const& theAttributeValues,
                                      rti1516e::VariableLengthData const& theUserSuppliedTag,
                                      rti1516e::OrderType sentOrder,
                                      rti1516e::TransportationType theType,
                                      rti1516e::SupplementalReflectInfo)
    RTI_THROW((rti1516e::FederateInternalError)) {
  // R13: the overload without a received order is RECEIVE.
  const std::uint64_t now = monotonic_ns();
  guarded([&] {
    on_reflect(theObject, theAttributeValues, theUserSuppliedTag, sentOrder, theType, nullptr,
               rti1516e::RECEIVE, false, now);
  });
}

void Observer::reflectAttributeValues(rti1516e::ObjectInstanceHandle theObject,
                                      rti1516e::AttributeHandleValueMap const& theAttributeValues,
                                      rti1516e::VariableLengthData const& theUserSuppliedTag,
                                      rti1516e::OrderType sentOrder,
                                      rti1516e::TransportationType theType,
                                      rti1516e::LogicalTime const& theTime,
                                      rti1516e::OrderType receivedOrder,
                                      rti1516e::SupplementalReflectInfo)
    RTI_THROW((rti1516e::FederateInternalError)) {
  const std::uint64_t now = monotonic_ns();
  guarded([&] {
    on_reflect(theObject, theAttributeValues, theUserSuppliedTag, sentOrder, theType, &theTime,
               receivedOrder, false, now);
  });
}

void Observer::reflectAttributeValues(rti1516e::ObjectInstanceHandle theObject,
                                      rti1516e::AttributeHandleValueMap const& theAttributeValues,
                                      rti1516e::VariableLengthData const& theUserSuppliedTag,
                                      rti1516e::OrderType sentOrder,
                                      rti1516e::TransportationType theType,
                                      rti1516e::LogicalTime const& theTime,
                                      rti1516e::OrderType receivedOrder,
                                      rti1516e::MessageRetractionHandle,
                                      rti1516e::SupplementalReflectInfo)
    RTI_THROW((rti1516e::FederateInternalError)) {
  // R13: a retractable update is captured as such; the reducer quarantines the object.
  const std::uint64_t now = monotonic_ns();
  guarded([&] {
    on_reflect(theObject, theAttributeValues, theUserSuppliedTag, sentOrder, theType, &theTime,
               receivedOrder, true, now);
  });
}

void Observer::removeObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                                    rti1516e::VariableLengthData const& theUserSuppliedTag,
                                    rti1516e::OrderType, rti1516e::SupplementalRemoveInfo)
    RTI_THROW((rti1516e::FederateInternalError)) {
  // NAT-17: the sent order is not kept; the received order of this overload is RECEIVE.
  const std::uint64_t now = monotonic_ns();
  guarded([&] {
    on_remove(theObject, theUserSuppliedTag, nullptr, rti1516e::RECEIVE, false, now);
  });
}

void Observer::removeObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                                    rti1516e::VariableLengthData const& theUserSuppliedTag,
                                    rti1516e::OrderType, rti1516e::LogicalTime const& theTime,
                                    rti1516e::OrderType receivedOrder,
                                    rti1516e::SupplementalRemoveInfo)
    RTI_THROW((rti1516e::FederateInternalError)) {
  const std::uint64_t now = monotonic_ns();
  guarded([&] {
    on_remove(theObject, theUserSuppliedTag, &theTime, receivedOrder, false, now);
  });
}

void Observer::removeObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                                    rti1516e::VariableLengthData const& theUserSuppliedTag,
                                    rti1516e::OrderType, rti1516e::LogicalTime const& theTime,
                                    rti1516e::OrderType receivedOrder,
                                    rti1516e::MessageRetractionHandle,
                                    rti1516e::SupplementalRemoveInfo)
    RTI_THROW((rti1516e::FederateInternalError)) {
  const std::uint64_t now = monotonic_ns();
  guarded([&] {
    on_remove(theObject, theUserSuppliedTag, &theTime, receivedOrder, true, now);
  });
}

void Observer::on_discover(rti1516e::ObjectInstanceHandle object,
                           rti1516e::ObjectClassHandle object_class, std::wstring const& name,
                           std::uint64_t now) {
  // NAT-04: the observer subscribes at PhysicalEntity only, so that is the class every
  // discovery names; it writes the qualified name it resolved, never asks the RTI for one.
  if (!(object_class == physical_entity_)) {
    fail(kCaptureSchema, kOtherClass);
    return;
  }
  std::size_t bytes = 0;
  if (!utf8_length(name, &bytes)) {
    fail(kCaptureSchema, kBadObjectName);
    return;
  }
  if (bytes > kMaxObjectNameBytes) {
    fail(kLimit, kLongObjectName);
    return;
  }
  std::map<rti1516e::ObjectInstanceHandle, TokenEntry>::iterator entry = tokens_.find(object);
  // NAT-11: an unmapped or removed handle is a new object with the next token; an active one
  // keeps its token (the host judges the rediscovery).
  const bool fresh = entry == tokens_.end() || !entry->second.active;
  if (fresh && allocated_ >= kMaxObjectTokens) {
    fail(kLimit, kTooManyTokens);
    return;
  }
  Record record;
  record.kind = Record::Kind::kDiscover;
  record.monotonic_ns = now;
  record.text = to_utf8(name);
  record.queue_bytes = bytes;
  if (!reserve(record)) return;
  if (fresh) {
    record.token = allocate_token();
    tokens_[object] = TokenEntry{record.token, true};
    requests_.push_back(object);
  } else {
    record.token = entry->second.token;
  }
  append(&record);
}

bool Observer::check_time(rti1516e::LogicalTime const& time, std::size_t* implementation_bytes) {
  if (time.encodedLength() > kMaxLogicalTimeBytes) {
    fail(kLimit, kLongTime);
    return false;
  }
  const std::wstring implementation = time.implementationName();
  if (!utf8_length(implementation, implementation_bytes)) {
    fail(kCaptureSchema, kBadTimeName);
    return false;
  }
  if (*implementation_bytes > kMaxImplementationNameBytes) {
    fail(kCaptureSchema, kLongTimeName);
    return false;
  }
  return true;
}

bool Observer::copy_time(rti1516e::LogicalTime const& time, Record* record) {
  // R13, NAT-17: the implementation's name and its own encoding, kept as opaque bytes.
  const std::size_t length = time.encodedLength();
  std::string bytes(length, '\0');
  bool encoded = true;
  try {
    if (length > 0 && time.encode(&bytes[0], length) != length) encoded = false;
  } catch (const rti1516e::Exception&) {
    encoded = false;
  }
  if (!encoded) {
    fail(kCaptureSchema, kBadTime);
    return false;
  }
  record->has_time = true;
  record->time_implementation = to_utf8(time.implementationName());
  record->time_bytes = bytes;
  return true;
}

void Observer::on_reflect(rti1516e::ObjectInstanceHandle object,
                          rti1516e::AttributeHandleValueMap const& values,
                          rti1516e::VariableLengthData const& tag,
                          rti1516e::OrderType sent_order, rti1516e::TransportationType transport,
                          rti1516e::LogicalTime const* time, rti1516e::OrderType received_order,
                          bool retractable, std::uint64_t now) {
  // NAT-06, R41: the count first, then every size, all before a byte is copied.
  if (values.size() > kMaxAttributesPerReflection) {
    fail(kLimit, kTooManyAttributes);
    return;
  }
  std::size_t bytes = 0;
  for (rti1516e::AttributeHandleValueMap::const_iterator it = values.begin(); it != values.end();
       ++it) {
    if (it->second.size() > kMaxAttributeValueBytes) {
      fail(kLimit, kLongValue);
      return;
    }
    bytes += it->second.size();
  }
  if (tag.size() > kMaxUserTagBytes) {
    fail(kLimit, kLongTag);
    return;
  }
  bytes += tag.size();
  std::size_t implementation_bytes = 0;
  if (time != nullptr) {
    if (!check_time(*time, &implementation_bytes)) return;
    bytes += time->encodedLength() + implementation_bytes;
  }
  if (!valid_order(sent_order) || !valid_order(received_order) || !valid_transport(transport)) {
    fail(kCaptureSchema, kBadMetadata);
    return;
  }
  std::map<rti1516e::ObjectInstanceHandle, TokenEntry>::iterator entry = tokens_.find(object);
  if (entry == tokens_.end() && allocated_ >= kMaxObjectTokens) {
    fail(kLimit, kTooManyTokens);
    return;
  }
  Record record;
  record.kind = Record::Kind::kReflect;
  record.monotonic_ns = now;
  for (rti1516e::AttributeHandleValueMap::const_iterator it = values.begin(); it != values.end();
       ++it) {
    CapturedAttribute attribute;
    attribute.handle = it->first;
    std::map<rti1516e::AttributeHandle, std::string>::const_iterator known =
        subscribed_.find(it->first);
    if (known != subscribed_.end()) {
      attribute.name = known->second;
      attribute.named = true;
    }
    attribute.value = copy_bytes(it->second);
    record.attributes.push_back(attribute);
  }
  record.tag = copy_bytes(tag);
  record.sent_order = order_of(sent_order);
  record.received_order = order_of(received_order);
  record.transport = transport_of(transport);
  if (time != nullptr && !copy_time(*time, &record)) return;
  record.retractable = retractable;
  record.queue_bytes = bytes;
  if (!reserve(record)) return;
  if (entry == tokens_.end()) {
    // NAT-11: a never-discovered handle gets the next token, as an object nobody discovered:
    // the host reports it unknown, and a later discovery of the handle is a new object.
    record.token = allocate_token();
    tokens_[object] = TokenEntry{record.token, false};
  } else {
    record.token = entry->second.token;
  }
  append(&record);
}

void Observer::on_remove(rti1516e::ObjectInstanceHandle object,
                         rti1516e::VariableLengthData const& tag,
                         rti1516e::LogicalTime const* time, rti1516e::OrderType received_order,
                         bool retractable, std::uint64_t now) {
  if (tag.size() > kMaxUserTagBytes) {
    fail(kLimit, kLongTag);
    return;
  }
  std::size_t bytes = tag.size();
  std::size_t implementation_bytes = 0;
  if (time != nullptr) {
    if (!check_time(*time, &implementation_bytes)) return;
    bytes += time->encodedLength() + implementation_bytes;
  }
  if (!valid_order(received_order)) {
    fail(kCaptureSchema, kBadMetadata);
    return;
  }
  std::map<rti1516e::ObjectInstanceHandle, TokenEntry>::iterator entry = tokens_.find(object);
  if (entry == tokens_.end() && allocated_ >= kMaxObjectTokens) {
    fail(kLimit, kTooManyTokens);
    return;
  }
  Record record;
  record.kind = Record::Kind::kRemove;
  record.monotonic_ns = now;
  record.tag = copy_bytes(tag);
  record.received_order = order_of(received_order);
  if (time != nullptr && !copy_time(*time, &record)) return;
  record.retractable = retractable;
  record.queue_bytes = bytes;
  if (!reserve(record)) return;
  if (entry == tokens_.end()) {
    record.token = allocate_token();
    tokens_[object] = TokenEntry{record.token, false};
  } else {
    // NAT-11: the handle keeps its token, retired, so a repeated remove names it again.
    record.token = entry->second.token;
    entry->second.active = false;
  }
  append(&record);
}

}  // namespace sc_hla
