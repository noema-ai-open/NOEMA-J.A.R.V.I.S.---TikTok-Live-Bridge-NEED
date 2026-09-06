const $ = (id) => document.getElementById(id);
const state = { status: {}, events: [], queue: [], settings: null };
const eventIcons = { chat_message: "TXT", gift: "◆", follow: "+", share: "↗", status: "●" };
let youtubePlayer = null;
let youtubeReady = false;
let youtubeApiLoading = false;
let youtubeResults = [];
let youtubeResultIndex = -1;
let youtubeAttempted = new Set();
let youtubeSearchGeneration = 0;
let youtubeAttemptGeneration = 0;
let youtubeTimer = null;
let youtubePendingIndex = -1;
let currentYoutubeVideoId = null;

const youtubeErrorMessages = {
  2: "Ungültige YouTube-Video-ID.",
  5: "Dieses Video kann im eingebetteten HTML5-Player nicht abgespielt werden.",
  100: "Dieses Video wurde entfernt oder ist privat.",
  101: "Der Kanal erlaubt keine eingebettete Wiedergabe.",
  150: "Der Kanal erlaubt keine eingebettete Wiedergabe.",
  153: "YouTube konnte den lokalen Player nicht eindeutig zuordnen.",
};

function setText(id, value) { $(id).textContent = value ?? "—"; }
function connection(id, online) { $(id).classList.toggle("online", Boolean(online)); }

function modelFamily(model, fallback) {
  const value = String(model || "").toLowerCase();
  if (value.includes("claude")) return "CLAUDE";
  if (value.includes("gemini")) return "GEMINI";
  if (value.includes("minimax")) return "MINIMAX";
  if (value.includes("qwen")) return "QWEN";
  return fallback;
}

function renderProviderSwitch(status) {
  const provider = status.provider || "local";
  const localButton = $("provider-local-btn");
  const cloudButton = $("provider-cloud-btn");
  localButton.classList.toggle("active", provider === "local");
  cloudButton.classList.toggle("active", provider === "cloud");
  localButton.setAttribute("aria-pressed", String(provider === "local"));
  cloudButton.setAttribute("aria-pressed", String(provider === "cloud"));
  setText("provider-local-model", modelFamily(status.local_model || status.model, "LOCAL"));
  setText("provider-cloud-model", modelFamily(status.cloud_model, "FALLBACK"));
}

function renderStatus(status) {
  state.status = status;
  const jarvisState = (status.state || "IDLE").toLowerCase();
  const core = $("jarvis-core");
  ["state-idle", "state-listening", "state-processing", "state-speaking", "state-error"].forEach((name) => core.classList.remove(name));
  core.classList.add(`state-${jarvisState}`);
  setText("jarvis-state", status.state || "IDLE");
  setText("core-signal", status.state === "SPEAKING" ? "VOICE ACTIVE" : status.state === "PROCESSING" ? "SYNTHESIZING" : status.state === "LISTENING" ? "SIGNAL LOCK" : status.state === "ERROR" ? "FAULT" : "STANDBY");
  connection("bridge-dot", status.bridge_connected);
  connection("llm-dot", status.llm_connected);
  connection("internet-dot", status.internet_connected);
  setText("bridge-status", status.bridge_connected ? "CONNECTED" : "OFFLINE");
  setText("llm-status", status.llm_connected ? "READY" : "OFFLINE");
  setText("internet-status", !status.internet_enabled ? "DISABLED" : status.internet_connected ? "ONLINE" : status.internet_configured ? "READY" : "NO KEY");
  if (status.interactive_music_enabled && status.youtube_enabled) ensureYouTubeApi();
  setText("provider-status", (status.provider || "local").toUpperCase());
  setText("provider-label", (status.provider || "local").toUpperCase());
  setText("model-status", status.model || "NICHT GESETZT");
  setText("model-label", (status.model || "MODEL NOT SET").toUpperCase());
  setText("tts-status", status.tts_speaking ? "SPEAKING" : "BEREIT");
  setText("queue-status", String(status.queue_length ?? 0));
  const latency = status.last_latency_ms == null ? "—" : `${status.last_latency_ms} ms`;
  setText("latency-status", latency);
  setText("latency-label", latency.toUpperCase());
  setText("current-question", status.current_question?.message || "Keine offene Verarbeitung.");
  setText("current-answer", status.current_answer || status.last_answer || "Bereit.");
  $("pause-btn").innerHTML = status.paused ? "<span>▶</span>AI fortsetzen" : "<span>Ⅱ</span>AI pausieren";
  renderProviderSwitch(status);
  $("error-box").hidden = !status.last_error;
  setText("error-text", status.last_error || "");
}

