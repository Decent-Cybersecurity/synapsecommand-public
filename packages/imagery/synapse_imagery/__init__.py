"""synapse-imagery: the host of the `stanag4545` adapter of synapse-cdm.

WHAT IT IS
----------
The host half of the SynapseCommand STANAG 4545 (NSIF/NITF) imagery adapter under the
SC4545-CORE-1 engineering profile. It receives a container into private staging, hashes the
staged octets, runs the adapter's inventory and translation in an isolated worker process, asks a
policy engine whether the material may be released, keeps the immutable original in a local asset
store (or in quarantine when policy blocks it), commits a durable host record and only then
publishes the CDM objects. Storage and policy are interfaces; a local filesystem store, a default
policy gate, a label-lattice interface and test fakes ship with it.

WHAT IT IS NOT
--------------
It is not a codec: it decodes only the native uncompressed cell the adapter decodes, and every
compressed or masked cell is disabled. It is not an HTTP service, a tile service or a URL signer;
it opens no socket. Its policy code is an interface, a test fake, a default gate that admits only
material the adapter assesses as declared unclassified, and a lattice interface that refuses every
combination it cannot decide: it is not a classification-policy engine and not a cross-domain
guard. It carries no certification or accreditation of any kind.
"""

from synapse_imagery._version import __version__

__all__ = ["__version__"]
