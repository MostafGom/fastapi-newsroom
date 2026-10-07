const CAP_MS = 30 * 60 * 1000;

function bucketScroll(pct) {
  if (pct >= 100) return 100;
  if (pct >= 75) return 75;
  if (pct >= 50) return 50;
  if (pct >= 25) return 25;
  return 0;
}

function scrollPct() {
  const root = document.documentElement;
  const max = root.scrollHeight - root.clientHeight;
  if (max <= 0) return 100;
  return bucketScroll(Math.round((root.scrollTop / max) * 100));
}

function clickTarget(anchor) {
  let url;
  try {
    url = new URL(anchor.href, window.location.href);
  } catch {
    return "";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return "";
  return `${url.host}${url.pathname}`.slice(0, 200);
}

export function mountAnalytics(root = document) {
  const node = root.querySelector("[data-analytics-token]");
  if (!node || node.dataset.analyticsBound === "true") return;
  node.dataset.analyticsBound = "true";
  const token = node.dataset.analyticsToken;
  const url = node.dataset.analyticsUrl;
  if (!token || !url || !window.crypto?.randomUUID) return;
  const viewId = window.crypto.randomUUID();
  let accrued = 0;
  let visibleSince = document.visibilityState === "visible" ? performance.now() : null;
  let sent = 0;
  let maxScroll = scrollPct();

  function send(type, extra) {
    const body = JSON.stringify({ token, type, view_id: viewId, ...extra });
    const blob = new Blob([body], { type: "application/json" });
    if (navigator.sendBeacon?.(url, blob)) return;
    fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  }

  function elapsed() {
    const running = visibleSince === null ? 0 : performance.now() - visibleSince;
    return accrued + running;
  }

  function flush() {
    const delta = Math.round(elapsed() - sent);
    if (delta <= 0) return;
    const capped = Math.min(delta, CAP_MS);
    sent += capped;
    send("engagement", { engaged_ms: capped, scroll_pct: maxScroll });
  }

  if (document.visibilityState === "visible") {
    send("page_view", { engaged_ms: 0, scroll_pct: maxScroll });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      if (visibleSince !== null) {
        accrued += performance.now() - visibleSince;
        visibleSince = null;
      }
      flush();
      return;
    }
    visibleSince = performance.now();
  });

  document.addEventListener("pagehide", flush);
  document.addEventListener(
    "scroll",
    () => {
      maxScroll = Math.max(maxScroll, scrollPct());
    },
    { passive: true },
  );
  window.setInterval(() => {
    if (document.visibilityState === "visible") flush();
  }, 30_000);

  document.addEventListener("click", (event) => {
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!anchor) return;
    const inStory = anchor.closest(".article-body");
    if (!inStory && !anchor.hasAttribute("data-track-click")) return;
    const target = clickTarget(anchor);
    if (!target) return;
    send("click", { engaged_ms: 0, scroll_pct: maxScroll, click_target: target });
  });
}
