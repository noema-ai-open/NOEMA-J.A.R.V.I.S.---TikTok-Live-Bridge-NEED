(() => {
  if (window.__noemaChatMusicGuardInstalled) return;
  const originalSearchAndPlay = window.searchAndPlayYouTube;
  if (typeof originalSearchAndPlay !== "function") return;

  window.__noemaChatMusicGuardInstalled = true;
  window.searchAndPlayYouTube = async function guardedSearchAndPlayYouTube(query) {
    const dialog = document.getElementById("media-dialog");
    const operatorOpenedDialog = Boolean(dialog?.open);
    const pending = originalSearchAndPlay.call(this, query);

    // A chat-triggered request starts while the media dialog is closed. The
    // existing player code opens it synchronously; close it again before the
    // browser can paint the next frame so it never appears in stream capture.
    if (!operatorOpenedDialog && dialog?.open) dialog.close();

    try {
      return await pending;
    } finally {
      if (!operatorOpenedDialog && dialog?.open) dialog.close();
    }
  };
})();