function renderEvents(events) {
  state.events = events.slice(-100);
  const gifts = state.events.filter((event) => event.event_type === "gift");
  const giftUnits = gifts.reduce((sum, event) => sum + Number(event.metadata?.repeat_count || event.metadata?.count || 1), 0);
  const diamonds = gifts.reduce((sum, event) => sum + Number(event.metadata?.diamond_count || 0) * Number(event.metadata?.repeat_count || event.metadata?.count || 1), 0);
  setText("gift-count", String(giftUnits));
  setText("diamond-count", String(diamonds));
  const feed = $("event-feed");
  feed.replaceChildren();
  if (!state.events.length) {
    const empty = document.createElement("div"); empty.className = "empty-state";
    empty.textContent = "Warte auf TikTok Bridge oder Demo-Event …"; feed.append(empty); return;
  }
  [...state.events].reverse().forEach((event) => {
    const row = document.createElement("article"); row.className = `event ${event.event_type === "gift" ? "gift" : ""} ${event.gift_tier === "spotlight" ? "spotlight" : ""}`;
    const icon = document.createElement("div"); icon.className = "event-icon"; icon.textContent = eventIcons[event.event_type] || "·";
    const body = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = event.user?.display_name || "System";
    const type = document.createElement("div"); type.className = "event-type"; type.textContent = event.event_type + (event.is_question ? " · QUESTION" : "") + (event.gift_tier === "spotlight" ? " · SPOTLIGHT" : "");
    const message = document.createElement("p");
    message.textContent = event.message || (event.event_type === "gift" ? `${event.metadata?.gift_name || "Gift"} × ${event.metadata?.repeat_count || 1}` : event.metadata?.status || "Event");
    body.append(name, type, message);
    const time = document.createElement("time"); time.textContent = new Date(event.timestamp).toLocaleTimeString("de-DE", {hour:"2-digit",minute:"2-digit",second:"2-digit"});
    row.append(icon, body, time); feed.append(row);
  });
  setText("event-count", String(state.events.length));
}

function triggerGift(event) {
  const core = $("jarvis-core");
  const amount = Number(event.metadata?.repeat_count || event.metadata?.count || 1);
  const spotlight = event.gift_tier === "spotlight";
  setText("gift-alert", `${spotlight ? "SPOTLIGHT · " : "+"}${amount} ${event.metadata?.gift_name || "GIFT"}`.toUpperCase());
  core.classList.remove("gift-hit", "spotlight-hit");
  requestAnimationFrame(() => core.classList.add("gift-hit", ...(spotlight ? ["spotlight-hit"] : [])));
  setTimeout(() => core.classList.remove("gift-hit", "spotlight-hit"), 1900);
}

function renderQueue(queue) {
  state.queue = queue;
  const first = queue[0];
  setText("queue-preview", first ? `${first.display_name}: ${first.message}${first.gift ? " · Gift Boost" : ""}` : "Queue leer");
}

