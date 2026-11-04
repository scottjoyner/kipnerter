import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("home and /chat reuse one public chat component and API contract", () => {
  const home = source("../app/page.js");
  const chat = source("../app/chat/page.js");
  const component = source("../app/HomeChat.js");
  assert.match(home, /import HomeChat from ["']\.\/HomeChat["']/);
  assert.match(chat, /import HomeChat from ["']\.\.\/HomeChat["']/);
  assert.match(home, /return <HomeChat \/>/);
  assert.match(chat, /return <HomeChat \/>/);
  assert.match(component, /fetch\(["']\/api\/chat\/completions["']/);
  assert.match(component, /href=["']\/chat["']/);
  assert.match(component, /href=["']\/fleet["']/);
  assert.doesNotMatch(chat, /FleetConsole|api\/portal|getServerSession/);
});

test("operator console is still session-gated and never exposed through public /chat", () => {
  const protectedPage = source("../app/fleet/page.js");
  const consoleComponent = source("../app/chat/console.js");
  assert.match(protectedPage, /getServerSession\(authOptions\)/);
  assert.match(protectedPage, /isAllowed\(session\?\.user\?\.email, session\?\.user\?\.id\)/);
  assert.match(protectedPage, /return <FleetConsole email=\{session\.user\.email\} \/>/);
  assert.match(protectedPage, /callbackUrl=%2Ffleet/);
  assert.match(consoleComponent, /\/api\/portal\//);
  assert.match(consoleComponent, /callbackUrl=%2Ffleet/);
  assert.doesNotMatch(protectedPage, /KIPNERTER_LFM3_ENDPOINTS|Bearer |api\/chat\/completions/);
});
