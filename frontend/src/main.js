import Alpine from "alpinejs";
import htmx from "htmx.org";
import { mountAnalytics } from "./analytics.js";
import "./main.css";

window.htmx = htmx;
window.Alpine = Alpine;

document.addEventListener("htmx:configRequest", (event) => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && event.detail.verb !== "get") {
    event.detail.headers["X-CSRF-Token"] = meta.content;
  }
});

async function boot(root) {
  if (!root.querySelector("[data-richtext]")) return;
  const { mountEditors } = await import("./editor.js");
  mountEditors(root);
}

document.addEventListener("DOMContentLoaded", () => {
  boot(document);
  mountAnalytics(document);
  Alpine.start();
});

document.addEventListener("htmx:afterSwap", (event) => {
  boot(event.detail.target);
});
