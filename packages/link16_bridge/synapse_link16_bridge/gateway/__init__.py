"""The gateway side of the API: the synthetic provider, its synthetic wrapper, the loopback HTTP
server that serves the provider, and the client the bridge talks to a gateway with.

Synthetic only. Nothing here reads, writes or claims native JREAP C or Link 16 traffic: the
native provider is a boundary (`synapse_link16_bridge.native`) that refuses with
BLOCKED_EXTERNAL_EVIDENCE."""
