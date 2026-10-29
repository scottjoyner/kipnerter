import { test } from "node:test";
import { strict as assert } from "node:assert";
import { readFile } from "node:fs/promises";
import { lexicalVector, VECTOR_DIMENSION } from "./browser-vectors.js";
test("feature hashing deterministic, bounded and normalized", () => {
  const a = lexicalVector("hello quantum vector memory");
  const b = lexicalVector("hello quantum vector memory");
  assert.equal(a.length, VECTOR_DIMENSION);
  assert.deepEqual(a, b);
  assert.ok(Math.abs(Math.hypot(...a) - 1) < 0.00001);
});
test("Rust WASM exact lookup indexes and excludes records", async () => {
  const bytes = await readFile(new URL("../public/sensorgraft_vector.wasm", import.meta.url));
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const w = instance.exports;
  const v = w.sg_alloc(512), o = w.sg_alloc(12);
  new Float32Array(w.memory.buffer, v, 128).set(lexicalVector("alpha beta gamma"));
  assert.equal(w.sg_insert(7, v, 128), 0);
  assert.equal(w.sg_search(v, 128, o, 3, 0), 1);
  assert.equal(new Uint32Array(w.memory.buffer, o, 3)[0], 7);
  assert.equal(w.sg_search(v, 128, o, 3, 7), 0);
  w.sg_free(v, 512);
  w.sg_free(o, 12);
});
