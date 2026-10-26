#include "record.h"

#include <algorithm>

#include "constants.h"
#include "text.h"

namespace sc_hla {

namespace {

// The longest frame the worker's bounds allow, counted generously: a reflection with four
// 4096-byte values under 128-byte names made only of control characters (each escaped in six
// bytes), a 4096-byte tag, a 256-byte logical time under such an implementation name, a
// 20-digit stamp and 512 bytes for every member name, quote and separator. It fits the line
// limit, so the writer never meets a record it accepted and cannot write as one line.
constexpr std::size_t kLongestFrame =
    512 + kMaxAttributesPerReflection * (2 * kMaxAttributeValueBytes + 6 * kMaxAttributeNameBytes) +
    2 * kMaxUserTagBytes + 2 * kMaxLogicalTimeBytes + 6 * kMaxImplementationNameBytes + 20;
static_assert(kLongestFrame <= kMaxLineBytes, "a worker frame could pass the line limit");
// A discover is shorter still: 1024 name bytes escaped in at most six bytes each.
static_assert(512 + 6 * kMaxObjectNameBytes <= kMaxLineBytes, "a discover could pass the limit");

const char* order_name(Order order) {
  return order == Order::kReceive ? "RECEIVE" : "TIMESTAMP";
}

const char* transport_name(Transport transport) {
  return transport == Transport::kReliable ? "RELIABLE" : "BEST_EFFORT";
}

void append_member(std::string* out, const char* name) {
  out->push_back('"');
  out->append(name);
  out->append("\":");
}

void append_time(std::string* out, const Record& record) {
  append_member(out, "logical_time");
  if (!record.has_time) {
    out->append("null");
    return;
  }
  out->push_back('{');
  append_member(out, "hex");
  out->push_back('"');
  append_hex(out, record.time_bytes);
  out->append("\",");
  append_member(out, "implementation");
  append_json_string(out, record.time_implementation);
  out->push_back('}');
}

void append_tag(std::string* out, const Record& record) {
  append_member(out, "tag_hex");
  out->push_back('"');
  append_hex(out, record.tag);
  out->push_back('"');
}

void append_token(std::string* out, const Record& record) {
  append_member(out, "object_token");
  append_json_string(out, record.token);
}

}  // namespace

std::string serialize(const Record& record) {
  std::string out = "{\"event\":{";
  switch (record.kind) {
    case Record::Kind::kGenerationStart:
      append_member(&out, "federation_name");
      append_json_string(&out, record.text);
      out.append(",\"type\":\"generation_start\"");
      break;
    case Record::Kind::kDiscover:
      append_member(&out, "name");
      append_json_string(&out, record.text);
      out.push_back(',');
      append_token(&out, record);
      out.push_back(',');
      append_member(&out, "reported_class");
      append_json_string(&out, kPhysicalEntityClass);
      out.append(",\"type\":\"discover\"");
      break;
    case Record::Kind::kReflect:
      append_member(&out, "attributes");
      out.push_back('[');
      for (std::size_t i = 0; i < record.attributes.size(); ++i) {
        if (i > 0) out.push_back(',');
        out.append("{\"hex\":\"");
        append_hex(&out, record.attributes[i].value);
        out.append("\",\"name\":");
        append_json_string(&out, record.attributes[i].name);
        out.push_back('}');
      }
      out.append("],");
      append_time(&out, record);
      out.push_back(',');
      append_token(&out, record);
      out.push_back(',');
      append_member(&out, "received_order");
      out.append("\"").append(order_name(record.received_order)).append("\",");
      append_member(&out, "retractable");
      out.append(record.retractable ? "true," : "false,");
      append_member(&out, "sent_order");
      out.append("\"").append(order_name(record.sent_order)).append("\",");
      append_tag(&out, record);
      out.push_back(',');
      append_member(&out, "transport");
      out.append("\"").append(transport_name(record.transport)).append("\",");
      out.append("\"type\":\"reflect\"");
      break;
    case Record::Kind::kRemove:
      // NAT-17: the remove event has no sent_order; the supplied one is not kept.
      append_time(&out, record);
      out.push_back(',');
      append_token(&out, record);
      out.push_back(',');
      append_member(&out, "received_order");
      out.append("\"").append(order_name(record.received_order)).append("\",");
      append_member(&out, "retractable");
      out.append(record.retractable ? "true," : "false,");
      append_tag(&out, record);
      out.append(",\"type\":\"remove\"");
      break;
    case Record::Kind::kDiagnostic:
      // A worker diagnostic names no object and no attribute: it is the copy of a terminal
      // condition of the worker, which the host also learns from the status channel.
      out.append("\"diagnostic\":{\"attribute\":null,");
      append_member(&out, "code");
      append_json_string(&out, record.code);
      out.push_back(',');
      append_member(&out, "message");
      append_json_string(&out, record.text);
      out.append(",\"severity\":\"ERROR\"},\"object_token\":null,\"type\":\"diagnostic\"");
      break;
  }
  out.append("},\"monotonic_ns\":\"");
  out.append(std::to_string(record.monotonic_ns));
  out.append("\"}");
  return out;
}

bool sort_attributes(std::vector<CapturedAttribute>* attributes) {
  std::sort(attributes->begin(), attributes->end(),
            [](const CapturedAttribute& a, const CapturedAttribute& b) { return a.name < b.name; });
  for (std::size_t i = 1; i < attributes->size(); ++i) {
    if ((*attributes)[i - 1].name == (*attributes)[i].name) return false;
  }
  return true;
}

}  // namespace sc_hla
