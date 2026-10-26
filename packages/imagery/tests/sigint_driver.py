"""The interrupt driver: one `sc-imagery` command in its own process, interrupted at a named
point exactly as an operator's Ctrl-C would interrupt it.

    python sigint_driver.py POINT ARGUMENT...

It runs `synapse_imagery.cli.main(ARGUMENTS, _fault=f)`, where `f` sends SIGINT to this
process when the command reaches POINT (`staged` in an ingest, `derivative_temp_written` in a
preview, `export_temp_written` in an export, `replay_part_written` in a replay), and exits with
the status `main` returns. A process started in the background of a non-interactive shell
inherits SIGINT ignored; the driver restores Python's own handler first, so the command meets the
interrupt an operator's terminal delivers."""

import os
import signal
import sys

from synapse_imagery.cli import main


def run() -> int:
    point, arguments = sys.argv[1], sys.argv[2:]
    signal.signal(signal.SIGINT, signal.default_int_handler)

    def fault(reached: str) -> None:
        if reached == point:
            os.kill(os.getpid(), signal.SIGINT)

    return main(arguments, _fault=fault)


if __name__ == "__main__":
    sys.exit(run())
