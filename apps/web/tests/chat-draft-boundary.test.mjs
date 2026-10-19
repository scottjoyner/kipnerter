import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../app/chat/ChatComposer.js", import.meta.url), "utf8");
const shell = readFileSync(new URL("../app/chat/console.js", import.meta.url), "utf8");

test("chat composer accepts bounded accessible text but never enables send", () => {
  assert.match(source, /<textarea\b/);
  assert.match(source, /maxLength=\{MAX_DRAFT_CHARS\}/);
  assert.match(source, /onSubmit=\{event => event\.preventDefault\(\)\}/);
  assert.match(source, /type="submit"[^>]*disabled/);
  assert.match(source, /aria-describedby="kipnerter-draft-custody"/);
});

test("draft composer cannot call a backend or persist raw text", () => {
  assert.doesNotMatch(source, /\b(fetch|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB)\b/);
  assert.match(source, /Discard this unsent message draft/);
});

test("chat workspace mounts the composer with parent-owned in-memory state", () => {
  assert.match(shell, /import ChatComposer from "\.\/ChatComposer"/);
  assert.match(shell, /const \[chatDraft, setChatDraft\] = useState\(" "\.trim\(\)\)|const \[chatDraft, setChatDraft\] = useState\(""\)/);
  assert.match(shell, /<ChatComposer draft=\{chatDraft\} onDraftChange=\{setChatDraft\}\s*\/>/);
});
