(() => {
  if (window.__noemaChatMusicGuardInstalled) return;
  const dialog = document.getElementById("media-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;

  window.__noemaChatMusicGuardInstalled = true;

  const nativeShowModal = dialog.showModal.bind(dialog);
  let operatorPermit = 0;

  function grantOperatorOpen() {
    operatorPermit += 1;
    window.setTimeout(() => {
      operatorPermit = Math.max(0, operatorPermit - 1);
    }, 0);
  }

  // app.js is loaded before this guard. A capture-phase listener still runs
  // before the existing media-button click handler, so only a real/manual
  // operator click receives permission to open the dialog.
  document.getElementById("media-btn")?.addEventListener(
    "click",
    grantOperatorOpen,
    true,
  );

  dialog.showModal = function guardedShowModal() {
    if (operatorPermit <= 0) return undefined;
    return nativeShowModal();
  };

  // Entering/leaving TikTok Show must never leave an already-open operator
  // dialog sitting above the captured dashboard.
  document.getElementById("focus-btn")?.addEventListener(
    "click",
    () => {
      if (dialog.open) dialog.close();
    },
    true,
  );
})();
