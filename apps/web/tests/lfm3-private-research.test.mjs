import test from "node:test";
import assert from "node:assert/strict";
import { POST, validateResearchInput } from "../app/api/chat/research/route.js";

test("operator research accepts only a short question, never client-supplied endpoints or subtasks", () => {
  assert.equal(validateResearchInput({ question: " What is the implication? " }), "What is the implication?");
  assert.throws(() => validateResearchInput({ question: "x" }), /invalid/);
  assert.throws(() => validateResearchInput({ question: "x".repeat(701) }), /invalid/);
  assert.throws(() => validateResearchInput({ question: "Explain", tools: ["shell"] }), /invalid/);
  assert.throws(() => validateResearchInput({ question: "Explain", model: "other" }), /invalid/);
  assert.throws(() => validateResearchInput({ question: "Explain", baseUrl: "http://127.0.0.1:1234" }), /invalid/);
});
test("cross-origin research is denied before authentication or model calls", async () => {
  const request = new Request("https://kipnerter.com/api/chat/research", {
    method: "POST",
    headers: { origin: "https://attacker.example", "content-type": "application/json" },
    body: JSON.stringify({ question: "Why test this?" }),
  });
  const res = await POST(request);
  assert.equal(res.status, 403);
  assert.match((await res.json()).error, /same-origin/i);
});
test("requests without a trusted Origin header fail closed", async () => {
  const request = new Request("https://kipnerter.com/api/chat/research", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question: "Why test this?" }),
  });
  const res = await POST(request);
  assert.equal(res.status, 403);
});
