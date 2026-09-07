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
  const makeButton = () => ({
    capture: [],
    bubble: [],
    addEventListener(type, fn, options) {
      if (type !== "click") return;
      (options === true ? this.capture : this.bubble).push(fn);
    },
    click() {
      for (const fn of this.capture) fn({type:"click"});
      for (const fn of this.bubble) fn({type:"click"});
    },
  });
  const media = makeButton();
  const focus = makeButton();
  // Existing app.js handlers are registered before the guard script.
  media.addEventListener("click", () => dialog.showModal());
  focus.addEventListener("click", () => {});

  const timers = [];
  const context = vm.createContext({
    document: {
      getElementById(id) {
        if (id === "media-dialog") return dialog;
        if (id === "media-btn") return media;
        if (id === "focus-btn") return focus;
        return null;
      },
    },
    setTimeout(fn) { timers.push(fn); return timers.length; },
  });
  context.window = context;
  vm.runInContext(source, context, {filename: "chat-music-guard.js"});
  return {context, dialog, media, focus, flush(){ while (timers.length) timers.shift()(); }};
}

test("viewer-triggered programmatic media opening stays hidden from stream capture", () => {
  const h = harness();
  h.dialog.showModal();
  assert.equal(h.dialog.open, false);
});

test("operator media button can still open the dialog manually", () => {
  const h = harness();
  h.media.click();
  assert.equal(h.dialog.open, true);
  h.flush();
  h.dialog.close();
  h.dialog.showModal();
  assert.equal(h.dialog.open, false);
});

test("TikTok Show button closes an already-open operator dialog", () => {
  const h = harness();
  h.media.click();
  assert.equal(h.dialog.open, true);
  h.focus.click();
  assert.equal(h.dialog.open, false);
});
