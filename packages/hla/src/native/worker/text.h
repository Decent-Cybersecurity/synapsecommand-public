// Text the worker writes: the UTF-8 form of the RTI's wide strings, JSON string bodies and
// lowercase hex. Nothing here allocates more than its caller asked for, and nothing interprets
// the bytes it is given.
#ifndef SC_HLA_TEXT_H
#define SC_HLA_TEXT_H

#include <cstddef>
#include <string>

namespace sc_hla {

// The rti1516e API carries names as std::wstring. On the reference platform and on macOS a
// wchar_t holds one UTF-32 code unit, which is what the conversion below assumes; a platform
// with another width would need its own conversion, so it does not compile here.
static_assert(sizeof(wchar_t) == 4, "the worker converts wide strings as UTF-32");

// The number of UTF-8 bytes `text` needs, or false when one of its code units is not a
// Unicode scalar value (above U+10FFFF, or a surrogate U+D800..U+DFFF). The RTI does not
// validate the names it passes on (FACTS: OpenRTI delivers U+D800 and U+110000), and a lossy
// replacement would invent a name nobody sent, so such a string is refused (SPEC:289).
bool utf8_length(const std::wstring& text, std::size_t* bytes);

// The UTF-8 bytes of `text`. Precondition: utf8_length(text) succeeded.
std::string to_utf8(const std::wstring& text);

// Appends `utf8` as the body of a JSON string: quotation mark, reverse solidus and the control
// characters U+0000..U+001F are escaped, every other byte is copied, so valid UTF-8 stays
// valid UTF-8 and an untrusted name can never end the string or the line.
void append_json_string(std::string* out, const std::string& utf8);

// Appends the bytes as lowercase hexadecimal, two digits per byte, in order (R16).
void append_hex(std::string* out, const std::string& bytes);

// A wide string built from ASCII bytes (argument values the worker has already checked).
std::wstring widen_ascii(const std::string& ascii);

}  // namespace sc_hla

#endif  // SC_HLA_TEXT_H
