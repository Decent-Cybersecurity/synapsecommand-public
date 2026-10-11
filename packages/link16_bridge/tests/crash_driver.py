"""The process-level crash driver (R01, R02): a bridge in its own process whose crash point calls
`os._exit(137)`, so the SQLite file is left as a real process death leaves it.

    python crash_driver.py CONFIG CREDENTIAL POINT HOLDER

The clock is the tests' fixed instant, the sink a memory sink; the process prints nothing and
its exit status is the reading (137 when the crash point was reached)."""
import random
import sys

from helpers import T0
from synapse_link16_bridge import faults
from synapse_link16_bridge.bridge import Bridge, MemorySink
from synapse_link16_bridge.clock import ManualClock, RecordingSleeper
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.gateway.client import GatewayClient


def main() -> int:
    config_path, credential, point, holder = sys.argv[1:5]
    config = BridgeConfig.load(config_path)
    client = GatewayClient(config.gateway_base_url, credential, connect_timeout=2,
                           request_deadline=5)
    bridge = Bridge(config, sink=MemorySink(config.cdm_schema_version), client=client,
                    clock=ManualClock(T0), sleeper=RecordingSleeper(), rng=random.Random(1),
                    faults=faults.CrashPoints({point}, exit_process=True), holder=holder)
    if bridge.start() != "READY":
        return 3
    bridge.run_once()
    bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
