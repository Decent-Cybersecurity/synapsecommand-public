"""A loopback TCP relay that can break its connections on demand (test only, never product code).

    python rti_proxy.py UPSTREAM_PORT MODE        (MODE: rst or fin)

It listens on 127.0.0.1 on a port the kernel chooses and prints `{"port": N}` as its first line on
stdout; every connection it accepts is relayed both ways to 127.0.0.1:UPSTREAM_PORT. On SIGUSR1 it
breaks every connection relayed so far, then prints `{"broken": n}`: with MODE rst the client's
side is closed with SO_LINGER(1, 0), which sends a TCP reset (NAT-03: OpenRTI calls connectionLost
for it); with fin both sides are closed normally, which sends FIN (NAV-02: OpenRTI calls no
connectionLost but removes every object it knows). Connections accepted later are relayed as
before (the worker's reconnect goes through it again). SIGTERM ends it. It is the scout's
`rst_proxy.py` (scratch/native) made deterministic: the break happens when the test says, not on
a timer.
"""

import errno
import json
import os
import signal
import socket
import struct
import sys
import threading

UPSTREAM = int(sys.argv[1])
MODE = sys.argv[2]
assert MODE in ("rst", "fin")
LOOPBACK = "127.0.0.1"

pairs: list[tuple[socket.socket, socket.socket]] = []
lock = threading.Lock()
wake_read, wake_write = os.pipe()


def pump(source: socket.socket, target: socket.socket) -> None:
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass


def accept(server: socket.socket) -> None:
    while True:
        try:
            client, _ = server.accept()
        except OSError:
            return
        upstream = socket.create_connection((LOOPBACK, UPSTREAM))
        with lock:
            pairs.append((client, upstream))
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=pump, args=(a, b), daemon=True).start()


def main() -> None:
    server = socket.socket()
    server.bind((LOOPBACK, 0))
    server.listen(16)
    print(json.dumps({"port": server.getsockname()[1]}), flush=True)
    threading.Thread(target=accept, args=(server,), daemon=True).start()
    signal.signal(signal.SIGUSR1, lambda *_: os.write(wake_write, b"b"))
    signal.signal(signal.SIGTERM, lambda *_: os.write(wake_write, b"t"))
    while True:
        command = os.read(wake_read, 1)
        if command == b"t":
            return
        with lock:
            broken = list(pairs)
            pairs.clear()
        for client, upstream in broken:
            if MODE == "rst":
                client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            # Each socket has a relay thread blocked in recv. On Linux a close() under that call
            # neither wakes it nor ends the connection: no reset and no FIN leave until data
            # arrives (the Linux reference run's finding F2). shutdown() wakes the thread
            # first; for rst the client side is shut for reading only, which sends nothing, so
            # the close below still sends the reset the linger option asks for. macOS behaves
            # the same with or without it.
            for sock, how in ((client, socket.SHUT_RD if MODE == "rst" else socket.SHUT_RDWR),
                              (upstream, socket.SHUT_RDWR)):
                try:
                    sock.shutdown(how)
                except OSError as error:
                    # The peer may already have gone; that is the only refusal to tolerate.
                    if error.errno != errno.ENOTCONN:
                        raise
            client.close()
            upstream.close()
        print(json.dumps({"broken": len(broken)}), flush=True)


if __name__ == "__main__":
    main()
