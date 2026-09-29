import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import Underline from "@tiptap/extension-underline";
import StarterKit from "@tiptap/starter-kit";
import { Editor } from "@tiptap/core";

const EMPTY = { type: "doc", content: [{ type: "paragraph" }] };

const autosaveTimers = new WeakMap();

function scheduleAutosave(host, editor) {
  const url = host.dataset.autosave;
  if (!url) return;
  const previous = autosaveTimers.get(host);
  if (previous) clearTimeout(previous);
  autosaveTimers.set(
    host,
    setTimeout(() => {
      autosave(host, editor);
    }, 2000),
  );
}

async function autosave(host, editor) {
  const form = host.closest("form");
  const title = form?.querySelector('[name="title"]')?.value?.trim();
  const base = form?.querySelector('[name="base_revision_id"]')?.value;
  if (!form || !title || !base) return;
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  const subtitle = form.querySelector('[name="subtitle"]')?.value?.trim() || null;
  const excerpt = form.querySelector('[name="excerpt"]')?.value?.trim() || null;
  const response = await fetch(host.dataset.autosave, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": token || "",
    },
    body: JSON.stringify({
      base_revision_id: base,
      kind: "autosave",
      content: { title, subtitle, excerpt, body: editor.getJSON() },
    }),
  });
  if (!response.ok) return;
  const saved = await response.json();
  const input = form.querySelector('[name="base_revision_id"]');
  if (input && saved.id) input.value = saved.id;
}

function run(editor, command) {
  const chain = editor.chain().focus();
  const commands = {
    bold: () => chain.toggleBold().run(),
    italic: () => chain.toggleItalic().run(),
    underline: () => chain.toggleUnderline().run(),
    strike: () => chain.toggleStrike().run(),
    h2: () => chain.toggleHeading({ level: 2 }).run(),
    h3: () => chain.toggleHeading({ level: 3 }).run(),
    bullet: () => chain.toggleBulletList().run(),
    ordered: () => chain.toggleOrderedList().run(),
    quote: () => chain.toggleBlockquote().run(),
    rule: () => chain.setHorizontalRule().run(),
    link: () => {
      const previous = editor.getAttributes("link").href ?? "https://";
      const href = window.prompt("URL", previous);
      if (href === null) return;
      if (href === "") chain.unsetLink().run();
      else chain.setLink({ href }).run();
    },
    image: () => {
      const src = window.prompt("Media URL", "/media/");
      if (!src) return;
      const alt = window.prompt("Alt text", "");
      if (!alt || !alt.trim()) return;
      chain.setImage({ src: src.trim(), alt: alt.trim() }).run();
    },
  };
  commands[command]?.();
}

export function mountEditors(root = document) {
  root.querySelectorAll("[data-richtext]").forEach((host) => {
    if (host.dataset.mounted === "1") return;
    const surface = host.querySelector("[data-editor]");
    const input = host.querySelector("textarea");
    if (!surface || !input) return;
    host.dataset.mounted = "1";

    let content = EMPTY;
    if (input.value.trim()) {
      try {
        content = JSON.parse(input.value);
      } catch {
        content = EMPTY;
      }
    }

    const editor = new Editor({
      element: surface,
      extensions: [
        StarterKit.configure({ heading: { levels: [2, 3, 4] } }),
        Underline,
        Link.configure({ openOnClick: false, autolink: false }),
        Image.configure({ inline: true }),
        Placeholder.configure({ placeholder: host.dataset.placeholder || "" }),
      ],
      content,
      editorProps: {
        attributes: {
          dir: host.dataset.dir || "auto",
          class: "px-3 py-2",
        },
      },
      onUpdate: ({ editor: current }) => {
        input.value = JSON.stringify(current.getJSON());
        scheduleAutosave(host, current);
      },
    });
    input.value = JSON.stringify(editor.getJSON());

    host.querySelectorAll("[data-cmd]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        run(editor, button.dataset.cmd);
      });
    });
  });
}
