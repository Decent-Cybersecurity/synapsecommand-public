"""The STANAG 4545 imagery adapter's handoff evidence: the filled acceptance table
`docs/stanag4545-acceptance.csv`, the implementation record `docs/stanag4545-implementation.md`
and the corpus manifest `docs/stanag4545-corpus.json`, held to their own rules and to the tree.

Every expectation is a literal: the kit's table header, the dispositions of the rows that are not
implemented, the SHA-256 of each of the kit's requirement summaries (never the text, so a subject
in this repository's words can be told from a copied one), the digests of the kit's files, the
permitted claim sentence, the record's section headings and the handoff list. Words this module
bans from other files are built by concatenation, so it does not match its own rules.
Repository-bound: the three records and the published manifest live at the repository root, and
the tracked set comes from git, none of which an installed wheel carries.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import pathlib
import re
import subprocess

import pytest

import synapse_cdm
from synapse_cdm.adapters import nsif_codec as nc
from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter
from tests.test_cdm_prose_counts import ROSTER_COUNT, ROSTER_FLOOR, stated

REPO = pathlib.Path(__file__).resolve().parents[1]
RECORD = REPO / "docs" / "stanag4545-implementation.md"
TABLE = REPO / "docs" / "stanag4545-acceptance.csv"
CORPUS = REPO / "docs" / "stanag4545-corpus.json"
MANIFEST = REPO / "manifests" / "stanag4545.json"
PARSER_SAFETY = REPO / "docs" / "docs" / "security" / "parser-safety.mdx"
FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "stanag4545"
FIXTURE_PREFIX = "packages/cdm/synapse_cdm/fixtures/stanag4545/"

HEADER = "requirement_id,requirement_summary,status,implementation,tests,evidence,reviewer"
STATUSES = ("implemented", "not_claimed", "gate_open", "maintainer_action")

#: Every row that is not `implemented`, with its status: a disposition changes only by an edit here.
NOT_IMPLEMENTED = {
    "REQ-005": "not_claimed",
    "REQ-008": "maintainer_action",
    "REQ-032": "not_claimed",
    "REQ-036": "not_claimed",
    "REQ-039": "not_claimed",
    "REQ-046": "gate_open",
    "REQ-047": "not_claimed",
    "REQ-048": "not_claimed",
    "REQ-055": "not_claimed",
    "REQ-075": "gate_open",
    "REQ-084": "not_claimed",
    "REQ-085": "maintainer_action",
    "REQ-087": "maintainer_action",
    "REQ-088": "maintainer_action",
    "REQ-090": "maintainer_action",
    "REQ-091": "maintainer_action",
    "REQ-096": "gate_open",
    "REQ-097": "gate_open",
    "REQ-098": "maintainer_action",
    "REQ-100": "maintainer_action",
}

#: The SHA-256 of the kit's `requirement_summary` of REQ-001 ... REQ-100, in order.
KIT_SUMMARY_SHA256 = (
    "39f2995bd9487cfc9b35a6e1bece7472f87754d4a42a91a34aefc2fcb7018fa5",
    "ce954072e8a29330eb7014617c7e69bd23fc6af02330e6565b13618891e4d478",
    "aa2f22efcfa04f8c80d64cdb76b08c705db2b44bb2b8f08a6d52f9469f001046",
    "ead4c39aae3360e73320dc7976044459a810af19c76e3ba9a4b785e0a035c64a",
    "d924740e227ceb094870c4544f8a7c3885f91610eb1be30a4f7db8dfc45c333c",
    "77a5e3fff1a5d6c4a80b05a78f27ae762db7cef5473e5a356da0985c1cf2246a",
    "b44306e28e16888749360c458b6beabb3bdddefaf2c3165fec95b532193833a7",
    "2cd9f92f00d2fb7a74f6e6fa6775aa450bd5a35e76f47d442fabc039d6c95baa",
    "d114a154aa08098f50d65ac0dab02d79710248a7cbf33ff901c1203e3b40e72f",
    "01b47d9f64adc792e88279ae6dc91bf999f9918e28e9f7ef15757a312d62b12a",
    "34f58c252504b25f9c4ecc4e596ed0e1625cd3b0cd8fb118bac12bb012e54da7",
    "1811caade76c63f944d9ff4e5ec5ec6b96d15adb38d9395eeb88c2e46479e08b",
    "f5acf1c087d9aa3f1c426ba5d0d4c27aa8a47ad3214e10b8057ff364c5c30c17",
    "5e640a53e4bb731ab8204450bf83e62b5bb331c9a4640bee6acb57acbf966a2e",
    "a954e9d0b3c1b0f259b321df34f34cdd2bf8d76818df2dd66aa5e33c0723eab7",
    "8d33ff21dfca0263623ec0281daed89ed2165dc62f3a059db8aaa2fce4584498",
    "6f37cbe500b76c31ffa4d651540284a54ecd3999bd3ec424d9f8a2e971b67718",
    "e14a708483f7b74d1b0d56398368cc7dca36a7dbae062be992e35d6608d92679",
    "7f133a4678a2af93a7a97ca87c022357a6a53420c9d219cdec5b9da2209a3113",
    "b694f2552f20d3380b745a87bcc64abbd756f69be31130bdb474109533f70603",
    "2fe3b5e241113edef74bc4bdfa54a31bb820120bd8a7e31defbbeaee37b8c683",
    "d7267c05dba12388e1372421dee88c87fb9c92909b772a4b3d06ff411e1fa112",
    "e32f174f963cbe674751c10188aa11a61e5f4540ab2ab6e9d0fa709463c0d291",
    "d240abf1dd2ab6b4a4a666bedf5415c4daa96dc94dfae9c2cd25e817396b91d7",
    "9dc2f333566599cb5c6f326eb66ace0a7305c382eae81b5699ebb22a0b93dae8",
    "4e47a85402ab733b118d6f79b19a581dea70da309224e5f1813acf6857c548d6",
    "5a8e32e0b3d1c8199294d6a349673c164ac162aa409768ff2dfd5e7941caf239",
    "eaf1077ef4f7230014e4d20e72711956d368b6e3b5a1068261544a0a65a7c051",
    "94fa0feea3d26829ba4247364cd3daf25ab3076fcca947c4cc835c02c13c87f8",
    "0eb0adc7930107fa3cf7b6a978d67878107e904fc3c659f3eaeb46da46d29a8c",
    "2dc915664f9a7d75a66583da13a7b06a4db699f6fbfb79a4f361b8c52a16e3ab",
    "d1e31b676919b291a08950a9cf3cd8d533ac5506856df01fb531d85ab8e4e23b",
    "0b56934f334102b4df40c3ee83145713c29ffe9d8ad322e1de272fc98ca7f5c0",
    "ae6951bafa0cc8f6751b752de8491b70c7c17f93661450dc3d26827d4918c513",
    "7110366b4a32f2de83842fef0eae7e595fd212d6e0d148e0ba37a1f179769ae0",
    "7d90e0f7353e26f482029c7fd8aa85dfef17301cd15d89d8b9549007cbcc44f3",
    "2ba6d6355535efef9bf300bdf95d4093af202d5981de9e977c3ac82d309eceb4",
    "eff95645b2911c15128cdd8961ac575971fe9277b2821c2b833dcca75c58ad00",
    "46a079c7eac2960417c788b0d9e369a6cbbe171c59bbd0d8ca03e7e99fa1ed11",
    "8e8afb1e2b0310c6ce0d111bca62bd539b28071c9dcb6e3916e7641a518af4c1",
    "a10f95e1be3fb09ed9ecf6c4f5dbc11a6546fe11136e92e5f963e1e4f688bd62",
    "6ab3dc41ab2d6bd155f49e32fb154f890328f6eed6efe2bb92b7e456c6ac6c67",
    "d7eae615e374c30871368e6e2cb764a94d6dda2bb3769b5d334c0bf458fffa54",
    "2b70d830e603bebe18c6ebe5d1e0ce3825a4f0b922ea615d943f73d0279eb79b",
    "a7a1f049771a18a72b72b29a271bcf086bf445f75d7a5fa06fcca5081943dc07",
    "15842906b0e9e5ee64d965c4b00c5e8e1770d7a376ba7456187070bd01055e91",
    "bef2dcaa0b0a0055ede83656e68697efe949f949a889880f8ad89e4634f26e77",
    "23b5bfd029f43808761918a17b7bdd414bd9facaa0a660f90b98331331368169",
    "1845bb2879eee140b57e80c81bb7d9b3364bb837d9a56cfbe9544e22ce6c9f89",
    "8b33fa6e24e7bbff8c71550b050c9e3ee778125612b8830ad2203d654e7cf82b",
    "73e61d240d0f8dd9b63abbd5cee3c16e52e68f5994d042f0b0e55cb0cd5c55d8",
    "3ad3469578f4aad7dff9fbfce967099ba01f6fb5861d17304ed91c8a25248f02",
    "a20e8ac9cb0b8e5be6bba45f5628881fd08be90ce42d978fba6b4fe80af6bfed",
    "4409267920cc59ff86046d8db8539bc04aa40d1697ab089f9ad39f2cd2434ccb",
    "21c3f1eb77d9a33abb30e017679bd6d1077ff003c7d9498c0420f63ed13c396c",
    "dcf305c0e72220d4b8a9ac020b3dd895e56e854ae690baffd0caeb23538ef991",
    "0fe6e7b6332268d36237170606aa83c47633b17293c917532c568358840cb233",
    "2a846541ad4a2ec7b23b1c3c58c3afe9e1cf5cfeba3f3343a63b8dd7b1ee3bf7",
    "562f8b775bf43a3629da5eb2bc02c63de8d84e12af282e2ae7f3bd273340d55c",
    "63473f06c4cfe82b2b6ca952ee6ed8ef0019b35916d38f154581feeb48a57b30",
    "8f1a219770e1db621b1e44d330fb47210fbc36712317baca627601551dac4ea5",
    "8f782d24de90f5f1149520bb180e6f776ea82284fc75a17a8c9cdcc25464c2dd",
    "cdece42a15ecb792ca933351b11623529dbac34c02c3a9198e61531f67598ee6",
    "e47ebf0c76183c5d0384071db94948ccb8e6375a854873fc78096d734e98c599",
    "1d2ff10a3911d17f01e1e5c499eb4256024b6db30378199c0f2ca0e604053341",
    "056a0a204c1c15b61e7d198f4620e01982cbf8b2642fee7f7a1de26dfbeacf41",
    "e8bf246c251065d007a22b3f783da667d6b7bbfdf8907b3b8c2451d565a7590e",
    "3e57850998383e01dbb7e7e0d2157f154790dbae6c70b9835c742b95d1182f49",
    "71ff2d62824daf8c86f84f9f49e37121efcd764856c3d74b55a361f20c0524aa",
    "29313933be688c1725e7800ffd5e633ee34b87e2c44ddd06abefa7dd1ebd0a58",
    "d559c30265d6e3b7ee304c68f3ebda8f21aae2306816737a6c017c704ef87854",
    "e276d528887d7c51a8c619f9fcef8a9475f2f48493a21681af784bcb08deb215",
    "8ba834ac766d507af0e39dcbdea631d35661c25f2b1d40142ac58b4b1760e075",
    "888a13bfd68635fb18e70e4365aed1c3ebd199b4f660b6d446b4798cb01c2909",
    "76268ff500dcb0d62b3debb9c9f711858e7f448b9826b17b99964f43bc228f48",
    "41c9b067a8095345037ea40851e7b0d67f624002b21d70e9838dcb438b392ea7",
    "d49889f49c92c3097db971ee5ba9b344382c928dc863c5fe752a954501987211",
    "40f046f0c61743d67ecf7e61f1c07258b46f33e0ac44511bf2649cb9e3cf0fd8",
    "6db2c9a65a80ecf69b5ec2864d02207f2f472addc908f1ae7ab994592cb1c693",
    "e3a5b53ea92bd5c734e434802ded5aa48af8295a9477676c9105f74c30b4cd97",
    "58904a3329254a948c483d86e64c71f97d70d95fff57f4904aff0198fce63903",
    "261c3398912fb7a197a76106a66bc7045422970835c157ab6a05c62195915d22",
    "105d6c8d87469db2106a2363cc0817d9c88f4fc721732e9f7dc98c2641de9805",
    "0286c234248a878e4726434ab0484eb086d49895056f2ccd630170e03a3bbac8",
    "b3288dd320ec6719e510034662d628203b09a933e7b84ba208a5518e9267cd0d",
    "963a3d1f730ca3583b26c365c25d97a18b18bcbc5e9e841ca5e476638d9e20ed",
    "f7a1003ee256a24faf154f7dc87b840915627f4d0fa76349dec397a9fa2db558",
    "b8a89d4c12cec318e38fa9e085cb2a9f3a4a6527de7e0c695f3401e1943b4671",
    "4e8f86cc2d5652d37df8033cbe13b2b128edcfbb40d27f3581f7c51c95093d18",
    "12c8b1b2c841e21b5e160929a9b8cf0c7779abc5bf928a4aa5931473efac02da",
    "0a27e234874dd00899ffaa4cbe7de8b8b3f6f4f99f14f3eddcd8d6a0850264f8",
    "0c58e2abcf181f38141d8b721e4cc68d674094fc490a3c7db5e17d18803dfeea",
    "de4f071c474985a9e3d18f3d10d4d316afdc57f1b09b494d25541f7e2c0a7035",
    "9aea93f13ebcf4afc702624675fe7201f4d2d62a3fc5babca55099add81c0aa1",
    "7420e3a2cbac7e675a4ed963c061b58dd3456e95e20fbba06911620efaa4f71d",
    "4522fe0138c127a099450e623c9480e3b2e75d7ae5ddb3504a78790f42e43656",
    "0815ec398a448771809e466f487868297159150fb756b98635f2614839becf72",
    "aa655ecc581048734316d39ec1235e3ee8841ff229d1ace6e4a0c4554d6ee188",
    "bec5e23ea9fbb425d2e865d5543d8ee03e2da1c104e827ecfc160bede3a6bb6b",
    "05a71d25904105f76990735a71305c6c4bd850611129871c84bf060e23921c92",
)

#: The kit's 17 vectors by file name, from its `fixtures/expected.json`.
KIT_VECTOR_SHA256 = {
    "mono_nsif101.ntf": "934a6382dae1f512b4d7c7b426507f017725a92b1bf7d9694c48ee4c6acb8cc8",
    "mono_nsif100.ntf": "436a7d7aa77a4a21faf5590849412d1e0aa5dd4f70292916f0a49af47c4599ad",
    "mono_nitf210.ntf": "4dc3a218dc49394cf9b1fe23afd5ebd27bc2469e247475a8757e540f2038cec9",
    "geo_dms.ntf": "8848dd25910e03aaca8596ee4800b1dcd660dbb92a0ea31f22814267fc8d61d4",
    "unknown_duplicate_tre.ntf": "bfa3feec7d309097fc23268b9ae3406bd0b0d967e44169db2ff9184f18f224a2",
    "mode_B.ntf": "5b184def682d6f0a02b07e0c3cca7fb15ca62206e0f450baa1c90ef82f8f17ca",
    "mode_P.ntf": "bcbf4f7cafaa0395675d712cd9d44fedfd10d0f0ba1e7f7887574aaf0c16d6f8",
    "mode_R.ntf": "09ffe8ed581c75ec811ec5d177abdde45c98e4ef4fc869cc6a06e8819fdf3f00",
    "mode_S.ntf": "869bcbdd2c43a594aaf46dff71ebf6f2718599b648645ba3a689b516c1d831f6",
    "uint16.ntf": "77c8be04836b0e086dd19c895747184dfb982805fbffa78854babc82549f1fd6",
    "image_and_text.ntf": "68d11c0d3123b3a20ce2140db95b1c4844359b2f0cf7a8346098a89613310f48",
    "header_only.ntf": "e6f5af50b4b59b86ff0008ea06987ff5f9f345055b76b120a448f38ddecb877f",
    "bad_file_length.ntf": "dbd7f1edae1f325e7846a86588f72bfb5a9ca013bcc0a32328ebe47257c28385",
    "truncated.ntf": "54e7a8d93c2a59301f48b28c9969124e29bb7690a98a234757cb4ad27dc33c99",
    "trailing.ntf": "689588b79af9a73db5b985cd46efa78d1721f5aa216741095de616de78bd8f0f",
    "bad_count.ntf": "ca1ac997db6b82cfc66f4da292a60cb994e8ad42d00285a08f08b7d6003949ed",
    "unsupported_stype.ntf": "8eac401a58f51d3b063ee67e854f2c311fb07c0b263c2395b7b0b03a563b0274",
}

#: The kit's other eleven files, from its `SHA256SUMS`: none may be tracked here, but for the
#: result contract the host validates every result against, carried byte for byte at one path.
KIT_OTHER_SHA256 = {
    "README.txt": "5a5c06bb1aa1308c5c44e9469d31630a29c07076aee00f9960ceb2dcb0bfa33d",
    "acceptance.csv": "662d1fb53e322ba031c79f819f04fa6403ccb5a2d5a9df1d414faa1814fae89c",
    "check_fixtures.py": "057fabc5613b84083c53709b79a84416431f68aee650f8bf781e680ad483457a",
    "contracts/file-header-fields.json": (
        "51150f031b13d45c287e89b1788747b76ce40ceeb77693a8ded7b80d683ddd22"
    ),
    "contracts/ingest-result.schema.json": (
        "9b9fa1c7e26e229a765d0fffbc8b1cb2f85bcd301767bc1651e6d0e64e60ef65"
    ),
    "evidence-scope.json": "46f7c2a26089a97d45280f0b49e3cdc04a60731fd8dc0865b5dc8740825b7e95",
    "fixtures/expected.json": "2c2c46328a5e95bcb79e275c132881cff495762ebde6ccc5671f6fd5344955c3",
    "make_fixtures.py": "6fb46251f869d759b3e7bd403a139b0f6af3a9c1018d8984795d539741655220",
    "oracle-results.json": "0557c7c6970058f0aa3cea3555607a4ee1b75e38d6bf3104371f1daaa1fff9e9",
    "specification.html": "42b98adb726dccaf72a2c2333f07b188fd820e2393983d36a96b74dae9cd6797",
    "specification.txt": "ae4d912fcc2cd4164dd9e03832501e64c10f660514612ada80d7d8eba697369a",
}
CARRIED_CONTRACT = "packages/imagery/synapse_imagery/contracts/ingest-result.schema.json"

#: The only claim wording, REQ-100's sentence.
CLAIM = (
    "Implements the SC4545-CORE-1 NSIF/NITF imagery ingestion profile, with byte-preserving "
    "metadata inventory, specified NC sample decoding and direct geographic footprints."
)

HEADINGS = (
    "1. Scope",
    "2. Rulings",
    "3. What landed",
    "4. Dispositions",
    "5. Deviations from the specification",
    "6. Evidence",
    "7. Residual and security mapping",
    "8. Handoff list",
    "9. Permitted claim and what is not claimed",
    "10. Open items for the maintainer",
    "11. Commands",
)

#: REQ-100's handoff items, in its order.
HANDOFF = (
    "Source code",
    "Locked optional dependencies",
    "Licence notices",
    "SBOM for native codec builds",
    "Binary fixture manifest",
    "Installed-wheel test output",
    "Conformance evidence",
    "Performance measurements",
    "Fuzz summary",
    "Residual and security mapping",
    "Deployment runbook",
    "Exact permitted claim text",
)

#: REQ-097's eight missing items, in the requirement's order, as the record words them.
BROAD_GATE = (
    "authenticated applicable Edition 2 text and errata",
    "the full NSIF01.01 BIIF profile and accepted updates",
    "a selected national or customer profile",
    "the required registered TRE and DES catalogue",
    "the required codec and mask specifications",
    "official or accepted independent test files",
    "independent results on unchanged NSIF files",
    "a qualified security policy for real deployment labels",
)

#: REQ-094's items, in its order, as the record's release-gate list names them.
RELEASE_GATE = (
    "Every applicable requirement dispositioned",
    "No untriaged parser or security defect",
    "Fixture generation reproducible",
    "Positive and negative assertions complete",
    "Installed-wheel harness pass",
    "Byte-retention pass",
    "Policy-denial pass",
    "No forbidden imports",
    "Bounded-output pass",
    "Documented limitations",
)

#: The fuzz run of record, per target: the totals and outcome digests the record states.
FUZZ = {
    "cursor": (
        64,
        17055,
        82945,
        "0dadefc2bf089c0195b2db832bd1ae9a399ef85f9446db441218eee2a495d0b9",
    ),
    "extensions": (
        7,
        4636,
        95364,
        "d8b9243de8e5956195090c644ecf5d01eb6ad2ff867a0d9ec212d6e4d5b44699",
    ),
    "image_subheader": (
        51,
        14609,
        85391,
        "d6c0d6ebaf350230ea3a80725e373a1db1edca2e65cd58eeb15019a9438314b3",
    ),
    "geometry": (
        125,
        100000,
        0,
        "3610a2bd871eae278555d019801d39ca9c64143db345893a8fdc0ea021f9f28f",
    ),
    "window_index": (
        911,
        57094,
        42906,
        "b8b91bd15880778bc95e79fe257e19e01067acd98f3592ec77d48a08f023a92b",
    ),
}

#: The corpus manifest's fixed texts.
KIT_ORIGIN = "SC-4545-ENG-1.0 kit generator, contributed under Apache-2.0 by the maintainer"
NATIVE_ORIGIN = "authored for this repository by spec/build_fixtures.py"
AUTHORITY = "synthetic engineering vector; no normative authority"
REDISTRIBUTION = "Apache-2.0 (this repository)"
NOT_HELD = (
    "customer-samples",
    "jitc-compliance-files",
    "nga-ntb-test-files",
    "official-nsif0101-samples",
)
ENTRY_KEYS = [
    "name",
    "file",
    "sha256",
    "bytes",
    "origin",
    "authority",
    "redistribution",
    "expected",
    "oracle",
]


def tracked(prefix: str = "") -> list[str]:
    """The paths git tracks (the index), optionally under one directory."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", prefix] if prefix else ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in listing.stdout.split("\0") if name]


