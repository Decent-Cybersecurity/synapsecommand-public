// The fixed v1 values the native worker enforces itself (SPEC:217-231, OPS-21, OPS-22, NAT-05,
// NAT-06, NAT-11, R37). They are compile-time constants on purpose: no option, environment
// variable or configuration member reaches them, and the Python tests hold each one to the
// specification's table by reading this file.
#ifndef SC_HLA_CONSTANTS_H
#define SC_HLA_CONSTANTS_H

#include <cstddef>
#include <cstdint>

namespace sc_hla {

// Supplied attributes per reflection: more is E_LIMIT and nothing of the callback is copied.
constexpr std::size_t kMaxAttributesPerReflection = 4;
// One attribute value, checked before copying.
constexpr std::size_t kMaxAttributeValueBytes = 4096;
// One user tag, checked before copying.
constexpr std::size_t kMaxUserTagBytes = 4096;
// One object name, in UTF-8 bytes.
constexpr std::size_t kMaxObjectNameBytes = 1024;
// One encoded logical time.
constexpr std::size_t kMaxLogicalTimeBytes = 256;
// The longest attribute name and logical time implementation name a worker frame can carry
// (event.schema.json: maxLength 128), counted in UTF-8 bytes (NAT-06).
constexpr std::size_t kMaxAttributeNameBytes = 128;
constexpr std::size_t kMaxImplementationNameBytes = 128;
// The callback queue: frames and bytes, whichever fills first (R41, NAT-06).
constexpr std::size_t kMaxQueueFrames = 4096;
constexpr std::size_t kMaxQueueBytes = 16u * 1024u * 1024u;
// Object tokens one worker process may allocate (NAT-11).
constexpr std::size_t kMaxObjectTokens = 100000;
// One worker frame or status record, excluding its LF.
constexpr std::size_t kMaxLineBytes = 65536;
// The message of a failure record or diagnostic (R37), in UTF-8 bytes.
constexpr std::size_t kMaxMessageBytes = 1024;

// R12's literal event-loop call: evokeMultipleCallbacks(0.0, 0.05).
constexpr double kEvokeMinimumSeconds = 0.0;
constexpr double kEvokeMaximumSeconds = 0.05;
// NAT-05: after an evoke call that dispatched nothing, the loop pauses this long (and checks
// the stop flag and its parent afterwards), so an idle federation does not keep a core busy.
constexpr std::int64_t kIdlePauseNanoseconds = 5000000;

// The class the observer subscribes at, and the four attributes it resolves there (R10).
constexpr const char kPhysicalEntityClass[] = "HLAobjectRoot.BaseEntity.PhysicalEntity";
constexpr const wchar_t kPhysicalEntityClassWide[] = L"HLAobjectRoot.BaseEntity.PhysicalEntity";
constexpr const char kFederateType[] = "SynapseCommandObserver";

}  // namespace sc_hla

#endif  // SC_HLA_CONSTANTS_H
