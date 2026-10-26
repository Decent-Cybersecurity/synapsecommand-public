// What the worker process is told and what it checks before it touches the RTI: its argument
// vector, its status channel, its signals, its clock and its parent.
#ifndef SC_HLA_PROCESS_H
#define SC_HLA_PROCESS_H

#include <sys/types.h>

#include <cstdint>
#include <string>
#include <vector>

namespace sc_hla {

// What `sc-hla-federate --version` prints, exactly (CR-R5-02: host.VERSION_LINE).
extern const char kVersionLine[];

// The worker's exit statuses. The host reads only 0 (after its orderly stop) and "not 0"; the
// distinct values are for a person reading a log.
enum ExitStatus : int {
  kExitStopped = 0,         // the orderly stop completed, or --version
  kExitFailure = 1,         // a terminal condition was reported on fd 3
  kExitUsage = 64,          // the argument vector is not the three tokens of OPS-08
  kExitStatusChannel = 70,  // fd 3 is not open, or not a pipe (NAT-09), checked before any RTI call
  kExitChannelLost = 71,    // stdout or fd 3 broke (EPIPE): nobody is left to report to
  kExitParentGone = 72,     // the host that started the worker has gone
};

// The three values of OPS-08's argument tokens, as validated ASCII.
struct Options {
  std::string endpoint;
  std::string federation_name;
  std::string federate_name;
};

enum class Invocation { kRun, kVersion, kUsage };

// `tokens` are the arguments after the program name. Exactly `--version`, or exactly
// `--endpoint=V`, `--federation-name=V`, `--federate-name=V` in that order, each value matching
// the configuration schema's pattern (an endpoint `rti://<digits and dots>:<digits>` of at most
// 64 characters, names of 1 to 64 characters from A-Z a-z 0-9 . _ -). Anything else is kUsage:
// the worker refuses an argument it does not know rather than guess (OPS-08).
Invocation parse_arguments(const std::vector<std::string>& tokens, Options* options);

// NAV-01: OpenRTI writes its log to stdout when these are set, which would corrupt the frame
// channel. Called first thing in main, before anything else can read them.
void clear_openrti_debug_variables();

// NAT-09: fd 3 is open and a pipe (S_ISFIFO).
bool status_channel_present();

// SIGPIPE ignored (a broken channel is an EPIPE the worker handles), SIGTERM only sets a flag
// (SPEC:277: the event loop does the RTI cleanup outside the handler).
void install_signal_handlers();
bool stop_requested();

// CLOCK_MONOTONIC in nanoseconds (SPEC:275, OPV-02): the clock the host computes elapsed time
// with.
std::uint64_t monotonic_ns();

// Sleeps `nanoseconds`, or less when a signal arrives.
void pause_for(std::int64_t nanoseconds);

// The host is the worker's parent. When it dies the worker is re-parented, and nobody reads
// its channels or will stop it (CR-R6-F2 is the host's own half of this). The worker records
// its parent at start and compares getppid() with it: a different pid, whether init (1) or a
// subreaper, means the parent has gone.
class ParentWatch {
 public:
  ParentWatch();
  explicit ParentWatch(pid_t parent);
  bool gone() const;
  static bool changed(pid_t recorded, pid_t now);

 private:
  pid_t parent_;
};

}  // namespace sc_hla

#endif  // SC_HLA_PROCESS_H
