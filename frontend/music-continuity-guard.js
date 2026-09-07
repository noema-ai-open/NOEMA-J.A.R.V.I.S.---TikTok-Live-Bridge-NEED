(() => {
  if (window.__noemaMusicContinuityGuardInstalled) return;
  const originalSearchAndPlay = window.searchAndPlayYouTube;
  if (typeof originalSearchAndPlay !== "function") return;

  window.__noemaMusicContinuityGuardInstalled = true;
  let activeSearches = 0;

  const wrapPlayerConstructor = () => {
    if (!window.YT?.Player || window.YT.Player.__noemaContinuityWrapped) return;

    const OriginalPlayer = window.YT.Player;
    function GuardedPlayer(...args) {
      const player = new OriginalPlayer(...args);
      const originalStop = typeof player.stopVideo === "function"
        ? player.stopVideo.bind(player)
        : null;

      if (originalStop) {
        player.stopVideo = (...stopArgs) => {
          // app.js stops the current song before a replacement search even
          // knows whether it has a usable result. Keep the current track alive
          // during that search. A successful loadVideoById still switches to
          // the requested title normally.
          if (activeSearches > 0) return undefined;
          return originalStop(...stopArgs);
        };
      }
      return player;
    }

    Object.setPrototypeOf(GuardedPlayer, OriginalPlayer);
    GuardedPlayer.prototype = OriginalPlayer.prototype;
    GuardedPlayer.__noemaContinuityWrapped = true;
    window.YT.Player = GuardedPlayer;
  };

  const originalYouTubeReady = window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady = function guardedYouTubeReady(...args) {
    wrapPlayerConstructor();
    if (typeof originalYouTubeReady === "function") {
      return originalYouTubeReady.apply(this, args);
    }
    return undefined;
  };

  // In case the API was already present before this guard was injected.
  wrapPlayerConstructor();

  window.searchAndPlayYouTube = async function continuitySearchAndPlay(...args) {
    activeSearches += 1;
    try {
      return await originalSearchAndPlay.apply(this, args);
    } finally {
      activeSearches = Math.max(0, activeSearches - 1);
    }
  };
})();
