"""synapse-link16-bridge: the runtime between an SC Link16 Gateway 1.0.0 API and the CDM.

WHAT IT IS
----------
The runtime half of the SynapseCommand JREAP C and Link 16 engineering handoff 1.0.0: it reads
report batches from a gateway over the gateway API, checks every record against its configured
channel, hands each report's octets to the `link16_gateway` adapter of synapse-cdm, keeps durable
state (dispositions, identities, history, current state, freshness, lifecycle, an outbox with
stable event keys, export jobs and an audit trail) in one SQLite file per channel, delivers the
CDM objects to a sink at least once, and exports a CDM Entity to a gateway only when its explicit
deployment configuration permits it. It ships a synthetic provider and a loopback HTTP server for
that provider, so every path can run without a native gateway.

WHAT IT IS NOT
--------------
It is not JREAP C and not Link 16: it parses no native frame, message or J-series word, holds no
native socket, and claims no native interoperability, radio participation, encryption, anti-jam
behaviour, spectrum authorisation, national accreditation or certification of any kind. The native
provider is a boundary (`synapse_link16_bridge.native`) that refuses activation with
BLOCKED_EXTERNAL_EVIDENCE until a normative profile, independent byte vectors and a witnessed peer
test exist, and never falls back to the synthetic provider. It applies only exact-match channel,
label-set and export rules that its configuration names: it is not a classification-policy engine
and not a cross-domain guard. It makes no weapons, engagement or command decision.
"""
from synapse_link16_bridge._version import __version__

__all__ = ["__version__"]
