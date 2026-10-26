// sc-hla-federate: the native worker of synapse-hla (R03). The Python host starts it with an
// argument vector, reads worker frames from its stdout and status records from fd 3, and stops
// it with SIGTERM (SPEC:273-279). See observer.h for what it does in between.
#include <string>
#include <vector>

#include "channels.h"
#include "observer.h"
#include "process.h"
#include "text.h"

int main(int argc, char** argv) {
  // NAV-01: before anything else, so that no OpenRTI code ever sees them.
  sc_hla::clear_openrti_debug_variables();

  const std::vector<std::string> tokens(argv + 1, argv + argc);
  sc_hla::Options options;
  switch (sc_hla::parse_arguments(tokens, &options)) {
    case sc_hla::Invocation::kVersion:
      return sc_hla::write_all(1, sc_hla::kVersionLine) ? sc_hla::kExitStopped
                                                         : sc_hla::kExitFailure;
    case sc_hla::Invocation::kUsage:
      sc_hla::write_all(2, "sc-hla-federate: usage: sc-hla-federate --version | "
                           "--endpoint=rti://ADDRESS:PORT --federation-name=NAME "
                           "--federate-name=NAME\n");
      return sc_hla::kExitUsage;
    case sc_hla::Invocation::kRun:
      break;
  }
  // NAT-09: no status channel, no RTI call.
  if (!sc_hla::status_channel_present()) {
    sc_hla::write_all(2, "sc-hla-federate: file descriptor 3 is not the status pipe\n");
    return sc_hla::kExitStatusChannel;
  }
  sc_hla::install_signal_handlers();
  const sc_hla::ParentWatch parent;
  sc_hla::StatusChannel status(3);
  sc_hla::FrameQueue frames(1);
  frames.start();
  sc_hla::Observer observer(options, status, frames, parent);
  sc_hla::FactorySource source;
  // The configured endpoint is the local settings designator, verbatim (R10).
  return observer.run(source, sc_hla::widen_ascii(options.endpoint));
}
