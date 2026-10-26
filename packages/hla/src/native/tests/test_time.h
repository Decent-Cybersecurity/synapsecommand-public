// Test only: a logical time whose implementation name and encoding the harness chooses, for the
// bounds and the byte preservation of R13 and NAT-17 (a time of 257 bytes, an implementation
// name that is not Unicode). Only what the observer reads is meaningful: implementationName(),
// encodedLength() and encode(). Arithmetic and comparison are never used and refuse.
//
// A time may also be told to misbehave where a time from another implementation could
// (CR-new-R7-07, CR-new-R7-10): encode() refuses (CouldNotEncode) or writes fewer bytes than
// encodedLength() announced, or encodedLength() throws std::bad_alloc or an exception that is
// no RTI exception at all.
#ifndef SC_HLA_TEST_TIME_H
#define SC_HLA_TEST_TIME_H

#include <RTI/LogicalTime.h>

#include <string>

namespace sc_hla_test {

class TestTime : public rti1516e::LogicalTime {
 public:
  enum class Fault { kNone, kEncodeRefuses, kEncodeShort, kLengthNoMemory, kLengthOther };

  TestTime(const std::wstring& implementation, const std::string& bytes,
           Fault fault = Fault::kNone);
  ~TestTime() RTI_NOEXCEPT override;

  void setInitial() override;
  bool isInitial() const override;
  void setFinal() override;
  bool isFinal() const override;
  rti1516e::LogicalTime& operator=(rti1516e::LogicalTime const& value)
      RTI_THROW((rti1516e::InvalidLogicalTime)) override;
  rti1516e::LogicalTime& operator+=(rti1516e::LogicalTimeInterval const& addend)
      RTI_THROW((rti1516e::IllegalTimeArithmetic, rti1516e::InvalidLogicalTimeInterval)) override;
  rti1516e::LogicalTime& operator-=(rti1516e::LogicalTimeInterval const& subtrahend)
      RTI_THROW((rti1516e::IllegalTimeArithmetic, rti1516e::InvalidLogicalTimeInterval)) override;
  bool operator>(rti1516e::LogicalTime const& value) const
      RTI_THROW((rti1516e::InvalidLogicalTime)) override;
  bool operator<(rti1516e::LogicalTime const& value) const
      RTI_THROW((rti1516e::InvalidLogicalTime)) override;
  bool operator==(rti1516e::LogicalTime const& value) const
      RTI_THROW((rti1516e::InvalidLogicalTime)) override;
  bool operator>=(rti1516e::LogicalTime const& value) const
      RTI_THROW((rti1516e::InvalidLogicalTime)) override;
  bool operator<=(rti1516e::LogicalTime const& value) const
      RTI_THROW((rti1516e::InvalidLogicalTime)) override;
  rti1516e::VariableLengthData encode() const override;
  size_t encode(void* buffer, size_t bufferSize) const
      RTI_THROW((rti1516e::CouldNotEncode)) override;
  size_t encodedLength() const override;
  void decode(rti1516e::VariableLengthData const& encodedLogicalTime)
      RTI_THROW((rti1516e::InternalError, rti1516e::CouldNotDecode)) override;
  void decode(void* buffer, size_t bufferSize)
      RTI_THROW((rti1516e::InternalError, rti1516e::CouldNotDecode)) override;
  std::wstring toString() const override;
  std::wstring implementationName() const override;

 private:
  std::wstring implementation_;
  std::string bytes_;
  Fault fault_;
};

}  // namespace sc_hla_test

#endif  // SC_HLA_TEST_TIME_H