function connectDashboard() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/dashboard`);
  socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    if (message.type === "snapshot") { renderStatus(message.status); renderEvents(message.events); renderQueue(message.queue); }
    if (message.type === "status") renderStatus(message.status);
    if (message.type === "event") { renderEvents([...state.events, message.event]); if (message.event.event_type === "gift") triggerGift(message.event); }
    if (message.type === "queue") renderQueue(message.queue);
    if (message.type === "answer_chunk") setText("current-answer", message.text);
    if (message.type === "music_request") enqueueMusicRequest(message.request);
    if (message.type === "music_control") applyMusicControl(message.control);
  };
  socket.onclose = () => setTimeout(connectDashboard, 1500);
}

async function post(path, body) {
  const response = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) { const detail = await response.json().catch(() => ({})); throw new Error(detail.detail || `HTTP ${response.status}`); }
  return response.json();
}

async function loadSettings() {
  const response = await fetch("/api/settings"); state.settings = await response.json();
  const form = $("settings-form");
  Object.entries(state.settings).forEach(([key, value]) => {
    const field = form.elements.namedItem(key); if (!field || key.endsWith("_configured")) return;
    if (key === "provider") {
      const option = form.querySelector(`input[name="provider"][value="${value}"]`);
      if (option) option.checked = true;
    } else if (field.type === "checkbox") field.checked = Boolean(value); else field.value = value ?? "";
  });
  setText("settings-local-model", modelFamily(state.settings.model, "LOCAL"));
  setText("settings-cloud-model", modelFamily(state.settings.cloud_model, "FALLBACK"));
  form.elements.llm_api_key.value = ""; form.elements.cloud_api_key.value = ""; form.elements.brave_api_key.value = "";
  setText("settings-message", "");
  $("settings-message").classList.remove("success");
}

function settingsPayload(form) {
  const data = Object.fromEntries(new FormData(form));
  ["context_length","max_output_tokens","search_result_limit","memory_recent_turns","memory_max_users_ram","memory_max_turns_per_user_disk","memory_retention_days"].forEach((key) => data[key] = Number(data[key]));
  ["temperature","timeout","gift_grace_seconds","search_timeout","music_request_cooldown"].forEach((key) => data[key] = Number(data[key]));
  ["stream","reasoning","cloud_fallback","memory_enabled","internet_enabled","youtube_enabled","interactive_music_enabled","spotify_enabled"].forEach((key) => data[key] = form.elements[key].checked);
  return data;
}

function renderSpotifyStatus(status) {
  connection("spotify-dot", status.connected);
  const title = status.track
    ? `${status.track}${status.artists ? ` · ${status.artists}` : ""}`
    : status.connected ? "Verbunden · kein aktiver Titel" : "Nicht verbunden";
  setText("spotify-now", title);
  setText("spotify-device", status.device || (status.configured ? "Spotify-App öffnen und Gerät aktivieren" : "Client ID fehlt"));
  $("spotify-connect").hidden = Boolean(status.connected);
  $("spotify-disconnect").hidden = !status.connected;
}

async function loadSpotifyStatus() {
  try {
    const response = await fetch("/api/spotify/status");
    const status = await response.json();
    renderSpotifyStatus(status);
    setText("spotify-message", status.error || "");
    return status;
  } catch (error) {
    renderSpotifyStatus({connected:false, configured:false});
    setText("spotify-message", `Spotify: ${error.message}`);
    return null;
  }
}

async function spotifyControl(action, query = null) {
  const playback = await post("/api/spotify/control", {action, query});
  renderSpotifyStatus(playback);
  return playback;
}

function updateYouTubeFallback(result) {
  const fallback = $("music-open-youtube");
  fallback.hidden = !result?.url;
  fallback.href = result?.url || "#";
}

function cancelYouTubeAttempt() {
  window.clearTimeout(youtubeTimer);
  youtubeTimer = null;
  youtubeAttemptGeneration += 1;
  youtubePendingIndex = -1;
}

function currentYouTubeEvent(event) {
  if (event.target && event.target !== youtubePlayer) return false;
  const current = youtubeResults[youtubeResultIndex];
  if (!current || !["testing", "playing", "paused", "autoplay_blocked"].includes(current.playback_status)) return false;
  if (event.data === "timeout") return current.playback_status === "testing";
  // Ignore delayed events for a previous video on the shared IFrame.
  const url = youtubePlayer.getVideoUrl?.();
  const id = url ? new URL(url, location.origin).searchParams.get("v") : null;
  return !id || id === current.video_id;
}

function finishYouTubeFallback() {
  const current = youtubeResults[youtubeResultIndex] || youtubeResults[0];
  cancelYouTubeAttempt();
  youtubeResultIndex = -1;
  currentYoutubeVideoId = null;
  if (youtubeReady) {
    youtubePlayer.stopVideo();
    youtubePlayer.getIframe().hidden = true;
  }
  updateYouTubeFallback(current);
  setText("search-message", "Kein einbettbarer YouTube-Treffer gefunden.");
}

function playYouTubeResult(index, automatic = false) {
  const result = youtubeResults[index];
  if (!result?.video_id) return;
  cancelYouTubeAttempt();
  if (!youtubeReady || !youtubePlayer) {
    youtubePendingIndex = index;
    ensureYouTubeApi();
    setText("search-message", "Musik gefunden. YouTube-Player wird geladen …");
    return;
  }
  youtubeResultIndex = index;
  currentYoutubeVideoId = result.video_id;
  youtubeAttempted.add(result.video_id);
  result.playback_status = "testing";
  const attempt = youtubeAttemptGeneration;
  youtubePlayer.getIframe().hidden = false;
  updateYouTubeFallback(null);
  setText("search-message", `Prüfe Wiedergabe (${youtubeAttempted.size}/${youtubeResults.length}): ${result.title}`);
  youtubeTimer = window.setTimeout(() => {
    if (attempt === youtubeAttemptGeneration && result.playback_status === "testing") {
      handleYouTubeError({data: "timeout"});
    }
  }, 12000);
  youtubePlayer.setVolume(Number($("music-volume").value));
  youtubePlayer.loadVideoById(result.video_id);
}

async function searchAndPlayYouTube(query) {
  const generation = ++youtubeSearchGeneration;
  cancelYouTubeAttempt();
  youtubeResults = [];
  youtubeResultIndex = -1;
  currentYoutubeVideoId = null;
  if (youtubeReady) youtubePlayer.stopVideo();
  if (!$("media-dialog").open) $("media-dialog").showModal();
  $("search-kind").value = "youtube";
  $("search-query").value = query;
  ensureYouTubeApi();
  setText("search-message", `Musiksuche: ${query} …`);
  try {
    const response = await post("/api/search", {query, kind: "youtube"});
    if (generation !== youtubeSearchGeneration) return;
    renderSearchResults(response.results || [], "youtube");
    if (!youtubeResults.length) {
      finishYouTubeFallback();
      return;
    }
    playYouTubeResult(0, true);
  } catch (error) {
    if (generation !== youtubeSearchGeneration) return;
    setText("search-message", `Musiksuche fehlgeschlagen: ${error.message}`);
  }
}

function enqueueMusicRequest(request) {
  if (request?.query) return searchAndPlayYouTube(request.query);
}

function pauseYouTube() {
  ++youtubeSearchGeneration;
  cancelYouTubeAttempt();
  const current = youtubeResults[youtubeResultIndex];
  if (current) current.playback_status = "paused";
  if (youtubeReady) youtubePlayer.pauseVideo();
}

function stopYouTube() {
  ++youtubeSearchGeneration;
  cancelYouTubeAttempt();
  youtubeResultIndex = -1;
  currentYoutubeVideoId = null;
  if (youtubeReady) youtubePlayer.stopVideo();
  setText("search-message", "Musik gestoppt.");
}

function applyMusicControl(control) {
  if (!control?.action) return;
  if (control.action === "pause") { pauseYouTube(); return; }
  ensureYouTubeApi();
  if (!youtubeReady || !youtubePlayer) {
    setText("search-message", "Musiksteuerung wartet auf den Player.");
    return;
  }
  if (control.action === "resume") youtubePlayer.playVideo();
  if (control.action === "skip") {
    const nextIndex = youtubeResults.findIndex((result) => !youtubeAttempted.has(result.video_id));
    if (nextIndex >= 0) playYouTubeResult(nextIndex, true);
    else finishYouTubeFallback();
  }
  if (control.action === "volume_up" || control.action === "volume_down") {
    const change = control.action === "volume_up" ? 10 : -10;
    const volume = Math.max(0, Math.min(100, Number($("music-volume").value) + change));
    $("music-volume").value = String(volume);
    youtubePlayer.setVolume(volume);
  }
}

function handleYouTubeError(event) {
  if (!currentYouTubeEvent(event)) return;
  const current = youtubeResults[youtubeResultIndex];
  cancelYouTubeAttempt();
  current.playback_status = "failed";
  current.playback_error = event.data;
  const nextIndex = youtubeResults.findIndex((result) => !youtubeAttempted.has(result.video_id));
  if (nextIndex < 0) { finishYouTubeFallback(); return; }
  setText("search-message", `${youtubeErrorMessages[event.data] || "YouTube-Wiedergabe fehlgeschlagen."} Nächster Treffer wird getestet …`);
  // Yield once; duplicate error callbacks cannot schedule another advance.
  const attempt = youtubeAttemptGeneration;
  youtubeTimer = window.setTimeout(() => {
    if (attempt === youtubeAttemptGeneration) playYouTubeResult(nextIndex, true);
  }, 0);
}

function handleYouTubeState(event) {
  if (!currentYouTubeEvent(event)) return;
  const current = youtubeResults[youtubeResultIndex];
  if (event.data === YT.PlayerState.PLAYING) {
    cancelYouTubeAttempt();
    current.playback_status = "playing";
    setText("search-message", `Läuft: ${current.title}`);
  } else if (event.data === YT.PlayerState.PAUSED) {
    cancelYouTubeAttempt();
    current.playback_status = "paused";
  } else if (event.data === YT.PlayerState.ENDED) {
    cancelYouTubeAttempt();
    current.playback_status = "ended";
  }
}

function handleYouTubeAutoplayBlocked(event) {
  if (!currentYouTubeEvent(event)) return;
  cancelYouTubeAttempt();
  youtubeResults[youtubeResultIndex].playback_status = "autoplay_blocked";
  setText("search-message", "Der Browser blockiert Autoplay. Einmal Play drücken, damit die Wiedergabe starten darf.");
}

function renderSearchResults(results, kind) {
  const container = $("search-results");
  container.replaceChildren();
  if (kind === "youtube") {
    cancelYouTubeAttempt();
    const seen = new Set();
    youtubeResults = results.filter((result) => {
      if (!/^[A-Za-z0-9_-]{11}$/.test(result.video_id || "") || seen.has(result.video_id)) return false;
      seen.add(result.video_id);
      return true;
    }).slice(0, 20).map((result) => ({...result, playback_status: "unverified"}));
    youtubeResultIndex = -1;
    youtubeAttempted = new Set();
    updateYouTubeFallback(null);
  }
  if (!results.length) {
    const empty = document.createElement("div"); empty.className = "empty-state"; empty.textContent = "Keine Treffer."; container.append(empty); return;
  }
  results.forEach((result) => {
    const card = document.createElement("article"); card.className = "search-result";
    const title = document.createElement("a"); title.href = result.url; title.target = "_blank"; title.rel = "noopener"; title.textContent = result.title;
    const description = document.createElement("p"); description.textContent = result.description || "Keine Beschreibung.";
    card.append(title, description);
    if (result.video_id) {
      const play = document.createElement("button"); play.type = "button"; play.className = "control primary"; play.textContent = "Im Player abspielen";
      play.addEventListener("click", () => {
        ++youtubeSearchGeneration;
        if (kind !== "youtube") renderSearchResults([result], "youtube");
        const index = youtubeResults.findIndex((item) => item.video_id === result.video_id);
        playYouTubeResult(index);
      });
      card.append(play);
    }
    container.append(card);
  });
}

window.onYouTubeIframeAPIReady = () => {
  youtubeApiLoading = false;
  youtubePlayer = new YT.Player("youtube-player", {
    width: "100%",
    height: "260",
    playerVars: {
      playsinline: 1,
      origin: location.origin,
      widget_referrer: location.href,
    },
    events: {
      onReady: () => {
        youtubeReady = true;
        const iframe = youtubePlayer.getIframe();
        iframe.referrerPolicy = "strict-origin-when-cross-origin";
        youtubePlayer.setVolume(Number($("music-volume").value));
        if (youtubePendingIndex >= 0) playYouTubeResult(youtubePendingIndex, true);
      },
      onError: handleYouTubeError,
      onStateChange: handleYouTubeState,
      onAutoplayBlocked: handleYouTubeAutoplayBlocked,
    },
  });
};

function ensureYouTubeApi() {
  if (youtubeReady || youtubeApiLoading || !state.status.youtube_enabled) return;
  youtubeApiLoading = true;
  const script = document.createElement("script");
  script.src = "https://www.youtube.com/iframe_api";
  script.async = true;
  script.onerror = () => { youtubeApiLoading = false; setText("search-message", "YouTube-Player konnte nicht geladen werden."); };
  document.head.append(script);
}

$("pause-btn").addEventListener("click", () => post("/api/control/pause", {paused: !state.status.paused}).catch(showError));
$("skip-btn").addEventListener("click", () => post("/api/control/skip").catch(showError));
$("clear-btn").addEventListener("click", () => post("/api/control/clear").catch(showError));
$("tts-stop-btn").addEventListener("click", () => post("/api/control/tts-stop").catch(showError));
document.querySelectorAll("#provider-switch [data-provider]").forEach((button) => {
  button.addEventListener("click", () => post("/api/settings", {provider:button.dataset.provider}).catch(showError));
});
$("focus-btn").addEventListener("click", () => {
  const enabled = document.body.classList.toggle("focus-mode");
  $("focus-btn").innerHTML = enabled ? "<span>×</span>Show beenden" : "<span>◎</span>TikTok Show";
});
$("media-btn").addEventListener("click", () => { $("media-dialog").showModal(); ensureYouTubeApi(); if (state.status.music_backend === "spotify") loadSpotifyStatus(); else renderSpotifyStatus({connected:state.status.spotify_connected, configured:state.status.spotify_configured}); });
$("close-media").addEventListener("click", () => $("media-dialog").close());
$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("search-query").value.trim();
  const kind = $("search-kind").value;
  setText("search-message", "Suche läuft …");
  try {
    if (kind === "youtube") {
      await searchAndPlayYouTube(query);
      return;
    }
    if (kind === "spotify") {
      const playback = await spotifyControl("play", query);
      setText("search-message", playback.track ? `Spotify: ${playback.track}` : "Spotify-Wiedergabe gestartet.");
      return;
    }
    const response = await post("/api/search", {query, kind});
    renderSearchResults(response.results || [], kind);
    setText("search-message", `${response.results.length} Treffer · Brave Search`);
  } catch (error) {
    setText("search-message", error.message);
  }
});
$("music-play").addEventListener("click", () => { if (youtubeReady) youtubePlayer.playVideo(); });
$("music-pause").addEventListener("click", pauseYouTube);
$("music-stop").addEventListener("click", stopYouTube);
$("music-volume").addEventListener("input", (event) => { if (youtubeReady) youtubePlayer.setVolume(Number(event.target.value)); });
$("spotify-connect").addEventListener("click", () => { window.location.assign("/api/spotify/login"); });
$("spotify-disconnect").addEventListener("click", async () => { await post("/api/spotify/disconnect"); await loadSpotifyStatus(); });
$("spotify-pause").addEventListener("click", () => spotifyControl("pause").catch(showError));
$("spotify-resume").addEventListener("click", () => spotifyControl("resume").catch(showError));
$("spotify-skip").addEventListener("click", () => spotifyControl("skip").catch(showError));
$("spotify-quieter").addEventListener("click", () => spotifyControl("volume_down").catch(showError));
$("spotify-louder").addEventListener("click", () => spotifyControl("volume_up").catch(showError));
$("demo-question").addEventListener("click", () => post("/api/mock/event", {event_type:"chat_message",display_name:"Demo Viewer",user_id:"mock:demo",message:"Wie heißt das Spiel?"}).catch(showError));
$("demo-gift").addEventListener("click", () => post("/api/mock/event", {event_type:"gift",display_name:"Demo Viewer",user_id:"mock:demo"}).catch(showError));
$("demo-donut").addEventListener("click", () => post("/api/mock/event", {event_type:"gift",display_name:"Demo Viewer",user_id:"mock:demo",gift_name:"Donut",diamond_count:30}).catch(showError));
$("settings-btn").addEventListener("click", async () => { await loadSettings(); $("settings-dialog").showModal(); });
$("cancel-settings").addEventListener("click", () => $("settings-dialog").close());
$("test-llm").addEventListener("click", async () => {
  const form = $("settings-form");
  const message = $("settings-message");
  message.classList.remove("success");
  setText("settings-message", "Konfiguration wird geprüft …");
  try {
    await post("/api/settings", settingsPayload(form));
    const result = await post("/api/diagnostics/llm");
    message.classList.add("success");
    setText("settings-message", `BEREIT · ${result.model} · ${result.latency_ms} ms · ${result.answer}`);
  } catch (error) {
    message.classList.remove("success");
    setText("settings-message", error.message);
  }
});
$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget;
  try { await post("/api/settings", settingsPayload(form)); $("settings-dialog").close(); }
  catch (error) { setText("settings-message", error.message); }
});

function showError(error) { $("error-box").hidden = false; setText("error-text", error.message); }
setInterval(() => setText("clock", new Date().toLocaleTimeString("de-DE")), 1000);
connectDashboard();
if (new URLSearchParams(window.location.search).has("spotify")) {
  $("media-dialog").showModal();
  loadSpotifyStatus();
  window.history.replaceState({}, "", "/");
}
