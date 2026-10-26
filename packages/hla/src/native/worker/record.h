// One callback record: everything a callback copied, held until the writer thread turns it into
// a worker frame (worker-frame.schema.json). A record owns its bytes: nothing in it points into
// memory the RTI may reuse once the callback returns (R12).
#ifndef SC_HLA_RECORD_H
#define SC_HLA_RECORD_H

#include <RTI/Handle.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sc_hla {

enum class Order { kReceive, kTimestamp };
enum class Transport { kReliable, kBestEffort };

struct CapturedAttribute {
  rti1516e::AttributeHandle handle;
  // Empty and `named` false until the event loop has named an attribute the observer did not
  // subscribe to (NAT-06); one of the four names otherwise.
  std::string name;
  bool named = false;
  // The value bytes exactly as the RTI supplied them, padding included (R16, R18).
  std::string value;
};

struct Record {
  enum class Kind { kGenerationStart, kDiscover, kReflect, kRemove, kDiagnostic };

  Kind kind = Kind::kDiagnostic;
  // CLOCK_MONOTONIC when the callback (or the condition) happened (NAT-10, SPEC:275).
  std::uint64_t monotonic_ns = 0;
  // o1, o2, ... for discover, reflect and remove; empty otherwise.
  std::string token;
  // The federation (generation_start), the object name (discover) or the message (diagnostic),
  // as UTF-8.
  std::string text;
  // A diagnostic's code.
  std::string code;
  std::vector<CapturedAttribute> attributes;
  std::string tag;
  Order sent_order = Order::kReceive;
  Order received_order = Order::kReceive;
  Transport transport = Transport::kReliable;
  bool has_time = false;
  std::string time_implementation;
  std::string time_bytes;
  bool retractable = false;
  // What the record counts toward the queue's byte bound (see FrameQueue).
  std::size_t queue_bytes = 0;
};

// The worker frame of one record: one JSON object without its LF, with `monotonic_ns` as a
// decimal string and the event exactly as event.schema.json defines it. Attribute names must
// all be set; the caller sorts the attributes by name first (R16).
std::string serialize(const Record& record);

// Sorts the attributes of a reflection by their UTF-8 names (byte order is code point order,
// which is how the capture orders them, R16) and reports whether two share a name.
bool sort_attributes(std::vector<CapturedAttribute>* attributes);

}  // namespace sc_hla

#endif  // SC_HLA_RECORD_H
