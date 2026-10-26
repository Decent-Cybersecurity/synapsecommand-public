// sc-hla-test-federate: test only, never installed.
//
//   sc-hla-test-federate --endpoint=rti://ADDRESS:PORT --federation-name=NAME --federate-name=NAME
//                        --module=FILE [--module=FILE ...]
//
// Creates the federation NAME on a real rtinode from the module files it is given (the RTI reads
// them by path), joins it under the federate name it is given, reports {"event":"ready"} on
// stdout and holds, evoking callbacks, until its stdin ends or SIGTERM arrives; then it resigns,
// destroys the federation it created and disconnects, and reports each step. The tests use it for
// what the synthetic publisher must never do: a federation from a reduced module set that lacks
// an attribute the observer resolves (A-MISSING-FOM, OPS-28 b: the set is written at test time
// from the pinned bytes), and a federate that already holds the observer's own federate name
// (A-NAME-CONFLICT). It also shows that a federation name the observer was refused is still
// free afterwards: the observer created nothing (A-NO-CREATE).
//
// Exit status 0 after the destroyed federation, 1 for an RTI failure (reported on stdout with a
// fixed label, never the RTI's text), 64 for any other argument vector.

// <memory> first, before any RTI header. Below C++17 the rti1516e headers hand out
// std::auto_ptr (RTI_UNIQUE_PTR) but never include <memory>: libc++ happens to declare it
// through other headers, libstdc++ (GCC 13, the reference compiler) does not, and the build
// fails there without this line (Linux reference run, finding F1).
#include <memory>

#include <RTI/NullFederateAmbassador.h>
#include <RTI/RTIambassador.h>
#include <RTI/RTIambassadorFactory.h>
#include <poll.h>
#include <unistd.h>

#include <cerrno>
#include <string>
#include <vector>

#include "channels.h"
#include "process.h"
#include "text.h"

namespace {

bool take(const std::string& token, const char* prefix, std::string* value) {
  const std::string p(prefix);
  if (token.compare(0, p.size(), p) != 0 || token.size() == p.size()) return false;
  *value = token.substr(p.size());
  return true;
}

void emit(const std::string& json) { sc_hla::write_all(1, json + "\n"); }

const char* label(const rti1516e::Exception& e) {
  if (dynamic_cast<const rti1516e::FederationExecutionAlreadyExists*>(&e)) {
    return "FederationExecutionAlreadyExists";
  }
  if (dynamic_cast<const rti1516e::FederateNameAlreadyInUse*>(&e)) {
    return "FederateNameAlreadyInUse";
  }
  if (dynamic_cast<const rti1516e::FederatesCurrentlyJoined*>(&e)) {
    return "FederatesCurrentlyJoined";
  }
  if (dynamic_cast<const rti1516e::CouldNotOpenFDD*>(&e)) return "CouldNotOpenFDD";
  if (dynamic_cast<const rti1516e::ErrorReadingFDD*>(&e)) return "ErrorReadingFDD";
  if (dynamic_cast<const rti1516e::InconsistentFDD*>(&e)) return "InconsistentFDD";
  if (dynamic_cast<const rti1516e::ConnectionFailed*>(&e)) return "ConnectionFailed";
  return "RTIexception";
}

// Until stdin ends (or carries anything at all) or SIGTERM: callbacks are evoked meanwhile.
void hold(rti1516e::RTIambassador& rti) {
  while (!sc_hla::stop_requested()) {
    rti.evokeMultipleCallbacks(0.0, 0.0);
    pollfd input = {0, POLLIN, 0};
    const int ready = ::poll(&input, 1, 10);
    if (ready < 0 && errno == EINTR) continue;
    if (ready != 0) return;
  }
}

}  // namespace

int main(int argc, char** argv) {
  sc_hla::clear_openrti_debug_variables();
  std::string endpoint;
  std::string federation;
  std::string federate;
  std::vector<std::wstring> modules;
  const std::vector<std::string> tokens(argv + 1, argv + argc);
  bool usable = tokens.size() >= 4 && take(tokens[0], "--endpoint=", &endpoint) &&
                take(tokens[1], "--federation-name=", &federation) &&
                take(tokens[2], "--federate-name=", &federate);
  for (std::size_t i = 3; usable && i < tokens.size(); ++i) {
    std::string module;
    usable = take(tokens[i], "--module=", &module);
    modules.push_back(sc_hla::widen_ascii(module));
  }
  if (!usable) {
    sc_hla::write_all(2, "sc-hla-test-federate: usage: see test_federate.cpp\n");
    return 64;
  }
  sc_hla::install_signal_handlers();
  rti1516e::NullFederateAmbassador ambassador;
  const std::wstring name = sc_hla::widen_ascii(federation);
  std::string stage = "connect";
  bool connected = false;
  bool created = false;
  bool joined = false;
  int status = 0;
  RTI_UNIQUE_PTR<rti1516e::RTIambassador> rti;
  try {
    rti = rti1516e::RTIambassadorFactory().createRTIambassador();
    rti->connect(ambassador, rti1516e::HLA_EVOKED, sc_hla::widen_ascii(endpoint));
    connected = true;
    stage = "create";
    rti->createFederationExecution(name, modules, L"HLAfloat64Time");
    created = true;
    emit("{\"event\":\"created\"}");
    stage = "join";
    rti->joinFederationExecution(sc_hla::widen_ascii(federate), L"SynapseCommandTestFederate",
                                 name);
    joined = true;
    emit("{\"event\":\"ready\"}");
    stage = "hold";
    hold(*rti);
    stage = "resign";
    rti->resignFederationExecution(rti1516e::NO_ACTION);
    joined = false;
    emit("{\"event\":\"resigned\"}");
    stage = "destroy";
    rti->destroyFederationExecution(name);
    created = false;
    emit("{\"event\":\"destroyed\"}");
    stage = "disconnect";
    rti->disconnect();
    connected = false;
    emit("{\"event\":\"disconnected\"}");
  } catch (const rti1516e::Exception& e) {
    std::string line = "{\"event\":\"failure\",\"reason\":";
    sc_hla::append_json_string(&line, label(e));
    line += ",\"stage\":";
    sc_hla::append_json_string(&line, stage);
    emit(line + "}");
    status = 1;
    try {
      if (joined) rti->resignFederationExecution(rti1516e::NO_ACTION);
      if (created) rti->destroyFederationExecution(name);
      if (connected) rti->disconnect();
    } catch (const rti1516e::Exception&) {
      // The failure above is the result; this is only tidying up the test's own federation.
    }
  }
  return status;
}
