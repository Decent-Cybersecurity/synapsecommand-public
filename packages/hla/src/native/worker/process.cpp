#include "process.h"

#include <signal.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <cstdlib>

namespace sc_hla {

const char kVersionLine[] =
    "{\"name\":\"sc-hla-federate\",\"profile\":\"SC-HLA-RPR2-OBS-1\",\"version\":\"1.0.0\"}\n";

namespace {

static_assert(ATOMIC_BOOL_LOCK_FREE == 2, "the stop flag must be safe to set in a handler");
std::atomic<bool> g_stop(false);

extern "C" void on_terminate(int) { g_stop.store(true); }

bool name_character(char c) {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
         c == '.' || c == '_' || c == '-';
}

// config.schema.json: ^[A-Za-z0-9._-]{1,64}$
bool valid_name(const std::string& value) {
  if (value.empty() || value.size() > 64) return false;
  for (char c : value) {
    if (!name_character(c)) return false;
  }
  return true;
}

// config.schema.json: ^rti://[0-9.]+:[0-9]+$ with at most 64 characters. The semantic checks
// (octets, port range) are the host's; this only keeps the token what it claims to be.
bool valid_endpoint(const std::string& value) {
  static const std::string kScheme = "rti://";
  if (value.size() > 64 || value.compare(0, kScheme.size(), kScheme) != 0) return false;
  const std::string rest = value.substr(kScheme.size());
  const std::string::size_type colon = rest.rfind(':');
  if (colon == std::string::npos || colon == 0 || colon + 1 == rest.size()) return false;
  for (std::string::size_type i = 0; i < rest.size(); ++i) {
    const char c = rest[i];
    if (i == colon) continue;
    if (c >= '0' && c <= '9') continue;
    if (c == '.' && i < colon) continue;
    return false;
  }
  return true;
}

bool take(const std::string& token, const std::string& prefix, std::string* value) {
  if (token.compare(0, prefix.size(), prefix) != 0) return false;
  *value = token.substr(prefix.size());
  return true;
}

}  // namespace

Invocation parse_arguments(const std::vector<std::string>& tokens, Options* options) {
  if (tokens.size() == 1 && tokens[0] == "--version") return Invocation::kVersion;
  if (tokens.size() != 3) return Invocation::kUsage;
  Options parsed;
  if (!take(tokens[0], "--endpoint=", &parsed.endpoint) ||
      !take(tokens[1], "--federation-name=", &parsed.federation_name) ||
      !take(tokens[2], "--federate-name=", &parsed.federate_name)) {
    return Invocation::kUsage;
  }
  if (!valid_endpoint(parsed.endpoint) || !valid_name(parsed.federation_name) ||
      !valid_name(parsed.federate_name)) {
    return Invocation::kUsage;
  }
  *options = parsed;
  return Invocation::kRun;
}

void clear_openrti_debug_variables() {
  ::unsetenv("OPENRTI_DEBUG_PRIORITY");
  ::unsetenv("OPENRTI_DEBUG_CATEGORY");
}

bool status_channel_present() {
  struct stat info;
  if (::fstat(3, &info) != 0) return false;
  return S_ISFIFO(info.st_mode);
}

void install_signal_handlers() {
  struct sigaction ignore;
  ignore.sa_handler = SIG_IGN;
  sigemptyset(&ignore.sa_mask);
  ignore.sa_flags = 0;
  ::sigaction(SIGPIPE, &ignore, nullptr);
  struct sigaction stop;
  stop.sa_handler = on_terminate;
  sigemptyset(&stop.sa_mask);
  stop.sa_flags = SA_RESTART;
  ::sigaction(SIGTERM, &stop, nullptr);
}

bool stop_requested() { return g_stop.load(); }

std::uint64_t monotonic_ns() {
  struct timespec now;
  ::clock_gettime(CLOCK_MONOTONIC, &now);
  return static_cast<std::uint64_t>(now.tv_sec) * 1000000000u +
         static_cast<std::uint64_t>(now.tv_nsec);
}

void pause_for(std::int64_t nanoseconds) {
  struct timespec wait;
  wait.tv_sec = static_cast<time_t>(nanoseconds / 1000000000);
  wait.tv_nsec = static_cast<long>(nanoseconds % 1000000000);
  // An interrupted pause is a shorter pause: the loop looks at the stop flag next.
  ::nanosleep(&wait, nullptr);
}

ParentWatch::ParentWatch() : parent_(::getppid()) {}

ParentWatch::ParentWatch(pid_t parent) : parent_(parent) {}

bool ParentWatch::gone() const { return changed(parent_, ::getppid()); }

bool ParentWatch::changed(pid_t recorded, pid_t now) { return now != recorded; }

}  // namespace sc_hla
