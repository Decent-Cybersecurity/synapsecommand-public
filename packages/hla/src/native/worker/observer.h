// The observer: the receive-only federate of profile SC-HLA-RPR2-OBS-1 (R10-R14).
//
// It is the FederateAmbassador the RTI calls back and the event loop that calls the RTI, on one
// thread (SPEC:279). A callback copies what it is given into a record, stamps it with
// CLOCK_MONOTONIC and appends it to the batch of the evoke call it runs in, after checking every
// size against its bound and the queue's room; it never calls the RTI (R12). When the evoke call
// returns, the event loop names any attribute the observer did not subscribe to, hands the batch
// to the writer, and asks for the attribute values of each object discovered in it (NAT-06,
// R12). A terminal condition ends the dispatching: the records accepted before it are written,
// the condition is reported once on fd 3 (and as a diagnostic frame when the queue has room),
// and the observer resigns and disconnects (NAT-08).
#ifndef SC_HLA_OBSERVER_H
#define SC_HLA_OBSERVER_H

// <memory> first, before any RTI header. Below C++17 the rti1516e headers hand out
// std::auto_ptr (RTI_UNIQUE_PTR) but never include <memory>: libc++ happens to declare it
// through other headers, libstdc++ (GCC 13, the reference compiler) does not, and the build
// fails there without this line (Linux reference run, finding F1).
#include <memory>

#include <RTI/NullFederateAmbassador.h>
#include <RTI/RTIambassador.h>

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "channels.h"
#include "process.h"
#include "record.h"

namespace sc_hla {

// Where the observer gets its RTIambassador from (NAT-07 b): the worker asks
// rti1516e::RTIambassadorFactory; a test may hand it a wrapped one. The observer does not know
// which.
class AmbassadorSource {
 public:
  virtual ~AmbassadorSource();
  virtual RTI_UNIQUE_PTR<rti1516e::RTIambassador> create() = 0;
};

class FactorySource : public AmbassadorSource {
 public:
  RTI_UNIQUE_PTR<rti1516e::RTIambassador> create() override;
};

// A terminal condition: one of OPS-30's codes and a fixed message (R37).
struct Condition {
  std::string code;
  std::string message;
};

class Observer : public rti1516e::NullFederateAmbassador {
 public:
  Observer(const Options& options, StatusChannel& status, FrameQueue& frames,
           const ParentWatch& parent);
  ~Observer() RTI_NOEXCEPT override;

  // The whole life of one worker process: open, the event loop, close. The exit status.
  int run(AmbassadorSource& source, const std::wstring& local_settings_designator);

  // The steps of run(). The test harness (NAT-07 a) runs them itself, around the callbacks it
  // drives directly.
  // connect, join, generation_start, resolve and subscribe; false when the observer must close.
  bool open(AmbassadorSource& source, const std::wstring& local_settings_designator);
  // What follows one evoke call: name, hand over, request updates, report a new condition.
  void end_batch();
  // One turn of the event loop: evokeMultipleCallbacks(0.0, 0.05), end_batch(), and the idle
  // pause of NAT-05 when nothing was dispatched. False once the loop must end: a stop, a
  // terminal condition, a broken channel or a parent that has gone.
  bool step();
  // step() until it returns false.
  void event_loop();
  // Report a condition not yet reported, resign, disconnect, and let the writer finish. The
  // exit status.
  int close();

  bool has_condition() const { return has_condition_; }
  std::uint64_t callbacks() const { return callbacks_; }
  const Condition& condition() const { return condition_; }
  rti1516e::ObjectClassHandle physical_entity() const { return physical_entity_; }

