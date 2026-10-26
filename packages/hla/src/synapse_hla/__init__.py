"""synapse-hla: the receive-only HLA observer of profile SC-HLA-RPR2-OBS-1, Python side.

This distribution sits beside `synapse-cdm` and is not one of its registered adapters: it keeps
sockets, files, hashing and session state out of the pure CDM package (R03). The public surface
is fixed by lead ruling CR-L02, and it is complete: nothing outside that list is re-exported here.
"""

from synapse_hla.capture import verify_capture
from synapse_hla.codec import decode_attribute
from synapse_hla.config import validate_config
from synapse_hla.errors import HlaError
from synapse_hla.projector import project_state
from synapse_hla.reducer import reduce_frame
from synapse_hla.replay import replay

__version__ = "1.0.0"

#: The one profile this release implements.
PROFILE = "SC-HLA-RPR2-OBS-1"

__all__ = ["HlaError", "PROFILE", "__version__", "decode_attribute", "project_state",
           "reduce_frame", "replay", "validate_config", "verify_capture"]
