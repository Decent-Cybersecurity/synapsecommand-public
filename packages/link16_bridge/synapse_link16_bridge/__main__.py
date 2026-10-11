"""`python -m synapse_link16_bridge` runs the same `main` as the `synapse-link16-bridge` script."""
import sys

from synapse_link16_bridge.cli import main

sys.exit(main())
