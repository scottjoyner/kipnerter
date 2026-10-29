/**
 * Browser SensorGraft adapter: vector lookup is performed by a compact Rust
 * WASM exact-cosine index. Lexical feature hashing is a v0.1 retrieval baseline,
 * not a learned embedding model or neural weight update.
 */
export const VECTOR_DIMENSION = 128;
const MAX_TOP_K = 3;
function hash(text) {
  let n = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    n ^= text.charCodeAt(i);
    n = Math.imul(n, 16777619);
  }
  return n >>> 0;
}
export function lexicalVector(text) {
  const v = new Float32Array(VECTOR_DIMENSION);
  const terms = String(text).toLowerCase().match(/[\p{L}\p{N}]{2,}/gu) || [];
  for (const term of terms.slice(0, 700)) {
    const key = hash(term);
    v[key % VECTOR_DIMENSION] += (key & 256) ? 1 : -1;
  }
  const norm = Math.hypot(...v);
  if (norm > 0) for (let i = 0; i < v.length; i++) v[i] /= norm;
  return v;
}
export async function createVectorIndex() {
  const response = await fetch("/sensorgraft_vector.wasm", { cache: "force-cache" });
  if (!response.ok) throw new Error("SensorGraft WASM not available");
  const data = await response.arrayBuffer();
  const { instance } = await WebAssembly.instantiate(data, {});
  const wasm = instance.exports;
  if (!wasm.memory || !wasm.sg_insert || !wasm.sg_search) throw new Error("Invalid vector module");
  const bytes = VECTOR_DIMENSION * 4;
  const vecPtr = wasm.sg_alloc(bytes);
  const outPtr = wasm.sg_alloc(MAX_TOP_K * 4);
  if (!vecPtr || !outPtr) throw new Error("WASM memory allocation failed");
  const put = text => {
    const v = lexicalVector(text);
    new Float32Array(wasm.memory.buffer, vecPtr, VECTOR_DIMENSION).set(v);
  };
  return {
    reset() { wasm.sg_reset(); },
    insert(id, text) {
      if (!Number.isSafeInteger(id) || id < 1 || id > 2 ** 32 - 1) return;
      put(text);
      wasm.sg_insert(id, vecPtr, VECTOR_DIMENSION);
    },
    search(text, excluded = 0) {
      put(text);
      const count = wasm.sg_search(vecPtr, VECTOR_DIMENSION, outPtr, MAX_TOP_K, excluded);
      return Array.from(new Uint32Array(wasm.memory.buffer, outPtr, Math.min(count, MAX_TOP_K)));
    },
    close() { wasm.sg_free(vecPtr, bytes); wasm.sg_free(outPtr, MAX_TOP_K * 4); },
  };
}
