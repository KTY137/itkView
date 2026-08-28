/* Keep storage keys and allowed values aligned with src/appearance.ts.
   This blocking head script applies the saved palette before CSS can paint. */
(function () {
  var root = document.documentElement;
  var theme = "system";
  var accent = "copper";
  try {
    var savedTheme = localStorage.getItem("itkview.appearance.theme");
    var savedAccent = localStorage.getItem("itkview.appearance.accent");
    if (savedTheme === "light" || savedTheme === "dark") theme = savedTheme;
    if (
      savedAccent === "blue" ||
      savedAccent === "teal" ||
      savedAccent === "violet"
    ) {
      accent = savedAccent;
    }
  } catch (_) {
    // Storage may be blocked; the OS theme and copper accent remain usable.
  }
  var resolved =
    theme === "system"
      ? window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;
  root.dataset.theme = resolved;
  root.dataset.themePreference = theme;
  root.dataset.accent = accent;
})();
