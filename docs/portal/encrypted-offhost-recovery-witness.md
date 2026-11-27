# Encrypted off-host recovery witness (read-only)

**Status: SIGNED_ENCRYPTED_COPY_VERIFIED_NOT_ATOMIC. Production release remains NO_GO.**

The script scripts/portal_encrypted_custody_verify.py verifies the fixed October 23, 2026 signed recovery receipt from x1-370. It reads exact ciphertext/manifest/signature hashes independently from xwing **and Beelink**, verifies the detached Ed25519 manifest signature against the pinned Lenovo signing public key, validates the pinned RSA recipient certificate, and confirms protected signing/decryption key files remain on Lenovo.

Operator use: python3 scripts/portal_encrypted_custody_verify.py
Offline tests: python3 -m pytest -q scripts/tests/test_portal_encrypted_custody_verify.py

The existing x1-370 systemd user timer kipnerter-encrypted-recovery-watch.timer performs six-hour read-only monitoring. Its mode-0600 status file is /home/scott/.local/state/kipnerter-private-recovery-candidate-20261023/status.json. No automatic restore, deletion, DNS, ACL, or deployment is permitted. Failed validation returns CHECK_REQUIRED and exit code 3.

Archive ID: 20261023T064429Z-b4b7402d. Ciphertext and signed manifest are retained on xwing in an owner-private directory. RSA decryption key and Ed25519 signing private key remain on Lenovo and MUST NOT be copied into Git, agent logs, chat, backup ciphertext storage, or build artifacts.

Important limits: both PostgreSQL and MinIO snapshots were captured during a short *unfenced* observation window. This is NOT an atomic cross-resource point-in-time checkpoint, independent administrator custody, immutable anti-rollback record, offsite escrow, original legacy API/web image rollback, authenticated OIDC acceptance, or permission for production cutover. Both custody machines share one administrator. Loss of the Lenovo RSA private key makes this copy unrecoverable without separate authorized escrow.

Production release remains NO_GO pending actual writer fencing, a durable consistent checkpoint, independent anti-rollback custodian, reversible stateful restore, legacy image recovery, and legitimate Tailnet IdP browser acceptance.

References: https://github.com/scottjoyner/kipnerter/issues/19 and https://github.com/scottjoyner/kipnerter/issues/50; knowledge inbox 00-Inbox/2026-10-23-kipnerter-encrypted-cross-host-recovery-custody.md.

No private keys, credentials, raw database contents, object data, or enrollment URLs are included.