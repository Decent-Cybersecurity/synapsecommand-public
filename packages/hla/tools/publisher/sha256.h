// SHA-256 (FIPS 180-4) of a byte string, for the synthetic publisher's pin check: the publisher
// hashes the very bytes it hands to the RTI, so the digest it reports is the evidence of which
// module bytes created the federation (R11, NAT-19). Written out here so that the publisher
// links nothing beyond the RTI's own libraries.
#ifndef SC_HLA_PUBLISHER_SHA256_H
#define SC_HLA_PUBLISHER_SHA256_H

#include <string>

namespace sc_hla_publisher {

// The digest of `bytes` as 64 lowercase hexadecimal digits.
std::string sha256_hex(const std::string& bytes);

}  // namespace sc_hla_publisher

#endif  // SC_HLA_PUBLISHER_SHA256_H
