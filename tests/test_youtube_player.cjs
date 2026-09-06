const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8");

function harness(ready = true) {
  const elements = new Map();
  class Element {
    constructor() { this.value = "35"; this.textContent = ""; this.hidden = false; this.open = false; this.handlers = {}; this.children = []; this.classList = {toggle(){},add(){},remove(){}}; }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    append(...items) { this.children.push(...items); }
    replaceChildren() { this.children = []; }
    setAttribute() {}
    showModal() { this.open = true; }
    close() { this.open = false; }
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const timers = new Map();
  let serial = 0, now = 0, events;
  const frame = new Element();
  const loads = [];
  const requests = [];
  let respond = async () => ({results: []});
  const player = {
    id: "", stopped: 0,
    loadVideoById(id) { this.id = id; loads.push(id); },
    getVideoUrl() { return this.id ? "https://www.youtube.com/watch?v=" + this.id : ""; },
    getIframe() { return frame; },
    setVolume() {}, playVideo() {}, pauseVideo() {},
    stopVideo() { this.stopped++; },
  };
  const context = vm.createContext({
    console, URL, URLSearchParams, Date, Set, Number,
    location: {origin:"http://127.0.0.1:8770",href:"http://127.0.0.1:8770/",protocol:"http:",host:"127.0.0.1:8770",search:""},
    document: {getElementById:element, createElement:()=>new Element(), querySelectorAll:()=>[], head:new Element()},
    setTimeout(fn, delay) { const id = ++serial; timers.set(id, {fn, at:now+delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() {},
    WebSocket: class {},
    YT: {PlayerState:{PLAYING:1,PAUSED:2,ENDED:0}, Player: function(id, options) { events = options.events; return player; }},
    async fetch(url, options) {
      requests.push({url,body:options?.body ? JSON.parse(options.body) : null});
      return {ok:true, json:()=>respond(url, options)};
    },
  });
  context.window = context;
  vm.runInContext(source, context, {filename:"app.js"});
  vm.runInContext('state.status = {youtube_enabled:true, music_backend:"youtube"}', context);
  context.onYouTubeIframeAPIReady();
  if (ready) events.onReady();
  const run = code => vm.runInContext(code, context);
  const pool = n => Array.from({length:n},(_,i)=>({video_id:String(i).padStart(11,"0"),title:"Song "+i,url:"https://youtu.be/"+String(i).padStart(11,"0")}));
  const seed = n => run("renderSearchResults("+JSON.stringify(pool(n))+', "youtube"); playYouTubeResult(0);');
  const advance = ms => {
    now += ms;
    for (let guard=0; guard<100; guard++) {
      const due = [...timers].find(([,timer])=>timer.at <= now);
      if (!due) return;
      timers.delete(due[0]); due[1].fn();
    }
    throw new Error("unbounded timer loop");
  };
  return {run,pool,seed,advance,events,player,frame,loads,requests,element,timers,setResponse(fn){respond=fn;}};
}

for (const error of [2,5,100,101,150,153]) {
  test("IFrame error "+error+" automatically advances to a different candidate", () => {
    const h = harness(); h.seed(3);
    h.events.onError({target:h.player,data:error});
    assert.equal(h.run("youtubeResults[0].playback_status"),"failed");
    h.advance(0);
    assert.deepEqual(h.loads, ["00000000000","00000000001"]);
  });
}

test("multiple blocked candidates lead to the first PLAYING result and stop fallback", () => {
  const h = harness(); h.seed(4);
  for (const data of [101,150]) { h.events.onError({target:h.player,data}); h.advance(0); }
  h.events.onStateChange({target:h.player,data:1});
  h.advance(60000);
  assert.deepEqual(h.loads,["00000000000","00000000001","00000000002"]);
  assert.equal(h.run("youtubeResults[2].playback_status"),"playing");
  assert.equal(h.element("search-message").textContent,"Läuft: Song 2");
  assert.equal(h.timers.size,0);
});

test("exhaustion stops and hides the dead player and exposes external link", () => {
  const h = harness(); h.seed(2);
  for (const data of [101,150]) {h.events.onError({target:h.player,data}); h.advance(0);}
  assert.equal(h.element("search-message").textContent,"Kein einbettbarer YouTube-Treffer gefunden.");
  assert.equal(h.frame.hidden,true);
  assert.equal(h.element("music-open-youtube").hidden,false);
  assert.match(h.element("music-open-youtube").href,/00000000001$/);
  assert.equal(h.loads.length,2);
});

test("duplicate errors do not skip an extra candidate", () => {
  const h = harness();h.seed(3);
  h.events.onError({data:101});h.events.onError({data:150});h.advance(0);
  assert.equal(h.loads.length,2);
});

test("timeout advances but browser autoplay denial does not burn the pool", () => {
  const h = harness();h.seed(3);h.advance(12000);
  assert.equal(h.loads.length,2);
  h.events.onAutoplayBlocked({target:h.player});h.advance(60000);
  assert.equal(h.loads.length,2);
  assert.equal(h.run("youtubeResults[1].playback_status"),"autoplay_blocked");
  assert.match(h.element("search-message").textContent,/Autoplay/);
});

test("pause and stop cancel pending fallback timers", () => {
  for (const fn of ["pauseYouTube", "stopYouTube"]) {
    const h = harness();h.seed(3);h.events.onError({data:101});
    h.run(fn+"()");h.advance(60000);
    assert.equal(h.loads.length,1);
  }
});

test("frontend independently deduplicates and caps attempts at twenty", () => {
  const h = harness();const pool=h.pool(25);
  h.run('renderSearchResults('+JSON.stringify([...pool,...pool])+',"youtube");playYouTubeResult(0);');
  for(let i=0;i<20;i++){h.events.onError({data:101});h.advance(0);}
  assert.equal(h.loads.length,20);
  assert.equal(new Set(h.loads).size,20);
  assert.equal(h.frame.hidden,true);
});

test("manual search and chat both search once and start the first result", async () => {
  for (const chat of [false,true]) {
    const h=harness();h.setResponse(async()=>({results:h.pool(3)}));
    h.element("search-kind").value="youtube";h.element("search-query").value="Nightcall";
    if(chat) await h.run('enqueueMusicRequest({query:"Nightcall"})');
    else await h.element("search-form").handlers.submit({preventDefault(){}});
    assert.deepEqual(h.requests,[{url:"/api/search",body:{query:"Nightcall",kind:"youtube"}}]);
    assert.deepEqual(h.loads,["00000000000"]);
    assert.match(h.element("search-message").textContent,/Prüfe Wiedergabe/);
  }
});

test("search completion before IFrame readiness starts without another click", async () => {
  const h=harness(false);h.setResponse(async()=>({results:h.pool(2)}));
  await h.run('searchAndPlayYouTube("Nightcall")');
  assert.equal(h.loads.length,0);h.events.onReady();
  assert.deepEqual(h.loads,["00000000000"]);
  assert.equal(h.requests.length,1);
});

test("newer requests win over stale search responses", async () => {
  const h=harness();const pending=[];
  h.setResponse(()=>new Promise(resolve=>pending.push(resolve)));
  const first=h.run('searchAndPlayYouTube("Old")');
  const second=h.run('searchAndPlayYouTube("New")');
  await new Promise(setImmediate);
  pending[1]({results:h.pool(1).map(r=>({...r,title:"New"}))});await second;
  pending[0]({results:h.pool(1).map(r=>({...r,title:"Old"}))});await first;
  assert.equal(h.run("youtubeResults[0].title"),"New");
  assert.equal(h.loads.length,1);
});

test("stop while searching cancels later automatic playback", async () => {
  const h=harness();let resolve;
  h.setResponse(()=>new Promise(r=>resolve=r));
  const search=h.run('searchAndPlayYouTube("Nightcall")');
  await new Promise(setImmediate);
  h.run("stopYouTube()");resolve({results:h.pool(2)});await search;
  assert.equal(h.loads.length,0);
});

test("Spotify errors stay in Spotify UI and YouTube media opening never polls Spotify", async () => {
  const h=harness();h.seed(1);h.events.onStateChange({data:1});
  h.setResponse(async()=>({error:"Spotify 403"}));
  await h.run("loadSpotifyStatus()");
  assert.equal(h.element("search-message").textContent,"Läuft: Song 0");
  assert.equal(h.element("spotify-message").textContent,"Spotify 403");
  h.requests.length=0;
  h.element("media-btn").handlers.click();
  assert.equal(h.requests.length,0);
});

test("web search rendering leaves the current music fallback intact", () => {
  const h=harness();h.seed(3);
  h.run('renderSearchResults([{title:"Web",url:"https://example.test"}],"web")');
  h.events.onError({data:101});h.advance(0);
  assert.equal(h.loads.length,2);
});

test("late callbacks for old video cannot mark the new result as playing", () => {
  const h=harness();h.seed(3);h.events.onError({data:101});h.advance(0);
  h.player.id="00000000000";h.events.onStateChange({data:1});
  assert.equal(h.run("youtubeResults[1].playback_status"),"testing");
});
