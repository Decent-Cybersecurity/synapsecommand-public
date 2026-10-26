# Licences the synapse-hla release carries

synapse-hla itself is licensed under Apache-2.0: `../LICENSE` and `../NOTICE` are byte copies
of the repository's own files.

## OpenRTI (the RTI the native worker and the synthetic publisher link)

The native part of this release is built against OpenRTI commit
`814a210978b7faafd65affbe70a2e25679921b23`, from the pinned source archive
`openrti-814a210.tar.gz` (SHA-256
`16de11df983c8074feed252a7de1fc7c05c4e9520c050df6bcff8b3a899adb80`). The archive is not in
this repository; the release evidence kit ships it alongside the release, so the complete
corresponding source of the linked library is always available beside the built runtime.

The archive's `LICENSE` offers OpenRTI under the GNU Lesser General Public License version 2.1,
version 3.0, or the Mozilla Public License version 2.0, at the recipient's choice; the per-file
headers of its sources say LGPL-2.1-or-later.

**Elected licence: this release uses OpenRTI under the GNU Lesser General Public License,
version 2.1 or (at your option) any later version (LGPL-2.1-or-later). OpenRTI is linked
dynamically, as shared libraries (`libOpenRTI`, `librti1516e`, `libfedtime1516e`), and is not
modified; the pinned source archive is shipped alongside.**

The texts, verbatim from the pinned archive (NAT-14), are in `openrti/`:

| File here | File in the archive | SHA-256 |
|---|---|---|
| `openrti/LICENSE` | `LICENSE` (the licence offer) | `b7d81056ce95e13732e22f7312b7dd2ceddd5f2456711f445834443bd843e3f0` |
| `openrti/lgpl-2.1` | `lgpl-2.1.txt` | `dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551` |
| `openrti/lgpl-3` | `lgpl-3.txt` | `da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768` |
| `openrti/mpl-2.0` | `mpl-2.0.txt` | `fab3dd6bdab226f1c08630b1dd917e11fcb4ec5e1e020e2c16f83a0a13863e85` |

The repository ignores every `*.txt` file at any depth, so the texts are kept here without that
suffix; their bytes are the archive's, which a test holds them to. `cmake --install` of
`src/native` installs this directory beside the native runtime it installs.

OpenRTI's bundled expat sources (`src/OpenRTI/xml/`, with their `COPYING-expat`) are compiled
only when no system expat is found. Every build of this release so far linked the system expat
and zlib instead (macOS `/usr/lib/libexpat.1.dylib` and `/usr/lib/libz.1.dylib`; Ubuntu
`libexpat.so.1` and `libz.so.1` from the `libexpat1` and `zlib1g` packages), so `COPYING-expat`
is not carried; the SBOM in `../locks/` records the linked libraries and their licences (expat:
MIT; zlib: the zlib licence).

## Attributions

- The rti1516e API headers the native code is compiled against carry the IEEE's permission
  notice; as it requires: "Reprinted with permission from IEEE 1516.1(TM)-2010".
- The five RPR FOM 2.0 modules the observer checks and the synthetic publisher loads are not in
  this repository (they are found through `SYNAPSE_HLA_FOM_DIR` and held to the SHA-256 pins of
  `src/synapse_hla/pins.json`). They come from the immutable public repository copy at commit
  `9627bab695779a659800c7921af5d65c0f5d0e00`, not from a direct download from SISO, and keep
  their SISO identification. Their embedded SISO notices are preserved unmodified, and as they
  require: "Reprinted with permission from SISO Inc." The full standards prose of
  SISO-STD-001-2015 and SISO-STD-001.1-2015 is not redistributed, nor is the IEEE standard's.
