const RELOAD_ATTEMPTED = "eneo:chunk-reload-attempted";

/** One automatic recovery per tab, shared by route, boot and feature imports. */
export function installChunkRecovery(): () => void {
  const recover = () => {
    try {
      if (sessionStorage.getItem(RELOAD_ATTEMPTED)) return;
      // Persist before reload: it can be cancelled by an unsaved-edit guard.
      sessionStorage.setItem(RELOAD_ATTEMPTED, "1");
    } catch {
      // Without a durable budget, another document could repeat the reload forever.
      return;
    }
    window.location.reload();
  };

  // Keep the original import rejection so existing feature/error boundaries
  // can show it when reload is cancelled or the asset is still unavailable.
  window.addEventListener("vite:preloadError", recover);
  return () => window.removeEventListener("vite:preloadError", recover);
}