  // FederateAmbassador: the overloads of the pinned headers that concern an observer of
  // object attributes (R12). Everything else is NullFederateAmbassador's no-op.
  void connectionLost(std::wstring const& faultDescription)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void discoverObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                              rti1516e::ObjectClassHandle theObjectClass,
                              std::wstring const& theObjectInstanceName)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void discoverObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                              rti1516e::ObjectClassHandle theObjectClass,
                              std::wstring const& theObjectInstanceName,
                              rti1516e::FederateHandle producingFederate)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void reflectAttributeValues(rti1516e::ObjectInstanceHandle theObject,
                              rti1516e::AttributeHandleValueMap const& theAttributeValues,
                              rti1516e::VariableLengthData const& theUserSuppliedTag,
                              rti1516e::OrderType sentOrder, rti1516e::TransportationType theType,
                              rti1516e::SupplementalReflectInfo theReflectInfo)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void reflectAttributeValues(rti1516e::ObjectInstanceHandle theObject,
                              rti1516e::AttributeHandleValueMap const& theAttributeValues,
                              rti1516e::VariableLengthData const& theUserSuppliedTag,
                              rti1516e::OrderType sentOrder, rti1516e::TransportationType theType,
                              rti1516e::LogicalTime const& theTime,
                              rti1516e::OrderType receivedOrder,
                              rti1516e::SupplementalReflectInfo theReflectInfo)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void reflectAttributeValues(rti1516e::ObjectInstanceHandle theObject,
                              rti1516e::AttributeHandleValueMap const& theAttributeValues,
                              rti1516e::VariableLengthData const& theUserSuppliedTag,
                              rti1516e::OrderType sentOrder, rti1516e::TransportationType theType,
                              rti1516e::LogicalTime const& theTime,
                              rti1516e::OrderType receivedOrder,
                              rti1516e::MessageRetractionHandle theHandle,
                              rti1516e::SupplementalReflectInfo theReflectInfo)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void removeObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                            rti1516e::VariableLengthData const& theUserSuppliedTag,
                            rti1516e::OrderType sentOrder,
                            rti1516e::SupplementalRemoveInfo theRemoveInfo)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void removeObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                            rti1516e::VariableLengthData const& theUserSuppliedTag,
                            rti1516e::OrderType sentOrder, rti1516e::LogicalTime const& theTime,
                            rti1516e::OrderType receivedOrder,
                            rti1516e::SupplementalRemoveInfo theRemoveInfo)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void removeObjectInstance(rti1516e::ObjectInstanceHandle theObject,
                            rti1516e::VariableLengthData const& theUserSuppliedTag,
                            rti1516e::OrderType sentOrder, rti1516e::LogicalTime const& theTime,
                            rti1516e::OrderType receivedOrder,
                            rti1516e::MessageRetractionHandle theHandle,
                            rti1516e::SupplementalRemoveInfo theRemoveInfo)
      RTI_THROW((rti1516e::FederateInternalError)) override;

  void requestRetraction(rti1516e::MessageRetractionHandle theHandle)
      RTI_THROW((rti1516e::FederateInternalError)) override;

 private:
  // The handle-to-token map of NAT-11: a token stays with its handle after a removal, so that
  // a later remove or reflect of that handle names the retired token.
  struct TokenEntry {
    std::string token;
    bool active;
  };

  template <typename Body>
  void guarded(Body body);
  void on_discover(rti1516e::ObjectInstanceHandle object, rti1516e::ObjectClassHandle object_class,
                   std::wstring const& name, std::uint64_t now);
  void on_reflect(rti1516e::ObjectInstanceHandle object,
                  rti1516e::AttributeHandleValueMap const& values,
                  rti1516e::VariableLengthData const& tag, rti1516e::OrderType sent_order,
                  rti1516e::TransportationType transport, rti1516e::LogicalTime const* time,
                  rti1516e::OrderType received_order, bool retractable, std::uint64_t now);
  void on_remove(rti1516e::ObjectInstanceHandle object, rti1516e::VariableLengthData const& tag,
                 rti1516e::LogicalTime const* time, rti1516e::OrderType received_order,
                 bool retractable, std::uint64_t now);
  // Checks a supplied logical time against its bounds before anything is copied; false with
  // the condition set.
  bool check_time(rti1516e::LogicalTime const& time, std::size_t* implementation_bytes);
  // Copies a checked logical time into `record`; false with the condition set when the time
  // cannot encode itself.
  bool copy_time(rti1516e::LogicalTime const& time, Record* record);
  // Reserves the queue's room for `record` (R41: counts before appending); false with
  // E_QUEUE_OVERFLOW.
  bool reserve(const Record& record);
  // Appends a record whose room is reserved to the batch.
  void append(Record* record);
  std::string allocate_token();

  bool name_attribute(CapturedAttribute* attribute, std::string* fault);
  void request_updates();
  void fail(const char* code, const char* message);
  void report();
  bool stage(const char* name);
  void enqueue_generation_start();

  Options options_;
  StatusChannel& status_;
  FrameQueue& frames_;
  const ParentWatch& parent_;
  RTI_UNIQUE_PTR<rti1516e::RTIambassador> rti_;
  bool connected_ = false;
  bool joined_ = false;

  rti1516e::ObjectClassHandle physical_entity_;
  rti1516e::AttributeHandleSet four_;
  std::map<rti1516e::AttributeHandle, std::string> subscribed_;
  std::map<rti1516e::AttributeHandle, std::string> named_;

  std::map<rti1516e::ObjectInstanceHandle, TokenEntry> tokens_;
  std::size_t allocated_ = 0;
  std::vector<Record> batch_;
  std::vector<rti1516e::ObjectInstanceHandle> requests_;
  std::uint64_t callbacks_ = 0;

  bool has_condition_ = false;
  bool reported_ = false;
  Condition condition_;
  std::uint64_t condition_ns_ = 0;
  bool lost_ = false;
  bool orphaned_ = false;
};

}  // namespace sc_hla

#endif  // SC_HLA_OBSERVER_H
