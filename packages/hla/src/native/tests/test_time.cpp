#include "test_time.h"

#include <algorithm>
#include <new>
#include <stdexcept>

namespace sc_hla_test {

TestTime::TestTime(const std::wstring& implementation, const std::string& bytes, Fault fault)
    : implementation_(implementation), bytes_(bytes), fault_(fault) {}

TestTime::~TestTime() RTI_NOEXCEPT {}

void TestTime::setInitial() {}
bool TestTime::isInitial() const { return false; }
void TestTime::setFinal() {}
bool TestTime::isFinal() const { return false; }

rti1516e::LogicalTime& TestTime::operator=(rti1516e::LogicalTime const&)
    RTI_THROW((rti1516e::InvalidLogicalTime)) {
  throw rti1516e::InvalidLogicalTime(L"a test time is not assigned");
}

rti1516e::LogicalTime& TestTime::operator+=(rti1516e::LogicalTimeInterval const&)
    RTI_THROW((rti1516e::IllegalTimeArithmetic, rti1516e::InvalidLogicalTimeInterval)) {
  throw rti1516e::IllegalTimeArithmetic(L"a test time has no arithmetic");
}

rti1516e::LogicalTime& TestTime::operator-=(rti1516e::LogicalTimeInterval const&)
    RTI_THROW((rti1516e::IllegalTimeArithmetic, rti1516e::InvalidLogicalTimeInterval)) {
  throw rti1516e::IllegalTimeArithmetic(L"a test time has no arithmetic");
}

bool TestTime::operator>(rti1516e::LogicalTime const&) const
    RTI_THROW((rti1516e::InvalidLogicalTime)) {
  throw rti1516e::InvalidLogicalTime(L"a test time is not compared");
}

bool TestTime::operator<(rti1516e::LogicalTime const&) const
    RTI_THROW((rti1516e::InvalidLogicalTime)) {
  throw rti1516e::InvalidLogicalTime(L"a test time is not compared");
}

bool TestTime::operator==(rti1516e::LogicalTime const&) const
    RTI_THROW((rti1516e::InvalidLogicalTime)) {
  throw rti1516e::InvalidLogicalTime(L"a test time is not compared");
}

bool TestTime::operator>=(rti1516e::LogicalTime const&) const
    RTI_THROW((rti1516e::InvalidLogicalTime)) {
  throw rti1516e::InvalidLogicalTime(L"a test time is not compared");
}

bool TestTime::operator<=(rti1516e::LogicalTime const&) const
    RTI_THROW((rti1516e::InvalidLogicalTime)) {
  throw rti1516e::InvalidLogicalTime(L"a test time is not compared");
}

rti1516e::VariableLengthData TestTime::encode() const {
  return rti1516e::VariableLengthData(bytes_.data(), bytes_.size());
}

size_t TestTime::encode(void* buffer, size_t bufferSize) const
    RTI_THROW((rti1516e::CouldNotEncode)) {
  if (fault_ == Fault::kEncodeRefuses) throw rti1516e::CouldNotEncode(L"injected: no encoding");
  if (bufferSize < bytes_.size()) throw rti1516e::CouldNotEncode(L"buffer too small");
  std::copy(bytes_.begin(), bytes_.end(), static_cast<char*>(buffer));
  // The short encoding announces one byte more than it writes.
  return fault_ == Fault::kEncodeShort ? bytes_.size() - 1 : bytes_.size();
}

size_t TestTime::encodedLength() const {
  if (fault_ == Fault::kLengthNoMemory) throw std::bad_alloc();
  if (fault_ == Fault::kLengthOther) throw std::runtime_error("injected: not an RTI exception");
  return bytes_.size();
}

void TestTime::decode(rti1516e::VariableLengthData const&)
    RTI_THROW((rti1516e::InternalError, rti1516e::CouldNotDecode)) {
  throw rti1516e::CouldNotDecode(L"a test time is not decoded");
}

void TestTime::decode(void*, size_t)
    RTI_THROW((rti1516e::InternalError, rti1516e::CouldNotDecode)) {
  throw rti1516e::CouldNotDecode(L"a test time is not decoded");
}

std::wstring TestTime::toString() const { return L"test time"; }

std::wstring TestTime::implementationName() const { return implementation_; }

}  // namespace sc_hla_test
