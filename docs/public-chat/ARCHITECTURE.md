# Kipnerter public on-device chat — v0.1.0 (2026-10-29)

## Trust boundaries
- The homepage is public, no authentication. Browser downloads LFM3-1.7B ONNX q4f16 from Hugging Face and executes Transformers.js v4.3.2 via WebGPU.
- CPU fallback uses q4 ONNX with WASM. Large downloads and memory limitations apply; not all devices can run this model.
- The existing /chat path stays an authenticated fleet console in latest source; never make its internal APIs public.
- DigitalOcean only serves the UI/static WASM. Third-party model distribution receives ordinary model-download HTTP metadata.

## SensorGraft browser adapter
- Rust source: apps/web/wasm/sensorgraft-browser. Build via wasm32-unknown-unknown and copy artifact to apps/web/public.
- Exact-cosine similarity indexes 128-dimensional **lexical hashed vectors**, not learned embeddings, in a bounded 512-entry Rust WASM index.
- IndexedDB locally stores up to 250 origin-isolated prompt/response trace records and feedback ratings; feedback rejects disfavored memories.
- Retrieval can improve continuity, but it neither trains nor modifies LFM3 model weights.
- Users can export JSON or erase all records. Origin/profile changes do not share storage. Local device/extension security still matters.
- Recalled text is explicitly untrusted, but this does not guarantee prompt-injection immunity.

## Federation: NOT deployed
- Default off. No raw conversations or trace events upload to the server.
- Prior to enabling *optional* federation: explicit revocable consent, field-level redaction, deletion, retention, minimization, rate limits, origin-independent abuse controls, staging isolation, provenance review, encrypted transport, auditable receipts and poisoning defenses.
- Prefer de-identified diagnostic metrics to raw text when possible. Do not silently collect conversations from public users.
- Never ship service tokens or tailnet credentials in browser code.

## Harness evolution: NOT autonomous self-modifying code
- Current bounded harness: last 8 role messages, 2 recalled excerpts, max 256 output tokens and user feedback excluding disfavored memories.
- Candidate policy updates require signed versioned artifacts, independent evaluation, canary and rollback.
- No executing untrusted model-generated JavaScript or unseen system-policy rewrites.

## Verification and deploy
1. Rust unit test, Node tests, Next production build.
2. Anonymous / and /sensorgraft_vector.wasm must return HTTP 200; private /chat stays private in latest source.
3. Validate real model inference/decoding and WebGPU/CPU performance on actual browsers. Successful build alone does NOT imply tested inference.
4. Preserve the prior production web image; deploy only new public files and pinned browser runtime without touching databases/API/private routes.
5. Verify public site and rollback on regressions.
