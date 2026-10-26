#include "recording_ambassador.h"

#include <RTI/RTIambassadorFactory.h>
#include <signal.h>
#include <unistd.h>

#include <cstdlib>
#include <utility>

#include "channels.h"
#include "constants.h"
#include "text.h"

namespace sc_hla_test {

namespace {

using rti1516e::AlreadyConnected;
using rti1516e::AttributeNotDefined;
using rti1516e::CallNotAllowedFromWithinCallback;
using rti1516e::ConnectionFailed;
using rti1516e::CouldNotCreateLogicalTimeFactory;
using rti1516e::CouldNotOpenFDD;
using rti1516e::ErrorReadingFDD;
using rti1516e::FederateAlreadyExecutionMember;
using rti1516e::FederateIsExecutionMember;
using rti1516e::FederateNameAlreadyInUse;
using rti1516e::FederateNotExecutionMember;
using rti1516e::FederateOwnsAttributes;
using rti1516e::FederationExecutionDoesNotExist;
using rti1516e::InconsistentFDD;
using rti1516e::InvalidAttributeHandle;
using rti1516e::InvalidLocalSettingsDesignator;
using rti1516e::InvalidObjectClassHandle;
using rti1516e::InvalidResignAction;
using rti1516e::InvalidUpdateRateDesignator;
using rti1516e::NameNotFound;
using rti1516e::NotConnected;
using rti1516e::ObjectClassNotDefined;
using rti1516e::ObjectInstanceNotKnown;
using rti1516e::OwnershipAcquisitionPending;
using rti1516e::RestoreInProgress;
using rti1516e::RTIinternalError;
using rti1516e::SaveInProgress;
using rti1516e::UnsupportedCallbackModel;

const wchar_t* const kFour[] = {L"EntityIdentifier", L"EntityType", L"Spatial", L"ForceIdentifier"};

// A wide string as a JSON string (the log is test data; a name that is not Unicode is shown as
// null rather than invented).
std::string json(const std::wstring& text) {
  std::size_t bytes = 0;
  if (!sc_hla::utf8_length(text, &bytes)) return "null";
  std::string out;
  sc_hla::append_json_string(&out, sc_hla::to_utf8(text));
  return out;
}

bool one_of_the_four(const std::wstring& name) {
  for (const wchar_t* each : kFour) {
    if (name == each) return true;
  }
  return false;
}

const char kStop[] = "SIGTERM";

// A planned stop: the process sends itself SIGTERM, whose handler only sets the worker's flag,
// before the call is made.
void stop_if(const std::string& fault) {
  if (fault == kStop) ::kill(::getpid(), SIGTERM);
}

// A planned exception, thrown from inside the service that was called: one outside that
// service's exception specification ends the process (std::unexpected) instead of passing unseen.
void throw_if(const std::string& fault) {
  if (fault.empty() || fault == kStop) return;
  const std::wstring what = L"injected by sc-hla-harness: " + sc_hla::widen_ascii(fault);
  if (fault == "CouldNotCreateLogicalTimeFactory") throw CouldNotCreateLogicalTimeFactory(what);
  if (fault == "InconsistentFDD") throw InconsistentFDD(what);
  if (fault == "ErrorReadingFDD") throw ErrorReadingFDD(what);
  if (fault == "CouldNotOpenFDD") throw CouldNotOpenFDD(what);
  if (fault == "NameNotFound") throw NameNotFound(what);
  if (fault == "ObjectClassNotDefined") throw ObjectClassNotDefined(what);
  if (fault == "AttributeNotDefined") throw AttributeNotDefined(what);
  if (fault == "InvalidObjectClassHandle") throw InvalidObjectClassHandle(what);
  if (fault == "RTIinternalError") throw RTIinternalError(what);
  sc_hla::write_all(2, "sc-hla-harness: unknown fault " + fault + "\n");
  std::abort();
}

}  // namespace

CallLog::CallLog(int fd) : fd_(fd) {}

void CallLog::line(const std::string& json_text) { sc_hla::write_all(fd_, json_text + "\n"); }

RecordingAmbassador::RecordingAmbassador(RTI_UNIQUE_PTR<rti1516e::RTIambassador> inner,
                                         CallLog& log)
    : inner_(inner), log_(log) {}

RecordingAmbassador::~RecordingAmbassador() { flush_evokes(); }

void RecordingAmbassador::inject_name(rti1516e::AttributeHandle handle, const std::wstring& name) {
  injected_[handle] = name;
}

void RecordingAmbassador::inject_fault(const std::string& call, const std::string& fault) {
  faults_[call] = fault;
}

std::string RecordingAmbassador::take_fault(const char* call) {
  std::map<std::string, std::string>::iterator planned = faults_.find(call);
  if (planned == faults_.end()) return std::string();
  const std::string fault = planned->second;
  faults_.erase(planned);
  std::string line = "{\"call\":";
  sc_hla::append_json_string(&line, call);
  line.append(",\"injected\":");
  sc_hla::append_json_string(&line, fault);
  log(line + "}");
  return fault;
}

void RecordingAmbassador::flush_evokes() {
  if (evokes_ == 0) return;
  log_.line("{\"call\":\"evokeMultipleCallbacks\",\"count\":" + std::to_string(evokes_) +
            ",\"maximum\":0.05,\"minimum\":0.0}");
  evokes_ = 0;
}

void RecordingAmbassador::log(const std::string& json_text) {
  flush_evokes();
  log_.line(json_text);
}

void RecordingAmbassador::forbidden(const char* name) const {
  std::string line = "{\"call\":";
  sc_hla::append_json_string(&line, name);
  line.append(",\"forbidden\":true}");
  log_.line(line);
  sc_hla::write_all(2, std::string("sc-hla-harness: forbidden RTI call ") + name + "\n");
  std::abort();
}

void RecordingAmbassador::outside_callbacks(const char* name) const {
  if (!in_callback_ && !in_evoke_) return;
  std::string line = "{\"call\":";
  sc_hla::append_json_string(&line, name);
  line.append(",\"forbidden\":true,\"within_callback\":true}");
  log_.line(line);
  sc_hla::write_all(2, std::string("sc-hla-harness: RTI call within a callback: ") + name + "\n");
  std::abort();
}

void RecordingAmbassador::connect(rti1516e::FederateAmbassador& federateAmbassador,
                                  rti1516e::CallbackModel theCallbackModel,
                                  std::wstring const& localSettingsDesignator)
    RTI_THROW((ConnectionFailed, InvalidLocalSettingsDesignator, UnsupportedCallbackModel,
               AlreadyConnected, CallNotAllowedFromWithinCallback, RTIinternalError)) {
  outside_callbacks("connect");
  if (theCallbackModel != rti1516e::HLA_EVOKED) forbidden("connect");
  log("{\"call\":\"connect\",\"designator\":" + json(localSettingsDesignator) +
      ",\"model\":\"HLA_EVOKED\"}");
  const std::string fault = take_fault("connect");
  stop_if(fault);
  throw_if(fault);
  inner_->connect(federateAmbassador, theCallbackModel, localSettingsDesignator);
}

void RecordingAmbassador::disconnect()
    RTI_THROW((FederateIsExecutionMember, CallNotAllowedFromWithinCallback, RTIinternalError)) {
  outside_callbacks("disconnect");
  log("{\"call\":\"disconnect\"}");
  const std::string fault = take_fault("disconnect");
  stop_if(fault);
  inner_->disconnect();
  throw_if(fault);
}

rti1516e::FederateHandle RecordingAmbassador::joinFederationExecution(
    std::wstring const& federateName, std::wstring const& federateType,
    std::wstring const& federationExecutionName,
    std::vector<std::wstring> const& additionalFomModules)
    RTI_THROW((CouldNotCreateLogicalTimeFactory, FederateNameAlreadyInUse,
               FederationExecutionDoesNotExist, InconsistentFDD, ErrorReadingFDD, CouldNotOpenFDD,
               SaveInProgress, RestoreInProgress, FederateAlreadyExecutionMember, NotConnected,
               CallNotAllowedFromWithinCallback, RTIinternalError)) {
  outside_callbacks("joinFederationExecution");
  // R10: never a FOM module of the observer's own.
  if (!additionalFomModules.empty() || federateType != sc_hla::widen_ascii(sc_hla::kFederateType)) {
    forbidden("joinFederationExecution");
  }
  log("{\"call\":\"joinFederationExecution\",\"federate_name\":" + json(federateName) +
      ",\"federate_type\":" + json(federateType) + ",\"federation\":" +
      json(federationExecutionName) + ",\"modules\":0}");
  const std::string fault = take_fault("joinFederationExecution");
  stop_if(fault);
  throw_if(fault);
  return inner_->joinFederationExecution(federateName, federateType, federationExecutionName,
                                         additionalFomModules);
}

void RecordingAmbassador::resignFederationExecution(rti1516e::ResignAction resignAction)
    RTI_THROW((InvalidResignAction, OwnershipAcquisitionPending, FederateOwnsAttributes,
               FederateNotExecutionMember, NotConnected, CallNotAllowedFromWithinCallback,
               RTIinternalError)) {
  outside_callbacks("resignFederationExecution");
  if (resignAction != rti1516e::NO_ACTION) forbidden("resignFederationExecution");
  log("{\"action\":\"NO_ACTION\",\"call\":\"resignFederationExecution\"}");
  const std::string fault = take_fault("resignFederationExecution");
  stop_if(fault);
  inner_->resignFederationExecution(resignAction);
  throw_if(fault);
}

void RecordingAmbassador::subscribeObjectClassAttributes(
    rti1516e::ObjectClassHandle theClass, rti1516e::AttributeHandleSet const& attributeList,
    bool active, std::wstring const& updateRateDesignator)
    RTI_THROW((AttributeNotDefined, ObjectClassNotDefined, InvalidUpdateRateDesignator,
               SaveInProgress, RestoreInProgress, FederateNotExecutionMember, NotConnected,
               RTIinternalError)) {
  outside_callbacks("subscribeObjectClassAttributes");
  // R10: the four attributes, at PhysicalEntity, active, without a rate or a region.
  if (!have_class_ || !(theClass == physical_entity_) || !(attributeList == four_) || !active ||
      four_.size() != 4 || !updateRateDesignator.empty()) {
    forbidden("subscribeObjectClassAttributes");
  }
  log("{\"active\":true,\"attributes\":4,\"call\":\"subscribeObjectClassAttributes\","
      "\"class\":\"HLAobjectRoot.BaseEntity.PhysicalEntity\",\"update_rate\":\"\"}");
  const std::string fault = take_fault("subscribeObjectClassAttributes");
  stop_if(fault);
  throw_if(fault);
  inner_->subscribeObjectClassAttributes(theClass, attributeList, active, updateRateDesignator);
}

void RecordingAmbassador::requestAttributeValueUpdate(
    rti1516e::ObjectInstanceHandle theObject, rti1516e::AttributeHandleSet const& theAttributes,
    rti1516e::VariableLengthData const& theUserSuppliedTag)
    RTI_THROW((AttributeNotDefined, ObjectInstanceNotKnown, SaveInProgress, RestoreInProgress,
               FederateNotExecutionMember, NotConnected, RTIinternalError)) {
  outside_callbacks("requestAttributeValueUpdate");
  // R12: the same four attributes, with an empty tag.
  if (!(theAttributes == four_) || four_.size() != 4 || theUserSuppliedTag.size() != 0) {
    forbidden("requestAttributeValueUpdate");
  }
  const std::string fault = take_fault("requestAttributeValueUpdate");
  stop_if(fault);
  throw_if(fault);
  std::string outcome = "forwarded";
  try {
    inner_->requestAttributeValueUpdate(theObject, theAttributes, theUserSuppliedTag);
  } catch (const ObjectInstanceNotKnown&) {
    log("{\"attributes\":4,\"call\":\"requestAttributeValueUpdate\",\"outcome\":"
        "\"ObjectInstanceNotKnown\",\"tag_bytes\":0}");
    throw;
  }
  log("{\"attributes\":4,\"call\":\"requestAttributeValueUpdate\",\"outcome\":\"" + outcome +
      "\",\"tag_bytes\":0}");
}

rti1516e::ObjectClassHandle RecordingAmbassador::getObjectClassHandle(std::wstring const& theName)
    RTI_THROW((NameNotFound, FederateNotExecutionMember, NotConnected, RTIinternalError)) {
  outside_callbacks("getObjectClassHandle");
  // R10: PhysicalEntity and nothing else; no subclass is resolved to infer a type.
  if (theName != sc_hla::kPhysicalEntityClassWide) forbidden("getObjectClassHandle");
  log("{\"call\":\"getObjectClassHandle\",\"name\":" + json(theName) + "}");
  const std::string fault = take_fault("getObjectClassHandle");
  stop_if(fault);
  throw_if(fault);
  physical_entity_ = inner_->getObjectClassHandle(theName);
  have_class_ = true;
  return physical_entity_;
}

rti1516e::AttributeHandle RecordingAmbassador::getAttributeHandle(
    rti1516e::ObjectClassHandle whichClass, std::wstring const& theAttributeName)
    RTI_THROW((NameNotFound, InvalidObjectClassHandle, FederateNotExecutionMember, NotConnected,
               RTIinternalError)) {
  outside_callbacks("getAttributeHandle");
  if (!have_class_ || !(whichClass == physical_entity_) || !one_of_the_four(theAttributeName)) {
    forbidden("getAttributeHandle");
  }
  log("{\"call\":\"getAttributeHandle\",\"name\":" + json(theAttributeName) + "}");
  const std::string fault = take_fault("getAttributeHandle");
  stop_if(fault);
  throw_if(fault);
  const rti1516e::AttributeHandle handle = inner_->getAttributeHandle(whichClass, theAttributeName);
  four_.insert(handle);
  return handle;
}

std::wstring RecordingAmbassador::getAttributeName(rti1516e::ObjectClassHandle whichClass,
                                                   rti1516e::AttributeHandle theHandle)
    RTI_THROW((AttributeNotDefined, InvalidAttributeHandle, InvalidObjectClassHandle,
               FederateNotExecutionMember, NotConnected, RTIinternalError)) {
  outside_callbacks("getAttributeName");
  if (!have_class_ || !(whichClass == physical_entity_)) forbidden("getAttributeName");
  std::map<rti1516e::AttributeHandle, std::wstring>::const_iterator injected =
      injected_.find(theHandle);
  std::wstring name;
  try {
    name = inner_->getAttributeName(whichClass, theHandle);
  } catch (const rti1516e::Exception&) {
    log("{\"call\":\"getAttributeName\",\"outcome\":\"refused\"}");
    throw;
  }
  if (injected != injected_.end()) {
    log("{\"call\":\"getAttributeName\",\"outcome\":\"injected\"}");
    return injected->second;
  }
  log("{\"call\":\"getAttributeName\",\"name\":" + json(name) + ",\"outcome\":\"forwarded\"}");
  return name;
}

bool RecordingAmbassador::evokeMultipleCallbacks(double approximateMinimumTimeInSeconds,
                                                 double approximateMaximumTimeInSeconds)
    RTI_THROW((CallNotAllowedFromWithinCallback, RTIinternalError)) {
  outside_callbacks("evokeMultipleCallbacks");
  // R12's literal parameters (NAT-05).
  if (approximateMinimumTimeInSeconds != sc_hla::kEvokeMinimumSeconds ||
      approximateMaximumTimeInSeconds != sc_hla::kEvokeMaximumSeconds) {
    forbidden("evokeMultipleCallbacks");
  }
  const std::string fault = take_fault("evokeMultipleCallbacks");
  stop_if(fault);
  throw_if(fault);
  evokes_ += 1;
  in_evoke_ = true;
  bool more = false;
  try {
    more = inner_->evokeMultipleCallbacks(approximateMinimumTimeInSeconds,
                                          approximateMaximumTimeInSeconds);
  } catch (...) {
    in_evoke_ = false;
    throw;
  }
  in_evoke_ = false;
  return more;
}

RecordingSource::RecordingSource(CallLog& log) : log_(log) {}

void RecordingSource::plan_fault(const std::string& call, const std::string& fault) {
  planned_[call] = fault;
}

RTI_UNIQUE_PTR<rti1516e::RTIambassador> RecordingSource::create() {
  // A planned failure of the factory itself (review finding R7-r2-F5): the observer's open()
  // must end the run with E_RTI_CONNECT before any stage record.
  std::map<std::string, std::string>::iterator planned = planned_.find("create");
  if (planned != planned_.end()) {
    const std::string fault = planned->second;
    planned_.erase(planned);
    // Logged as the factory's, not as a call: no RTI service was called.
    std::string line = "{\"factory\":\"create\",\"injected\":";
    sc_hla::append_json_string(&line, fault);
    log_.line(line + "}");
    throw_if(fault);
  }
  rti1516e::RTIambassadorFactory factory;
  RecordingAmbassador* made = new RecordingAmbassador(factory.createRTIambassador(), log_);
  for (const auto& planned : planned_) made->inject_fault(planned.first, planned.second);
  made_ = made;
  return RTI_UNIQUE_PTR<rti1516e::RTIambassador>(made);
}

}  // namespace sc_hla_test
