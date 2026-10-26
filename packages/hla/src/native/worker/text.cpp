#include "text.h"

#include <cstdint>

namespace sc_hla {

namespace {

// The code point of one UTF-32 code unit, or a value above U+10FFFF for a negative wchar_t
// (wchar_t is signed on both platforms, and a negative unit is no code point either).
std::uint32_t code_point(wchar_t unit) {
  return static_cast<std::uint32_t>(unit);
}

bool scalar_value(std::uint32_t cp) {
  return cp <= 0x10FFFFu && (cp < 0xD800u || cp > 0xDFFFu);
}

std::size_t encoded_length(std::uint32_t cp) {
  if (cp < 0x80u) return 1;
  if (cp < 0x800u) return 2;
  if (cp < 0x10000u) return 3;
  return 4;
}

const char kHexDigits[] = "0123456789abcdef";

}  // namespace

bool utf8_length(const std::wstring& text, std::size_t* bytes) {
  std::size_t total = 0;
  for (wchar_t unit : text) {
    const std::uint32_t cp = code_point(unit);
    if (!scalar_value(cp)) return false;
    total += encoded_length(cp);
  }
  *bytes = total;
  return true;
}

std::string to_utf8(const std::wstring& text) {
  std::string out;
  for (wchar_t unit : text) {
    const std::uint32_t cp = code_point(unit);
    if (cp < 0x80u) {
      out.push_back(static_cast<char>(cp));
    } else if (cp < 0x800u) {
      out.push_back(static_cast<char>(0xC0u | (cp >> 6)));
      out.push_back(static_cast<char>(0x80u | (cp & 0x3Fu)));
    } else if (cp < 0x10000u) {
      out.push_back(static_cast<char>(0xE0u | (cp >> 12)));
      out.push_back(static_cast<char>(0x80u | ((cp >> 6) & 0x3Fu)));
      out.push_back(static_cast<char>(0x80u | (cp & 0x3Fu)));
    } else {
      out.push_back(static_cast<char>(0xF0u | (cp >> 18)));
      out.push_back(static_cast<char>(0x80u | ((cp >> 12) & 0x3Fu)));
      out.push_back(static_cast<char>(0x80u | ((cp >> 6) & 0x3Fu)));
      out.push_back(static_cast<char>(0x80u | (cp & 0x3Fu)));
    }
  }
  return out;
}

void append_json_string(std::string* out, const std::string& utf8) {
  out->push_back('"');
  for (char c : utf8) {
    const unsigned char byte = static_cast<unsigned char>(c);
    if (byte == '"' || byte == '\\') {
      out->push_back('\\');
      out->push_back(c);
    } else if (byte < 0x20u) {
      out->append("\\u00");
      out->push_back(kHexDigits[byte >> 4]);
      out->push_back(kHexDigits[byte & 0x0Fu]);
    } else {
      out->push_back(c);
    }
  }
  out->push_back('"');
}

void append_hex(std::string* out, const std::string& bytes) {
  for (char c : bytes) {
    const unsigned char byte = static_cast<unsigned char>(c);
    out->push_back(kHexDigits[byte >> 4]);
    out->push_back(kHexDigits[byte & 0x0Fu]);
  }
}

std::wstring widen_ascii(const std::string& ascii) {
  std::wstring out;
  for (char c : ascii) out.push_back(static_cast<wchar_t>(static_cast<unsigned char>(c)));
  return out;
}

}  // namespace sc_hla
