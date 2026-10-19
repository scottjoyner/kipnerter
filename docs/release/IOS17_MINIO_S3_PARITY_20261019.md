# Production backup → restored MinIO S3 inventory read-back

Read only the known `kipnerter-artifacts` bucket metadata via `mc ls --json` from inside the running MinIO container and from a newly created `--network none` scratch MinIO instance restored from the protected raw backup. Compare only bucket existence and sorted object-key/size/ETag triples **in memory**; never print identifiers, credentials, objects or raw listings. The scratch container and files are ephemeral, and source production buckets/volumes must not be written, restarted or publicly exposed. A parity mismatch or any client failure leaves the release on HOLD and must not cause an automatic backup reattempt. Matching metadata is not a point-in-time consistent snapshot, body hash proof, independently controlled off-host custody or production cutover authorization. The existing iOS build 1.7.0 TestFlight stays unchanged.

## October 19 — bounded scratch extraction and private source receipt

The isolated MinIO parity script now fails closed before extraction if a
raw tar contains paths outside the expected `data/` namespace, duplicate
names, directory traversal, links, special-file entries, oversized path
names, excessive member count or declared expanded payload beyond 3 GiB.
It also refuses a nonempty scratch destination or insufficient free scratch
capacity (including a 128 MiB headroom margin). The preflight checks every
archive member **before** writing extracted files. This is local scratch
filesystem safety, not a claim that the unquiesced live MinIO copy is
point-in-time consistent.

Before staging those bytes, the restore verifier now checks the private
receipt and archive are current-user-owned, mode 0600/0700, non-symlinked,
and that both recorded copy size and SHA-256 match the exact snapshot.
A matching receipt proves archive consistency relative to the original
snapshot receipt, **not** independently administered custody, object-body
equivalence or safe production rollback.

All new negative controls use synthetic, disposable tar fixtures in unit
tests; no source MinIO object body or bucket credentials are opened in
these controls. Do not rerun the one-shot backup or production parity action
because of these code changes without a separate operator approval.
