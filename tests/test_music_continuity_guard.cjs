const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../frontend/music-continuity-guard.js"),
  "utf8",
);

function harness() {
  let player = null;
  let releaseSearch;
  const pending = new Promise((resolve) => { releaseSearch = resolve; });

  function OriginalPlayer() {
    return {
      stops: 0,
      loads: [],
      stopVideo() { this.stops += 1; },
      loadVideoById(id) { this.loads.push(id); },
    };
  }

  const context = vm.createContext({
    console,
    Math,
    Promise,
    Object,
    YT: {Player: OriginalPlayer},
    onYouTubeIframeAPIReady() {
      player = new context.YT.Player("youtube-player", {});
    },
    async searchAndPlayYouTube() {
      player.stopVideo();
      await pending;
      return "done";
    },
  });
  context.window = context;
  vm.runInContext(source, context, {filename: "music-continuity-guard.js"});
  context.onYouTubeIframeAPIReady();

  return {
    context,
    player: () => player,
    releaseSearch,
  };
}

test("viewer search does not stop the song already playing", async () => {
  const h = harness();
  const request = h.context.searchAndPlayYouTube("Chillout");
  assert.equal(h.player().stops, 0);
  h.releaseSearch();
  await request;
  assert.equal(h.player().stops, 0);
});

test("normal stop works again after the replacement search is finished", async () => {
  const h = harness();
  const request = h.context.searchAndPlayYouTube("Chillout");
  h.releaseSearch();
  await request;
  h.player().stopVideo();
  assert.equal(h.player().stops, 1);
});
