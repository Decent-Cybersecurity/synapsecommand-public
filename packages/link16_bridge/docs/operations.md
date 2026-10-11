# synapse-link16-bridge: operations

Written 2026-10-11 with the bridge's first version, 1.0.0. This page is the bridge's operating
contract: the configuration, the limits, the channel states and how each one ends, the codes the
bridge writes, and the definitions it gives the terms the handoff's specification leaves open.

## Configuration

One JSON file, read strictly (UTF-8 without a byte order mark, no duplicate key, no non-finite
number), every key checked, an unknown key refused, nothing included or inherited. A refused file
builds no bridge, so transmit permission stays off. A change is a new file with a new
`config_revision`; every audit row records the revision. A channel stopped under one revision
starts again only under a new one.

| Key | Default | Rule |
|---|---|---|
| `config_revision` | required | 1 to 128 characters |
| `mode` | `ingest` | `ingest` or `bidirectional`; `bidirectional` needs a non-empty `export_policy` |
| `gateway_base_url` | required | `https://`, or `http://` to `127.0.0.1`, `::1` or `localhost` exactly; no user information, query or fragment |
| `gateway_id`, `consumer_id`, `tenant`, `realm`, `security_context` | required | identifiers `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}` |
| `credential_ref` | required | `env:NAME`: the environment variable holding the bearer credential; a literal is refused; the credential itself must be visible ASCII (0x21 to 0x7E: no space, no control character), checked when the client is built and refused as a configuration error that never quotes it (added 2026-10-11) |
| `realm_kind` | required | `live`, `exercise` or `replay`; `replay` needs `synthetic` true, `mode` ingest, no `transmit_families` and no `peer_profile` |
| `synthetic` | required | a boolean, no default |
| `approved_origin_scopes` | required | a non-empty list of identifiers |
| `native_profile` | required | 1 to 128 characters; must be exactly one the gateway offers |
| `cdm_schema_version` | required | the CDM schema versions the sink accepts, an explicit list (the specification's 4.0.0 target is CDM 3.1.0 here) |
| `receive_families` | `J3.2 J3.3 J3.4 J3.5` | distinct labels; intersected with the gateway's |
| `required_families` | empty | a family the gateway lacks makes the internal release stage `NOT_READY` |
| `transmit_families` | empty | the families an export may use |
| `export_policy` | empty | the rules below |
| `number_allocations_ref` | null | an identifier naming the provider's allocation records, written into each allocation |
| `peer_profile` | null | an object, for a native connection only |
| `freshness_seconds` | 30 AIR, 120 SURFACE, SUBSURFACE, LAND, UNKNOWN | finite, 0 to 86 400 |
| `long_poll_seconds` | 20 | 0 to 300 |
| `request_deadline_seconds` | 25 | must exceed `long_poll_seconds` plus `transport_allowance_seconds` |
| `connect_timeout_seconds` | 5 | below the request deadline |
| `transport_allowance_seconds` | 2 | the specification's "transport allowance" |
| `outbound_max_age_seconds` | 10 | the age limit of an export's position and motion, and its expiry |
| `limits` | below | integers within their bounds |
| `store_path` | required | the channel's SQLite file |
| `lease_ttl_seconds` | 30 | the writer lease's lifetime between renewals; must exceed `request_deadline_seconds` (added 2026-10-11) |
| `idle_poll_seconds` | 1 | above 0 and below `lease_ttl_seconds`: the wait after a pass that fetched nothing (a stopped, resynchronising or capped channel, or an empty batch), so the loop never spins; added 2026-10-11 |

An export rule: `{"policy_revision", "source": {"tenant", "realm", "synthetic", "label_set"},
"destination": {"peer_id", "tenant", "realm", "synthetic", "security_context", "vertical_forms",
"vertical_required"}, "families", "forwarding": false}`. A source resolves to a destination only
when one rule names exactly its label set (set equality), tenant, realm and synthetic layer and
exactly the destination peer; no rule means deny. `forwarding: true` is refused: no forwarding
profile is implemented. This is configuration matching, not a classification-policy engine and
not a cross-domain guard.

## Limits

| Limit | Default | At 80 percent | At 100 percent |
|---|---|---|---|
| active source identities per channel | 100 000 | a warning in `status` | the batch that would add one, by a report or by a `REKEY` notice's new tuple, is not consumed; `CAPACITY_IDENTITIES` (the notice half added 2026-10-11) |
| queued reports (outbox events not yet delivered) | 10 000 or 64 MiB | a warning | fetching stops until the sink takes them; nothing is lost; `CAPACITY_REPORTS` |
| queued exports (jobs not final) | 4 096 or 16 MiB | a warning | a new export is denied `CAPACITY_EXPORTS` |
| quarantine (quarantined bodies and raw batches kept as evidence) | 1 GiB | a warning | new refusals kept as metadata only, and the `quarantine_metadata_only` alarm counted |
| HTTP body | 8 MiB | — | 413 before the body is read; a longer answer is refused by the client |
| one report | 1 MiB, depth 32, 10 000 nodes | — | `LIMIT_EXCEEDED`, judged per report by the adapter on its canonical octets |
| one batch | 1 000 records, depth 67 | — | structurally invalid, nothing consumed |
| samples kept in memory per identity | none (the bound is 100) | — | durable history keeps every one; the bridge keeps no in-memory sample cache (an unread one, and its `sample_cache` limit, were removed on 2026-10-11) |

Nothing live is evicted: no identity, no tombstone, no unacknowledged export.

`status` lists the caps in their 80 percent band (`warnings`) and every cap at 100 percent, of
every kind (`full`); only the report queue's stops fetching (added 2026-10-11).

Past the quarantine cap each new refusal still keeps one metadata row (code, path, rule, digest;
no body, no raw batch), so `resolve-reuse` has something to act on. That row grows at the rate of
the audit row every refusal requires, and the bridge deletes neither in this release: their
retention is an operations matter for the deployment's evidence policy, and the bridge offers no
pruning command (added 2026-10-11).

## Channel states and how each ends

| State | Entered on | Effect | Ends by |
|---|---|---|---|
| `NORMAL` | — | ingest and allowed exports | — |
| `INCOMPLETE` | a `GAP` notice, a sequence gap (`STREAM_GAP`), or after `resync` | ingest continues; exports denied `CHANNEL_INCOMPLETE`; health not ready | `recover --evidence TEXT`, recorded with the gap's bounds; no drop is generated for tracks absent from a later snapshot. Only `recover` ends it: a stop, a scope reset or a cap that holds the channel meanwhile returns it to `INCOMPLETE`, never to `NORMAL`, and health names `CHANNEL_INCOMPLETE` beside that state's own reason (added 2026-10-11) |
| `RESYNC_REQUIRED` (`CURSOR_EXPIRED`) | a 410 from the gateway | no fetch; exports denied; health not ready | `resync --accept-earliest [--lost-count N] --evidence TEXT`: the cursor moves to the earliest retained one, the loss is accounted (`dropped_by_capacity`, when the gateway's count is known), and the channel is `INCOMPLETE` until `recover` |
| `RESYNC_REQUIRED` (`RESET_SCOPE`) | a `RESET_SCOPE` notice: the delivery epoch closes | no fetch; exports stopped | `resync-identities --decision keep|advance --evidence TEXT`: `advance` makes the next report of every identity of the closed epoch ambiguous reuse |
| `STOPPED` | `SYNTHETIC_MISMATCH`, `SECURITY_CONTEXT_MISMATCH`, a 401 or 403, a cursor the gateway calls foreign or future, or a structurally invalid batch refused three times | no fetch, no acknowledgement, no export; health not ready | a new configuration revision |
| `OVERLOADED` | the report-queue cap, or a batch the identity cap does not let in, on a `NORMAL` channel (on an `INCOMPLETE` one the cap holds the same way and the state stays `INCOMPLETE`; `status` lists the cap under `full`; added 2026-10-11) | at the report-queue cap no fetch; at the identity cap the same batch is fetched each pass and not consumed | the report-queue cap: by itself when the queue is below it; the identity cap: when a batch is consumed (one that fits, or under a new configuration revision with a higher `max_identities`). The state and its `capacity` and `capacity_cleared` audit rows change on a transition only, never once per pass (added 2026-10-11) |
| degraded (a flag) | `DUPLICATE_CONFLICT`, or a structurally invalid batch | reported in `status` | `recover --evidence TEXT`, which on a channel that is not `INCOMPLETE` clears the flag only: a `STOPPED`, `RESYNC_REQUIRED` or `OVERLOADED` state stays and ends as its own row says (added 2026-10-11) |

A disconnect, a 503, a 429, a missed long poll or an empty batch changes no identity, no state and
no history. After a disconnect, a 503 or a 429 the bridge waits for the reconnect backoff (1, 2,
4, 8, 16, then 30 s, each times a uniform factor in [0.8, 1.2], reset after 60 s of stable
service) and asks again; after an empty batch, or a pass on a channel that is stopped, awaiting
resynchronisation or at a capacity cap, it waits `idle_poll_seconds`. An acknowledgement the
gateway refuses, or whose answer does not arrive, leaves the pass unacknowledged: the batch is
committed, and the next pass reads after the committed cursor and acknowledges again.

Two outcomes end the running bridge itself (added 2026-10-11): a lease lost at any fenced step of
a pass — the record of an acknowledgement, a refusal's own audit transaction, the warning counter —
ends the pass `BLOCKED` with `LEASE_LOST`, and an exception the pass does not expect ends it
`BLOCKED` with `INTERNAL_ERROR` and one audit row naming the exception's type only; `run` then
exits 3, and a restart takes the lease again. A sink that does not take the outbox's head makes
health not ready (`SINK_FAILED`) until it does, with one `sink_failed` audit row when it starts
failing and one `sink_recovered` row when it stops; the event stays queued, never lost.

The operator records (`recover`, `resync`, `resync-identities`, `resolve-reuse`, `resolve-send`,
`allocate`, `evidence`) take the channel's writer lease; with a bridge running on the channel they
are refused (exit 4) until it stops.

## Codes

The specification's section 16 codes, with the bridge's action:

| Code | Action |
|---|---|
| `SCHEMA_INVALID`, `JSON_INVALID` | the report is quarantined with its disposition; no automatic retry |
| `LIMIT_EXCEEDED` | quarantined per report; a batch past its own bounds is not consumed |
| `SYNTHETIC_MISMATCH`, `SECURITY_CONTEXT_MISMATCH` | the whole batch rolled back, nothing acknowledged, the channel stopped, the refusal recorded in its own audit transaction |
| `TIME_UNRESOLVED` | kept as opaque evidence; no canonical track |
| `IDENTITY_SCOPE_UNRESOLVED`, `REUSE_AMBIGUOUS` | quarantined |
| `UNSUPPORTED_MESSAGE` | kept as opaque evidence; never projected |
| `UNSUPPORTED_FIELD_FORM`, `NATIVE_PROFILE_INCOMPLETE` | native: the activation gate refuses |
| `CDM_SOURCE_CONFLICT`, `ALTITUDE_DATUM_UNSUPPORTED`, `VALUE_NOT_REPRESENTABLE` | the export is denied with its loss record; nothing sent |
| `DUPLICATE_CONFLICT` | quarantined; the channel degraded |
| `CURSOR_EXPIRED`, `STREAM_GAP` | `RESYNC_REQUIRED` or `INCOMPLETE`, as above |
| `SEND_OUTCOME_UNKNOWN` | the job is `UNKNOWN`; no automatic re-send; `reconcile` adopts the gateway's state, and `resolve-send --decision abandon` closes a request the gateway does not know as `FAILED` |

The bridge's own codes: `LIFECYCLE_CONTRADICTION` (a drop older than the identity's current state,
with no native lifecycle resolver to confirm the order: quarantined, the contribution stays open);
`EXPORT_DENIED`, whose reason is one of `POLICY_DENIED`, `SYNTHETIC_MISMATCH`, `REALM_LOOP`,
`NUMBER_UNALLOCATED`, `FAMILY_NOT_ALLOWED`, `PROFILE_NOT_READY`, `SOURCE_STALE`, `TIME_SKEW`,
`CHANNEL_INCOMPLETE`, `REQUEST_EXPIRED`, `LEASE_LOST` or `CAPACITY_EXPORTS`; `INTERNAL_ERROR`
and `SINK_FAILED` (above; added 2026-10-11); and the API's
`UNAUTHENTICATED` (401), `FORBIDDEN` (403), `NOT_FOUND` (404, an unknown path or request id),
`REQUEST_ID_CONFLICT` and `PROFILE_MISMATCH` (409), `CURSOR_EXPIRED` (410), `LIMIT_EXCEEDED`
(413), `CURSOR_FUTURE`, `CURSOR_FOREIGN` and `REQUEST_EXPIRED` (422), `CAPACITY` (429) and
`PROVIDER_UNAVAILABLE` (503). Every error body is `{code, message, correlation_id, retryable}`
from a fixed table; `retryable` is true for 429 and 503 only, and no message carries a payload
value.

`PROFILE_NOT_READY` also denies the export of an Entity that the compatibility projection
published without its position — one whose `source.transformations` carry the
`POSITION_NOT_PROJECTED_CDM3` marker, or whose stored current snapshot does — because the report
built from it would say `position: null` for a source that reported a position, with no loss
record. Exporting a positioned SENSOR or UNKNOWN source needs the FULL projection, which a sink
that accepts CDM 3.1.0 is served from the 3.4.0 release, the one that types that schema version
(added 2026-10-11).

## Definitions

- **Canonical JSON.** `json.dumps(value, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False, allow_nan=False)` in UTF-8. A report's octets for the adapter are the
  canonical encoding of its `body` as parsed from the batch; the raw batch is kept as evidence
  when one of its records is refused.
- **Identical body.** Two record or request bodies whose canonical JSON is equal.
- **Identical state.** The SHA-256 of a report's canonical JSON without `record_id`,
  `gateway_id`, `session_id`, `sequence`, `received_at`, `reporter` and `time_evidence`. Equal
  `effective_at` and equal state is a refresh; equal `effective_at` and a different state is a
  conflict, and the established current state stays.
- **Sample conflict.** One identity, one `position.observed_at`, a different position.
- **Ambiguous reuse.** A report of a tuple closed by a drop and later than the drop; a report of
  a lower incarnation later than a higher incarnation's first report, whether or not that lower
  tuple was seen before; a report of an identity of an epoch closed with `advance`. A report at a
  higher, unseen incarnation is the provider's allocation: a new identity, and the quarantined
  reports of the lower one are closed as superseded. `resolve-reuse` decides a quarantine under
  any of the three: `continue` records the decision on the tuple (admitting it when it was never
  admitted) and releases its reports, so later reports of it are not held to the rule again
  against the incarnations known when the decision was recorded; a higher incarnation that
  appears afterwards holds the tuple to the rule again, and a new `continue` is needed;
  `reject` closes the quarantined reports and admits nothing.
- **Contradictory lifecycle history.** A drop older than the identity's current state.
- **Closing a contribution.** A `close` event carrying a copy of the last published Entity with
  `valid_to` set to the drop's `effective_at`, a tombstone, and the contribution closed.
- **Channel.** The configured `gateway_id`, `tenant`, `realm`, `synthetic` and `security_context`,
  with `consumer_id`; a record matches when each field it carries is equal, exactly.
- **Cursor.** Opaque text the gateway issues; `after=c` delivers the records strictly after `c`
  (the reading of "inclusive contents after the opaque committed cursor"). A batch never spans a
  session change, and a record naming another session than its batch makes the batch invalid.
- **Report order.** Each committed record of a session is the previous sequence plus one; a jump
  is a gap, a record at or below the last sequence is a redelivery for deduplication to judge,
  and a new session starts at 0 (except on a channel that has committed nothing). A `sequence`
  is read only in the contract's form (`0|[1-9][0-9]{0,19}`, a uint64); any other is not read
  at all, and the adapter quarantines the record `SCHEMA_INVALID` (added 2026-10-11).
- **Delivery epoch.** The channel's epoch, which a `RESET_SCOPE` closes; it is read again after
  each notice, so a report after a `RESET_SCOPE` belongs to the new epoch whether it arrives in
  the same batch or a later one (added 2026-10-11).
- **REKEY.** A durable relation from the old tuple to the new one, both identities kept, nothing
  merged; the new tuple, when not yet known, becomes a LIVE identity held to the identity cap. A
  `REKEY` whose old tuple this channel never saw is accepted and its relation recorded all the
  same: the relation is the record REQ073 asks for (added 2026-10-11).
- **Structurally invalid batch.** Not strict JSON outside every record body, or an envelope that
  is not the API's `batch`; a duplicate key, a non-finite literal, a lone surrogate or a number no
  double holds INSIDE one body makes only that record `JSON_INVALID`.
- **Queued reports and exports.** Undelivered outbox events; export jobs not in a final state.
- **Number allocation.** A destination tuple the provider allocated, recorded with `allocate` and
  the operator's evidence; the API carries no allocation call, so none is ever computed.
- **Clock.** One injected wall clock, one sleeper and one random source; instants in the store
  are integer UTC milliseconds.
- **A restart with an unacknowledged commit.** The first fetch asks again from the last
  acknowledged cursor; the gateway redelivers and every record is a `DUPLICATE`.
- **An export that may have left.** A job marked in flight when its POST starts; a restart under
  a new fence turns it `UNKNOWN`, never into a second send. A job of an older fence that never
  left is `REVALIDATE`d (policy, expiry, freshness, allocation) before it is sent with its own
  request id and body.
- **Request deadline.** One bound on a whole request to the gateway, from before the connection
  to the last octet of the answer; the time left is recomputed before every send (the header
  block and the body each) and every read, and is that operation's whole timeout, so a request
  sent into a slow sink or an answer that arrives in slow pieces fails at the deadline (a read is
  retried with backoff, a write is `SEND_OUTCOME_UNKNOWN`).
- **Current snapshot.** The Entity the bridge stored as the source identity's current state, and
  the one-sample Track the same record produced, compared in canonical JSON. The Entity (and
  Track) the bridge published for a `REFRESH` record of that identity — same `effective_at`,
  same state hash as current, not late — is accepted too, and what is sent is the stored current
  snapshot. An export of anything else — an older snapshot, a `LATE` or `CONFLICT` record's
  Entity, or one changed by the caller — is denied `SOURCE_STALE`, so an exported report's times
  and provenance are always the stored record's own.
- **Outbound session and sequence.** Each bridge start opens its own outbound `session_id`; each
  committed export job takes the next `sequence` of it from 0, and a retried job keeps its body.
- **History export.** Not offered: an export takes the current snapshot only.
