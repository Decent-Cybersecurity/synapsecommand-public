#include "sha256.h"

#include <cstddef>
#include <cstdint>

namespace sc_hla_publisher {

namespace {

// FIPS 180-4 section 4.2.2: the first 32 bits of the fractional parts of the cube roots of the
// first 64 primes.
const std::uint32_t kRound[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u,
    0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu,
    0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu,
    0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
    0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u,
    0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u,
    0xc67178f2u};

std::uint32_t rotate_right(std::uint32_t value, unsigned count) {
  return (value >> count) | (value << (32u - count));
}

void compress(std::uint32_t state[8], const unsigned char block[64]) {
  std::uint32_t w[64];
  for (std::size_t i = 0; i < 16; ++i) {
    w[i] = (static_cast<std::uint32_t>(block[4 * i]) << 24) |
           (static_cast<std::uint32_t>(block[4 * i + 1]) << 16) |
           (static_cast<std::uint32_t>(block[4 * i + 2]) << 8) |
           static_cast<std::uint32_t>(block[4 * i + 3]);
  }
  for (std::size_t i = 16; i < 64; ++i) {
    const std::uint32_t s0 =
        rotate_right(w[i - 15], 7) ^ rotate_right(w[i - 15], 18) ^ (w[i - 15] >> 3);
    const std::uint32_t s1 =
        rotate_right(w[i - 2], 17) ^ rotate_right(w[i - 2], 19) ^ (w[i - 2] >> 10);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  std::uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
  std::uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
  for (std::size_t i = 0; i < 64; ++i) {
    const std::uint32_t s1 = rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
    const std::uint32_t choice = (e & f) ^ (~e & g);
    const std::uint32_t t1 = h + s1 + choice + kRound[i] + w[i];
    const std::uint32_t s0 = rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
    const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
    const std::uint32_t t2 = s0 + majority;
    h = g;
    g = f;
    f = e;
    e = d + t1;
    d = c;
    c = b;
    b = a;
    a = t1 + t2;
  }
  state[0] += a;
  state[1] += b;
  state[2] += c;
  state[3] += d;
  state[4] += e;
  state[5] += f;
  state[6] += g;
  state[7] += h;
}

}  // namespace

std::string sha256_hex(const std::string& bytes) {
  // FIPS 180-4 section 5.3.3: the initial hash value.
  std::uint32_t state[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
                            0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
  // Section 5.1.1: the message, a single 1 bit, zeros to 56 bytes modulo 64, and its length in
  // bits as a 64-bit big-endian number.
  std::string padded = bytes;
  padded.push_back(static_cast<char>(0x80));
  while (padded.size() % 64 != 56) padded.push_back('\0');
  const std::uint64_t bits = static_cast<std::uint64_t>(bytes.size()) * 8u;
  for (int shift = 56; shift >= 0; shift -= 8) {
    padded.push_back(static_cast<char>((bits >> shift) & 0xFFu));
  }
  unsigned char block[64];
  for (std::size_t offset = 0; offset < padded.size(); offset += 64) {
    for (std::size_t i = 0; i < 64; ++i) {
      block[i] = static_cast<unsigned char>(padded[offset + i]);
    }
    compress(state, block);
  }
  static const char kDigits[] = "0123456789abcdef";
  std::string out;
  for (std::uint32_t word : state) {
    for (int shift = 28; shift >= 0; shift -= 4) {
      out.push_back(kDigits[(word >> shift) & 0xFu]);
    }
  }
  return out;
}

}  // namespace sc_hla_publisher