def rows() -> list[list[str]]:
    return list(csv.reader(io.StringIO(TABLE.read_text(encoding="utf-8"))))


def record() -> str:
    return RECORD.read_text(encoding="utf-8")


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


def section(text: str, heading: str) -> str:
    """The text of one `## ` section of the record."""
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def collected(path: pathlib.Path) -> set[str]:
    """The test functions pytest collects from a module: module-level `test…` functions and the
    `test…` methods of module-level `Test…` classes, read from the syntax tree."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            names.add(node.name)
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test"):
                    names.add(f"{node.name}::{item.name}")
    return names


def corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


# =========================================================================== the acceptance table


def test_the_acceptance_table_has_the_kits_header_and_100_rows_in_order():
    text = TABLE.read_text(encoding="utf-8")
    assert text.split("\n", 1)[0] == HEADER
    assert text.endswith("\n") and "\r" not in text
    table = rows()
    assert [row[0] for row in table[1:]] == [f"REQ-{n:03d}" for n in range(1, 101)]
    assert all(len(row) == 7 for row in table)


def test_every_status_is_in_the_vocabulary_and_implemented_rows_name_code_and_tests():
    for row in rows()[1:]:
        assert row[2] in STATUSES, row[0]
        if row[2] == "implemented":
            assert row[3] and row[4], row[0]


def test_every_path_and_test_id_in_the_table_resolves():
    anchors = {slug(heading) for heading in HEADINGS}
    text = record()
    cache: dict[str, set[str]] = {}
    for row in rows()[1:]:
        for path in row[3].split(";"):
            assert (REPO / path).exists(), (row[0], path)
        for test in row[4].split(";") if row[4] else []:
            path, name = test.split("::", 1)
            assert path.startswith(("tests/", "packages/imagery/tests/")), (row[0], test)
            if path not in cache:
                cache[path] = collected(REPO / path)
            assert name in cache[path], (row[0], test)
        for item in row[5].split(";"):
            assert item == item.strip() and item, (row[0], item)
            if item.startswith("reason: "):
                continue
            if item.startswith(("python ", "synapse ", "cd ")):
                assert item in text, (row[0], item)
                continue
            path, _, anchor = item.partition("#")
            assert (REPO / path).exists(), (row[0], item)
            if anchor:
                assert path == "docs/stanag4545-implementation.md" and anchor in anchors, item


def test_every_row_not_implemented_gives_its_reason_and_no_reviewer_signs():
    for row in rows()[1:]:
        assert row[6] == "", row[0]
        if row[2] != "implemented":
            assert any(item.startswith("reason: ") for item in row[5].split(";")), row[0]


def test_the_subjects_are_this_repositorys_words():
    assert len(KIT_SUMMARY_SHA256) == 100 and len(set(KIT_SUMMARY_SHA256)) == 100
    for row, kit in zip(rows()[1:], KIT_SUMMARY_SHA256):
        assert 0 < len(row[1]) <= 100, row[0]
        assert hashlib.sha256(row[1].encode("utf-8")).hexdigest() != kit, row[0]


def test_every_disposition_is_the_literal_one():
    found = {row[0]: row[2] for row in rows()[1:] if row[2] != "implemented"}
    assert found == NOT_IMPLEMENTED


def test_the_table_and_the_record_count_the_statuses_alike():
    counts = {status: 0 for status in STATUSES}
    for row in rows()[1:]:
        counts[row[2]] += 1
    table = section(record(), "4. Dispositions")
    for status, count in counts.items():
        assert f"| `{status}` | {count} |" in table, status
    for name, status in NOT_IMPLEMENTED.items():
        assert f"| {name} | `{status}` |" in table, name


# =========================================================================== the record


def test_the_record_has_its_eleven_sections_in_order():
    found = re.findall(r"^## (.+)$", record(), re.M)
    assert found == list(HEADINGS)


def test_the_permitted_claim_appears_once_in_the_record():
    assert record().count(CLAIM) == 1
    assert CLAIM in section(record(), "9. Permitted claim and what is not claimed")


def test_the_record_states_no_measured_duration():
    text = record()
    for pattern in (
        r"p(50|95)\s*[=:]\s*\d",
        r"\d\s?(ms|µs)\b",
        r"\d+(\.\d+)?\s?seconds? (elapsed|measured|on this)",
    ):
        assert not re.search(pattern, text), pattern


def test_the_record_names_the_table_and_the_corpus():
    text = record()
    assert "docs/stanag4545-acceptance.csv" in text and "docs/stanag4545-corpus.json" in text


def test_the_evidence_files_state_no_roster_count():
    for path in (RECORD, TABLE, CORPUS):
        flat = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        for found in ROSTER_COUNT.finditer(flat):
            assert stated(found["num"].lower()) < ROSTER_FLOOR, (path.name, found.group(0))


def test_the_record_lists_the_rounds_in_their_order():
    text = section(record(), "3. What landed")
    order = [text.index(f"R{n} ") for n in range(6)]
    assert order == sorted(order)
    assert "the fuzz suite was written after the worker interface and the writer" in text
    assert "No native worker or codec entered core in any round" in text


def test_the_release_gate_items_are_each_evidenced():
    text = section(record(), "4. Dispositions")
    gate = text[text.index("### The core release gate (REQ-094)") :]
    found = re.findall(r"^(\d+)\. \*\*(.+?)\*\*: \S", gate, re.M)
    assert found == [(str(n), item) for n, item in enumerate(RELEASE_GATE, 1)]


def test_the_broad_conformance_gate_lists_its_eight_missing_items():
    text = re.sub(r"\s+", " ", section(record(), "10. Open items for the maintainer"))
    positions = [text.index(item) for item in BROAD_GATE]
    assert positions == sorted(positions)
    (row,) = [row for row in rows()[1:] if row[0] == "REQ-097"]
    assert row[2] == "gate_open" and "Edition 2 text and errata" in row[5]


def test_the_fuzz_summary_is_the_run_of_record():
    text = section(record(), "6. Evidence")
    for target, (seeds, accepted, refused, digest) in FUZZ.items():
        line = f"| `{target}` | {seeds} | 100000 | {accepted} | {refused} | 0 | 0 | `{digest}` |"
        assert line in text, target
        assert accepted + refused == 100000
    assert "0 crashes, 0 hangs; no regression fixture was produced" in text


def test_the_handoff_list_names_its_twelve_items_in_order():
    text = section(record(), "8. Handoff list")
    assert re.findall(r"^\d+\. \*\*(.+?)\*\*:", text, re.M) == list(HANDOFF)
    for path in re.findall(r"`([^`\s]+)`", text):
        if "/" in path or path in ("LICENSE", "NOTICE"):
            assert (REPO / path).exists(), path
    assert (REPO / "packages" / "imagery" / "docs" / "runbook.md").is_file()


#: The keys under `residual.data.stanag4545`, in the order the adapter builds them and the
#: record's section 7 lists them: the product's six and each footprint's seven.
PRODUCT_RESIDUAL = (
    "wire_b64",
    "file_header",
    "segments",
    "extensions",
    "security",
    "parse_profile",
)
FOOTPRINT_RESIDUAL = (
    "presentation",
    "product",
    "image",
    "footprint",
    "label_basis",
    "security",
    "diagnostics",
)


def test_the_residual_table_has_one_row_for_every_key_a_golden_carries():
    """Section 7's residual rows against `golden/geo_dms.cdm.json`, whose product has a footprint:
    the table names each key once, in order, and the golden carries exactly those keys."""
    table = section(record(), "7. Residual and security mapping")
    named: dict[str, list[str]] = {"product": [], "footprint": []}
    pattern = r"^\| (product|footprint) `(?:residual\.data\.stanag4545\.|\u2026\.)([a-z_0-9]+)"
    for kind, key in re.findall(pattern, table, re.M):
        named[kind].append(key)
    assert tuple(named["product"]) == PRODUCT_RESIDUAL
    assert tuple(named["footprint"]) == FOOTPRINT_RESIDUAL
    golden = json.loads((FIXTURES / "golden" / "geo_dms.cdm.json").read_text(encoding="utf-8"))
    product, footprint = golden
    for found, keys in ((product, PRODUCT_RESIDUAL), (footprint, FOOTPRINT_RESIDUAL)):
        assert found["residual"]["namespace"] == "NSIF/NITF imagery"
        assert list(found["residual"]["data"]) == ["stanag4545"]
        assert sorted(found["residual"]["data"]["stanag4545"]) == sorted(keys)
    assert list(product["attributes"]) == ["stanag4545"]
    assert footprint["residual"]["data"]["stanag4545"]["label_basis"] == "IID1"


def test_no_added_file_makes_a_banned_claim():
    banned = (
        "100" + "/100",
        "STANAG 4545 " + "compliant",
        "STANAG 4545 " + "certified",
        "full STANAG 4545 " + "support",
        "fully supports " + "STANAG 4545",
    )
    added = [
        "docs/stanag4545-implementation.md",
        "docs/stanag4545-acceptance.csv",
        "docs/stanag4545-corpus.json",
        "manifests/stanag4545.json",
        "packages/cdm/synapse_cdm/adapters/stanag4545.py",
        "packages/cdm/synapse_cdm/adapters/nsif_codec.py",
        "packages/cdm/synapse_cdm/adapters/nsif_geometry.py",
        *(name for name in tracked("gates") if "/nsif_" in name),
        *(
            name
            for name in tracked("tests")
            if name.startswith(("tests/test_cdm_nsif_", "tests/test_cdm_stanag4545_"))
        ),
        *(name for name in tracked(FIXTURE_PREFIX) if name.endswith((".md", ".py"))),
        *(name for name in tracked("packages/imagery") if name.endswith((".py", ".md", ".toml"))),
    ]
    assert len(added) > 40
    for name in added:
        text = (REPO / name).read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase.lower() not in text, (name, phrase)


def test_the_core_test_modules_never_mark_a_test_as_not_run():
    words = ("sk" + "ip", "x" + "fail", "import" + "or" + "sk" + "ip")
    directive = "# fmt: " + "sk" + "ip"
    modules = (
        "test_cdm_nsif_codec.py",
        "test_cdm_nsif_geometry.py",
        "test_cdm_stanag4545_adapter.py",
        "test_cdm_nsif_robustness.py",
        "test_cdm_nsif_fuzz.py",
        "test_cdm_nsif_benchmark.py",
        "test_cdm_stanag4545_evidence.py",
    )
    for name in modules:
        # The formatter's own directive is not a test outcome.
        text = (REPO / "tests" / name).read_text(encoding="utf-8").replace(directive, "").lower()
        for word in words:
            assert word not in text, (name, word)
        if name in ("test_cdm_nsif_codec.py", "test_cdm_nsif_geometry.py"):
            assert "os" + "geo" not in text, name


def test_the_parser_safety_page_lists_the_adapter_and_its_bounds():
    text = PARSER_SAFETY.read_text(encoding="utf-8")
    bounds = text[text.index("\n## 1. ") : text.index("\n## 2. ")]
    audit = text[text.index("\n## 7. ") :]
    (row,) = [line for line in bounds.splitlines() if line.startswith("| `stanag4545` |")]
    assert row.startswith("| `stanag4545` | 16 777 216 | implementation cap |")
    for words in (
        "22 369 624 characters before decoding",
        "`nsif_codec.CORE1_LIMITS`",
        "cannot be reached by a CORE-1 container",
    ):
        assert words in row, words
    assert "on `stanag4545`" in bounds
    assert not [line for line in audit.splitlines() if line.startswith("| `stanag4545`")]


# =========================================================================== the corpus manifest


def test_every_tracked_vector_is_in_the_corpus_once_with_its_digest():
    document = corpus()
    assert list(document) == ["schema_id", "profile", "entries"]
    assert (document["schema_id"], document["profile"]) == (
        "synapse.stanag4545-corpus/v1",
        "SC4545-CORE-1",
    )
    entries = document["entries"]
    assert [entry["name"] for entry in entries] == sorted(entry["name"] for entry in entries)
    assert all(list(entry) == ENTRY_KEYS for entry in entries)
    held = [entry for entry in entries if entry["file"] is not None]
    vectors = sorted(
        name[len(FIXTURE_PREFIX) :] for name in tracked(FIXTURE_PREFIX) if name.endswith(".ntf")
    )
    assert len(vectors) == 64
    assert sorted(entry["file"] for entry in held) == vectors
    for entry in held:
        octets = (FIXTURES / entry["file"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(octets).hexdigest(), entry["name"]
        assert entry["bytes"] == len(octets)
        assert entry["name"] == pathlib.PurePosixPath(entry["file"]).stem
        assert (entry["authority"], entry["redistribution"]) == (AUTHORITY, REDISTRIBUTION)
        basename = pathlib.PurePosixPath(entry["file"]).name
        if basename in KIT_VECTOR_SHA256:
            assert entry["sha256"] == KIT_VECTOR_SHA256[basename]
            assert entry["origin"] == KIT_ORIGIN
        else:
            assert entry["file"].startswith("vectors/native_") and entry["origin"] == NATIVE_ORIGIN
    assert sum(entry["origin"] == KIT_ORIGIN for entry in held) == 17


def test_every_held_entry_has_the_outcome_the_parser_gives():
    adapter = Stanag4545Adapter()
    readings = {path.name.removesuffix(".gdal.json") for path in FIXTURES.glob("independent/*")}
    for entry in corpus()["entries"]:
        if entry["file"] is None:
            continue
        octets = (FIXTURES / entry["file"]).read_bytes()
        expected = entry["expected"]
        if expected["outcome"] == "ok":
            found = nc.parse_container(octets, nc.CORE1_LIMITS)
            assert adapter.validate_source(octets) == [], entry["name"]
            if "samples_band_major" in expected:
                image = found.images[0]
                window = nc.decode_nc_window(
                    found, 0, 0, 0, image.ncols, image.nrows, tuple(range(image.band_count))
                )
                assert list(window.values()) == expected["samples_band_major"], entry["name"]
        else:
            assert expected["outcome"] == "refused"
            with pytest.raises(nc.NsifError) as caught:
                nc.parse_container(octets, nc.CORE1_LIMITS)
            error = caught.value
            assert (error.code, error.stage, error.offset) == (
                expected["code"],
                expected["stage"],
                expected["offset"],
            ), entry["name"]
            assert len(adapter.validate_source(octets)) == 1
        gdal = f"GDAL 3.13.3 storage reading, independent/{entry['name']}.gdal.json"
        assert (gdal in entry["oracle"]) == (entry["name"] in readings), entry["name"]


#: The SarPy surrogate check as the kit's `oracle-results.json` records it: the twelve vectors its
#: unchanged reader was run on, and the one whose shared samples check reads `not_verified`.
SARPY = "SarPy fdcff94e surrogate layout check, kit oracle-results.json (retained, not re-run)"
SARPY_CHECKED = {
    "geo_dms",
    "header_only",
    "image_and_text",
    "mode_B",
    "mode_P",
    "mode_R",
    "mode_S",
    "mono_nitf210",
    "mono_nsif100",
    "mono_nsif101",
    "uint16",
    "unknown_duplicate_tre",
}


def test_the_corpus_names_the_sarpy_check_with_its_retained_failure():
    entries = {entry["name"]: entry for entry in corpus()["entries"]}
    checked = {
        name
        for name, entry in entries.items()
        if any(oracle.startswith("SarPy") for oracle in entry["oracle"])
    }
    assert checked == SARPY_CHECKED
    for name in sorted(SARPY_CHECKED - {"mode_R"}):
        assert entries[name]["oracle"].count(SARPY) == 1, name
    assert entries["mode_R"]["oracle"][-1] == (
        SARPY + ": header layout verified, samples not verified (IMODE R)"
    )
    assert SARPY not in entries["mode_R"]["oracle"]


def test_the_samples_not_held_are_named_with_null_hashes():
    entries = {entry["name"]: entry for entry in corpus()["entries"]}
    for name in NOT_HELD:
        entry = entries[name]
        assert (entry["file"], entry["sha256"], entry["bytes"], entry["expected"]) == (
            None,
            None,
            None,
            None,
        )
        assert entry["oracle"] == []
    outside = "outside the public repository unless publication is authorised"
    assert entries["customer-samples"]["redistribution"] == outside
    assert entries["official-nsif0101-samples"]["redistribution"] == outside
    assert len(entries) == 64 + len(NOT_HELD)


# =========================================================================== retained kit evidence


def test_the_record_retains_the_sarpy_evidence_by_citation():
    text = section(record(), "6. Evidence")
    assert "`fdcff94e8582fecd680f0b69471f3dc0b4384011`" in text
    assert f"`{KIT_OTHER_SHA256['oracle-results.json']}`" in text
    assert (
        '"not_verified: IMODE is `R` and the image is compressed at image segment index 0"' in text
    )
    assert '("rejected: Not a NITF file")' in text
    assert "surrogate layout evidence, never NSIF acceptance" in text


def test_no_tracked_file_is_a_kit_file_other_than_the_vectors():
    forbidden = {digest: name for name, digest in KIT_OTHER_SHA256.items()}
    carried = []
    for name in tracked():
        path = REPO / name
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in forbidden:
            carried.append((name, forbidden[digest]))
    assert carried == [(CARRIED_CONTRACT, "contracts/ingest-result.schema.json")]


def test_the_manifest_the_table_relies_on_is_the_adapters():
    adapter = json.loads(MANIFEST.read_text(encoding="utf-8"))["adapter"]
    assert (adapter["id"], adapter["adapter_version"], adapter["direction"]) == (
        "stanag4545",
        "1.0.0",
        "ingest",
    )
    assert (adapter["binding"], adapter["claim_status"]) == (
        "provisional-internal-profile",
        "PROVISIONAL",
    )
    assert adapter["evidence"] == {"available": False}
