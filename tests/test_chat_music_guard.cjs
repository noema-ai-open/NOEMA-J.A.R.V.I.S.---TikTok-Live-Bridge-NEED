const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../frontend/chat-music-guard.js"), "utf8");

function harness() {
  const dialog = {
    open: false,
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
  let calls = 0;
  const context = vm.createContext({
    document: {getElementById: (id) => id === "media-dialog" ? dialog : null},
    searchAndPlayYouTube: async () => {
      calls += 1;
      dialog.showModal();
      return "ok";
    },
  });
  context.window = context;
  vm.runInContext(source, context, {filename: "chat-music-guard.js"});
  return {context, dialog, calls: () => calls};
}

test("viewer-triggered music search is closed before stream capture can show it", async () => {
  const h = harness();
  await h.context.searchAndPlayYouTube("Nightcall");
  assert.equal(h.calls(), 1);
  assert.equal(h.dialog.open, false);
});

test("operator-opened media dialog remains visible during manual search", async () => {
  const h = harness();
  h.dialog.showModal();
  await h.context.searchAndPlayYouTube("Nightcall");
  assert.equal(h.calls(), 1);
  assert.equal(h.dialog.open, true);
});
