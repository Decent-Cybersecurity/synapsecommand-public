// Test only: the recording decorator of NAT-07 (b).
//
// It wraps the RTIambassador the worker's observer gets from its AmbassadorSource. It forwards
// exactly the calls a receive-only observer makes (connect with HLA_EVOKED; join by name with
// the federate type SynapseCommandObserver and no FOM module; getObjectClassHandle of
// PhysicalEntity; getAttributeHandle of the four attributes there; getAttributeName at
// PhysicalEntity; subscribeObjectClassAttributes of the four, active, no rate; the object
// instance's requestAttributeValueUpdate of the four with an empty tag; evokeMultipleCallbacks
// (0.0, 0.05); resign with NO_ACTION; disconnect), writes one JSON line per call to the call
// log, and fails on anything else: a forbidden call, or an allowed one with other arguments, is
// logged and aborts the process. The observer cannot tell it from the RTI's own ambassador.
//
// R12 forbids calling the RTI inside a callback. The decorator fails on any call made while the
// inner ambassador is dispatching callbacks (inside evokeMultipleCallbacks) or while the harness
// is calling one of the observer's callbacks directly (`set_in_callback`).
//
// For the scenarios that need an attribute name no compliant RTI hands out (one over 128 bytes,
// one that is not Unicode, one that collides), `inject_name` makes getAttributeName answer a
// given handle with a given name after forwarding the call.
//
// For the rows of the observer's exception table that no compliant RTI produces on demand
// (CR-new-R7-10), `inject_fault` makes the next call of one allowed service fail with a named
// exception of that service's own specification. The call is logged as usual, then an
// `injected` line; resign and disconnect are made first and fail afterwards (so the harness's
// own federation can still be destroyed), every other call fails instead of being made. The
// fault "SIGTERM" sends the process SIGTERM and then makes the call: a stop that arrives while
// that call blocks (CR-new-R7-16). The exception's own text says it was injected; the observer
// must never pass it on (CR-new-R7-15).
#ifndef SC_HLA_RECORDING_AMBASSADOR_H
#define SC_HLA_RECORDING_AMBASSADOR_H

// <memory> first, before any RTI header. Below C++17 the rti1516e headers hand out
// std::auto_ptr (RTI_UNIQUE_PTR) but never include <memory>: libc++ happens to declare it
// through other headers, libstdc++ (GCC 13, the reference compiler) does not, and the build
// fails there without this line (Linux reference run, finding F1).
#include <memory>

#include <RTI/RTIambassador.h>
#include <RTI/RangeBounds.h>

#include <cstddef>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "observer.h"

namespace sc_hla_test {

// One JSON object per line, appended to a file the harness opened.
class CallLog {
 public:
  explicit CallLog(int fd);
  void line(const std::string& json);

 private:
  int fd_;
};

class RecordingAmbassador : public rti1516e::RTIambassador {
 public:
  RecordingAmbassador(RTI_UNIQUE_PTR<rti1516e::RTIambassador> inner, CallLog& log);
  ~RecordingAmbassador() override;

  void inject_name(rti1516e::AttributeHandle handle, const std::wstring& name);
  void inject_fault(const std::string& call, const std::string& fault);
  void set_in_callback(bool inside) { in_callback_ = inside; }

#include "recording_ambassador_calls.h"

 private:
  [[noreturn]] void forbidden(const char* name) const;
  // Fails when a callback is running (R12); called first by every allowed member.
  void outside_callbacks(const char* name) const;
  void flush_evokes();
  void log(const std::string& json);
  // The fault planned for `call`, taken (empty when none); logged when there is one.
  std::string take_fault(const char* call);

  RTI_UNIQUE_PTR<rti1516e::RTIambassador> inner_;
  CallLog& log_;
  std::size_t evokes_ = 0;
  bool in_callback_ = false;
  bool in_evoke_ = false;
  bool have_class_ = false;
  rti1516e::ObjectClassHandle physical_entity_;
  rti1516e::AttributeHandleSet four_;
  std::map<rti1516e::AttributeHandle, std::wstring> injected_;
  std::map<std::string, std::string> faults_;
};

// The source the harness hands the observer: the RTI's ambassador, wrapped.
class RecordingSource : public sc_hla::AmbassadorSource {
 public:
  explicit RecordingSource(CallLog& log);
  RTI_UNIQUE_PTR<rti1516e::RTIambassador> create() override;
  // A fault the decorator create() makes will carry from its start (inject_fault), for the
  // calls the observer makes inside open(); the call "create" fails create() itself.
  void plan_fault(const std::string& call, const std::string& fault);
  // The decorator create() made, for name injection (owned by the observer).
  RecordingAmbassador* made() const { return made_; }

 private:
  CallLog& log_;
  RecordingAmbassador* made_ = nullptr;
  std::map<std::string, std::string> planned_;
};

}  // namespace sc_hla_test

#endif  // SC_HLA_RECORDING_AMBASSADOR_H
