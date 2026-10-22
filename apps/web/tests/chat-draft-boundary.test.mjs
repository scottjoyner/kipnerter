import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../app/chat/ChatComposer.js", import.meta.url), "utf8");
const shell = readFileSync(new URL("../app/chat/console.js", import.meta.url), "utf8");

test("read-only chat accepts bounded accessible questions but not empty sends", () => {
  assert.match(source, /<textarea\b/);
  assert.match(source, /maxLength=\{MAX_DRAFT_CHARS\}/);
  assert.match(source, /onSubmit=\{submit\}/);
  assert.match(source, /disabled=\{!draft\.trim\(\)\}/);
  assert.match(source, /aria-describedby="kipnerter-draft-custody"/);
});

test("browser-only composer does not transmit or persist raw question text", () => {
  assert.doesNotMatch(source, /\b(fetch|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB)\b/);
  assert.match(source, /Discard this unsent message draft/);
  assert.match(source, /onSend\(draft\)/);
});

test("authenticated console responds with in-memory deterministic telemetry only", () => {
  assert.match(shell, /import ChatComposer from "\.\/ChatComposer"/);
  assert.match(shell, /answerFleetQuestion\(question, data/);
  assert.match(shell, /const \[chatDraft, setChatDraft\] = useState\(""\)/);
  assert.match(shell, /setChatHistory\(previous =>/);
  assert.match(shell, /<ChatComposer draft=\{chatDraft\} onDraftChange=\{setChatDraft\} onSend=\{askFleet\}/);
});
