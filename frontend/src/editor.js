import { Editor, Extension, InputRule } from "@tiptap/core";
import CharacterCount from "@tiptap/extension-character-count";
import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import {
  closeDoubleQuote,
  closeSingleQuote,
  emDash,
  openDoubleQuote,
  openSingleQuote,
} from "@tiptap/extension-typography";
import StarterKit from "@tiptap/starter-kit";
import { Fragment, Slice } from "@tiptap/pm/model";

const EMPTY = { type: "doc", content: [{ type: "paragraph" }] };

const MARKS = new Set(["bold", "italic", "underline", "strike", "code", "link"]);

const ACTIVE = {
  bold: (editor) => editor.isActive("bold"),
  italic: (editor) => editor.isActive("italic"),
  underline: (editor) => editor.isActive("underline"),
  strike: (editor) => editor.isActive("strike"),
  code: (editor) => editor.isActive("code"),
  h2: (editor) => editor.isActive("heading", { level: 2 }),
  h3: (editor) => editor.isActive("heading", { level: 3 }),
  h4: (editor) => editor.isActive("heading", { level: 4 }),
  bullet: (editor) => editor.isActive("bulletList"),
  ordered: (editor) => editor.isActive("orderedList"),
  quote: (editor) => editor.isActive("blockquote"),
  "code-block": (editor) => editor.isActive("codeBlock"),
  link: (editor) => editor.isActive("link"),
};

export function allowedHref(href) {
  if (typeof href !== "string") return false;
  const value = href.trim();
  if (!value || /\s/.test(value)) return false;
  if (value.startsWith("/") && !value.startsWith("//")) return true;
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return false;
  }
  if (!["http:", "https:", "mailto:"].includes(parsed.protocol)) return false;
  if (parsed.protocol === "mailto:") return true;
  return Boolean(parsed.host);
}

export function liftImages(node) {
  if (!node || typeof node !== "object" || !Array.isArray(node.content)) return node;
  const content = [];
  for (const child of node.content) {
    if (
      child?.type === "paragraph" &&
      Array.isArray(child.content) &&
      child.content.some((item) => item?.type === "image")
    ) {
      let inline = [];
      const flush = () => {
        if (!inline.length) return;
        content.push({ ...child, content: inline });
        inline = [];
      };
      for (const item of child.content) {
        if (item?.type === "image") {
          flush();
          content.push(item);
        } else {
          inline.push(item);
        }
      }
      flush();
    } else {
      content.push(liftImages(child));
    }
  }
  return { ...node, content };
}

function keepMark(mark) {
  if (!MARKS.has(mark.type.name)) return false;
  if (mark.type.name === "link") return allowedHref(mark.attrs.href || "");
  return true;
}

function cleanNode(node) {
  const marks = node.marks.filter((mark) => keepMark(mark));
  if (node.isText) return node.mark(marks);
  const children = [];
  node.content.forEach((child) => {
    children.push(cleanNode(child));
  });
  const content = Fragment.fromArray(children);
  if (node.type.name === "heading" && ![2, 3, 4].includes(node.attrs.level)) {
    return node.type.create({ ...node.attrs, level: 2 }, content, marks);
  }
  return node.copy(content).mark(marks);
}

function cleanPasted(slice) {
  const children = [];
  slice.content.forEach((node) => {
    children.push(cleanNode(node));
  });
  return new Slice(Fragment.fromArray(children), slice.openStart, slice.openEnd);
}

function onlyWhenLtr(editor, rule) {
  return new InputRule({
    find: rule.find,
    undoable: rule.undoable,
    handler: (props) => {
      if (editor.view.dom.getAttribute("dir") !== "ltr") return null;
      return rule.handler(props);
    },
  });
}

const TypographyLtr = Extension.create({
  name: "typographyLtr",
  addInputRules() {
    const editor = this.editor;
    return [emDash(), openDoubleQuote(), closeDoubleQuote(), openSingleQuote(), closeSingleQuote()].map(
      (rule) => onlyWhenLtr(editor, rule),
    );
  },
});

function wordCount(text) {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function syncToolbar(editor, host) {
  host.querySelectorAll("[data-cmd]").forEach((button) => {
    const command = button.dataset.cmd;
    if (command === "undo") {
      button.disabled = !editor.can().undo();
      return;
    }
    if (command === "redo") {
      button.disabled = !editor.can().redo();
      return;
    }
    const active = ACTIVE[command];
    if (!active) return;
    button.setAttribute("aria-pressed", active(editor) ? "true" : "false");
  });
  const count = host.querySelector("[data-word-count]");
  if (!count) return;
  const pattern = count.dataset.wordPattern || "{count}";
  count.textContent = pattern.replaceAll("{count}", String(editor.storage.characterCount.words()));
}

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

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || "";
}

function pickerMode(dialog) {
  return dialog.querySelector("#body-media-mode")?.value === "lead" ? "lead" : "body";
}

function setPickerCopy(dialog) {
  const lede = dialog.querySelector("#body-media-lede");
  if (!lede) return;
  const lead = pickerMode(dialog) === "lead";
  const text = lead ? dialog.dataset.pickLead : dialog.dataset.pickBody;
  if (text) lede.textContent = text;
}

function refreshChoices(dialog) {
  const choices = dialog.querySelector("#body-media-choices");
  if (!choices || !window.htmx) return;
  const locale = dialog.querySelector("#body-media-locale")?.value || "";
  const query = dialog.querySelector("#body-media-query")?.value || "";
  window.htmx.ajax("GET", "/admin/media/picker", {
    target: choices,
    swap: "innerHTML",
    values: { mode: pickerMode(dialog), locale, q: query },
  });
}

function setStatus(dialog, message) {
  const status = dialog.querySelector("#body-media-status");
  if (!status) return;
  status.hidden = !message;
  status.textContent = message || "";
}

function hidePending(dialog) {
  const pending = dialog.querySelector("#body-media-pending");
  if (pending) pending.hidden = true;
  delete dialog.dataset.pending;
}

function showPending(dialog) {
  const pending = dialog.querySelector("#body-media-pending");
  const input = dialog.querySelector("#body-media-pending-alt");
  if (!pending) return;
  pending.hidden = false;
  if (input) {
    input.value = "";
    input.focus();
  }
  setStatus(dialog, dialog.dataset.altMissing || "");
}

function chooseUploaded(dialog, asset, alt) {
  dialog.dataset.src = `/media/${asset.id}`;
  dialog.dataset.alt = alt;
  dialog.close("chosen");
}

function altForLocale(asset, locale) {
  const row = (asset.translations || []).find((item) => item.locale === locale);
  return (row?.alt_text || "").trim();
}

async function saveAlt(asset, locale, alt, caption) {
  const response = await fetch(`/api/v1/admin/media/${asset.id}/translations`, {
    method: "PUT",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify({ locale, alt_text: alt, caption: caption || null }),
  });
  if (!response.ok) return null;
  return response.json();
}

function clearUpload(dialog) {
  const preview = dialog.querySelector("#body-media-preview");
  const file = dialog.querySelector("#body-media-file");
  const clear = dialog.querySelector("#body-media-clear");
  if (preview?.dataset.objectUrl) {
    URL.revokeObjectURL(preview.dataset.objectUrl);
    delete preview.dataset.objectUrl;
  }
  if (preview) {
    preview.hidden = true;
    preview.removeAttribute("src");
  }
  if (file) file.value = "";
  if (clear) {
    clear.hidden = true;
    clear.textContent = clear.dataset.cancel || clear.textContent;
  }
}

async function uploadFromEditor(dialog, form) {
  const fileInput = form.querySelector("#body-media-file");
  const file = fileInput?.files?.[0];
  if (!file) return;
  const previous = dialog.controller;
  if (previous) previous.abort();
  const controller = new AbortController();
  dialog.controller = controller;
  const clear = dialog.querySelector("#body-media-clear");
  if (clear) {
    clear.hidden = false;
    clear.dataset.cancel = clear.dataset.cancel || clear.textContent;
    clear.textContent = clear.dataset.stop || clear.textContent;
  }
  setStatus(dialog, "");
  hidePending(dialog);
  const body = new FormData();
  body.append("file", file);
  const credit = form.querySelector('[name="credit"]')?.value?.trim();
  if (credit) body.append("credit", credit);
  const typedAlt = form.querySelector('[name="alt_text"]')?.value?.trim() || "";
  let response;
  try {
    response = await fetch("/api/v1/admin/media", {
      method: "POST",
      body,
      signal: controller.signal,
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken() },
    });
  } catch (error) {
    if (error.name === "AbortError") return;
    setStatus(dialog, dialog.dataset.uploadFailed || "");
    return;
  } finally {
    if (dialog.controller === controller) dialog.controller = null;
    if (clear) clear.textContent = clear.dataset.cancel || clear.textContent;
  }
  if (!response.ok) {
    let detail = "";
    try {
      detail = (await response.json()).detail || "";
    } catch {
      detail = "";
    }
    setStatus(dialog, detail || dialog.dataset.uploadFailed || "");
    return;
  }
  const asset = await response.json();
  const locale = dialog.querySelector("#body-media-locale")?.value || "";
  const existing = (asset.translations || []).find((item) => item.locale === locale);
  clearUpload(dialog);
  form.querySelector('[name="credit"]').value = "";
  form.querySelector('[name="alt_text"]').value = "";
  if (typedAlt) {
    const saved = await saveAlt(asset, locale, typedAlt, existing?.caption);
    if (!saved) {
      setStatus(dialog, dialog.dataset.uploadFailed || "");
      refreshChoices(dialog);
      return;
    }
    chooseUploaded(dialog, asset, typedAlt);
    return;
  }
  const generated = altForLocale(asset, locale);
  if (pickerMode(dialog) === "lead") {
    chooseUploaded(dialog, asset, generated || "");
    return;
  }
  if (generated) {
    chooseUploaded(dialog, asset, generated);
    return;
  }
  dialog.dataset.pending = asset.id;
  refreshChoices(dialog);
  showPending(dialog);
}

function bindLibrary(dialog) {
  if (dialog.dataset.bound === "1") return;
  dialog.dataset.bound = "1";
  const clear = dialog.querySelector("#body-media-clear");
  if (clear) clear.dataset.cancel = clear.textContent.trim();
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
      return;
    }
    const pick = event.target.closest("[data-pick]");
    if (!pick || pick.disabled) return;
    const alt = (pick.dataset.alt || "").trim();
    if (pickerMode(dialog) !== "lead" && !alt) return;
    dialog.dataset.src = `/media/${pick.dataset.pick}`;
    dialog.dataset.alt = alt;
    dialog.close("chosen");
  });
  dialog.querySelector("#body-media-file")?.addEventListener("change", () => {
    const file = dialog.querySelector("#body-media-file")?.files?.[0];
    const preview = dialog.querySelector("#body-media-preview");
    const button = dialog.querySelector("#body-media-clear");
    if (preview?.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
    if (!file || !file.type.startsWith("image/") || !preview) {
      if (preview) {
        preview.hidden = true;
        preview.removeAttribute("src");
      }
      if (button && !dialog.controller) button.hidden = true;
      return;
    }
    const url = URL.createObjectURL(file);
    preview.dataset.objectUrl = url;
    preview.src = url;
    preview.hidden = false;
    if (button) button.hidden = false;
  });
  clear?.addEventListener("click", () => {
    if (dialog.controller) {
      dialog.controller.abort();
      dialog.controller = null;
      clear.textContent = clear.dataset.cancel || clear.textContent;
      return;
    }
    clearUpload(dialog);
  });
  dialog.querySelector("#body-media-upload")?.addEventListener("submit", (event) => {
    event.preventDefault();
    uploadFromEditor(dialog, event.currentTarget);
  });
  dialog.querySelector("#body-media-use")?.addEventListener("click", async () => {
    const id = dialog.dataset.pending;
    const alt = dialog.querySelector("#body-media-pending-alt")?.value?.trim();
    if (!id || !alt) return;
    const locale = dialog.querySelector("#body-media-locale")?.value || "";
    const saved = await saveAlt({ id }, locale, alt, null);
    if (!saved) {
      setStatus(dialog, dialog.dataset.uploadFailed || "");
      return;
    }
    chooseUploaded(dialog, { id }, alt);
  });
  dialog.addEventListener("close", () => {
    if (dialog.controller) dialog.controller.abort();
    const modeInput = dialog.querySelector("#body-media-mode");
    if (modeInput) modeInput.value = "body";
    setPickerCopy(dialog);
  });
}

function preparePicker(dialog, mode, locale) {
  bindLibrary(dialog);
  const modeInput = dialog.querySelector("#body-media-mode");
  if (modeInput) modeInput.value = mode;
  if (locale) {
    const localeInput = dialog.querySelector("#body-media-locale");
    if (localeInput) localeInput.value = locale;
  }
  const query = dialog.querySelector("#body-media-query");
  if (query) query.value = "";
  delete dialog.dataset.src;
  delete dialog.dataset.alt;
  clearUpload(dialog);
  hidePending(dialog);
  setStatus(dialog, "");
  setPickerCopy(dialog);
  refreshChoices(dialog);
}

function openLibrary(editor, host) {
  const dialog = document.getElementById("body-media");
  if (!dialog || typeof dialog.showModal !== "function") return;
  preparePicker(dialog, "body", host.dataset.locale || "");
  const onClose = () => {
    dialog.removeEventListener("close", onClose);
    if (dialog.returnValue !== "chosen") return;
    const src = dialog.dataset.src || "";
    const alt = (dialog.dataset.alt || "").trim();
    if (!src || !alt) return;
    editor.chain().focus().setImage({ src, alt }).run();
  };
  dialog.addEventListener("close", onClose);
  dialog.showModal();
}

function openLeadPicker(button) {
  const dialog = document.getElementById("body-media");
  if (!dialog || typeof dialog.showModal !== "function") return;
  preparePicker(dialog, "lead", button.dataset.locale || "");
  const onClose = () => {
    dialog.removeEventListener("close", onClose);
    if (dialog.returnValue !== "chosen") return;
    const match = (dialog.dataset.src || "").match(/\/media\/([^/?#]+)/);
    const id = match ? match[1] : "";
    if (!id) return;
    const input = document.getElementById(button.dataset.input || "");
    const preview = document.getElementById(button.dataset.preview || "");
    if (input) input.value = id;
    if (preview) {
      preview.src = `/media/${id}`;
      preview.hidden = false;
    }
    const clear = button.parentElement?.querySelector("[data-lead-clear]");
    if (clear) clear.hidden = false;
  };
  dialog.addEventListener("close", onClose);
  dialog.showModal();
}

function bindLeadControls(root) {
  root.querySelectorAll("[data-lead-picker]").forEach((button) => {
    if (button.dataset.bound === "1") return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => openLeadPicker(button));
  });
  root.querySelectorAll("[data-lead-clear]").forEach((button) => {
    if (button.dataset.bound === "1") return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.input || "");
      const preview = document.getElementById(button.dataset.preview || "");
      if (input) input.value = "";
      if (preview) {
        preview.hidden = true;
        preview.removeAttribute("src");
      }
      button.hidden = true;
    });
  });
}

function applyDirection(editor, host, dir) {
  const next = dir === "ltr" ? "ltr" : "rtl";
  host.dataset.dir = next;
  editor.view.dom.setAttribute("dir", next);
  const form = host.closest("form");
  const hidden = form?.querySelector('input[name="editor_dir"]');
  if (hidden) hidden.value = next;
  form?.querySelectorAll("[data-writing]").forEach((field) => field.setAttribute("dir", next));
  host.querySelectorAll('[data-cmd="dir"]').forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.value === next ? "true" : "false");
  });
}

function bindLinkDialog(dialog) {
  if (dialog.dataset.bound === "1") return;
  dialog.dataset.bound = "1";
  const input = dialog.querySelector("[data-link-input]");
  const error = dialog.querySelector("[data-link-error]");
  const apply = () => {
    const href = input?.value.trim() || "";
    if (href && !allowedHref(href)) {
      if (error) error.hidden = false;
      input?.focus();
      return;
    }
    dialog.close(href ? "apply" : "remove");
  };
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close("cancel");
  });
  dialog.querySelector("[data-link-apply]")?.addEventListener("click", apply);
  dialog.querySelector("[data-link-remove]")?.addEventListener("click", () => dialog.close("remove"));
  dialog.querySelector("[data-link-cancel]")?.addEventListener("click", () => dialog.close("cancel"));
  input?.addEventListener("input", () => {
    if (error) error.hidden = true;
  });
  input?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    apply();
  });
}

function openLink(editor, host) {
  const dialog = host.querySelector("[data-link-dialog]");
  const input = dialog?.querySelector("[data-link-input]");
  const error = dialog?.querySelector("[data-link-error]");
  if (!dialog || !input || typeof dialog.showModal !== "function") return;
  bindLinkDialog(dialog);
  const { from, to } = editor.state.selection;
  input.value = editor.getAttributes("link").href || "https://";
  if (error) error.hidden = true;
  const onClose = () => {
    dialog.removeEventListener("close", onClose);
    const action = dialog.returnValue;
    if (action !== "apply" && action !== "remove") return;
    const chain = editor.chain().focus().setTextSelection({ from, to });
    if (action === "remove") chain.unsetLink().run();
    else chain.setLink({ href: input.value.trim() }).run();
  };
  dialog.addEventListener("close", onClose);
  dialog.showModal();
  input.focus();
  input.select();
}

function run(editor, command, host, button) {
  const chain = editor.chain().focus();
  const commands = {
    undo: () => chain.undo().run(),
    redo: () => chain.redo().run(),
    bold: () => chain.toggleBold().run(),
    italic: () => chain.toggleItalic().run(),
    underline: () => chain.toggleUnderline().run(),
    strike: () => chain.toggleStrike().run(),
    code: () => chain.toggleCode().run(),
    h2: () => chain.toggleHeading({ level: 2 }).run(),
    h3: () => chain.toggleHeading({ level: 3 }).run(),
    h4: () => chain.toggleHeading({ level: 4 }).run(),
    bullet: () => chain.toggleBulletList().run(),
    ordered: () => chain.toggleOrderedList().run(),
    quote: () => chain.toggleBlockquote().run(),
    "code-block": () => chain.toggleCodeBlock().run(),
    rule: () => chain.setHorizontalRule().run(),
    link: () => openLink(editor, host),
    image: () => openLibrary(editor, host),
    dir: () => applyDirection(editor, host, button?.dataset.value),
  };
  commands[command]?.();
}

export function mountEditors(root = document) {
  bindLeadControls(root);
  root.querySelectorAll("[data-richtext]").forEach((host) => {
    if (host.dataset.mounted === "1") return;
    const surface = host.querySelector("[data-editor]");
    const input = host.querySelector("textarea");
    if (!surface || !input) return;
    host.dataset.mounted = "1";

    let content = EMPTY;
    if (input.value.trim()) {
      try {
        content = liftImages(JSON.parse(input.value));
      } catch {
        content = EMPTY;
      }
    }

    const editor = new Editor({
      element: surface,
      extensions: [
        StarterKit.configure({
          heading: { levels: [2, 3, 4] },
          link: {
            openOnClick: false,
            autolink: true,
            linkOnPaste: true,
            defaultProtocol: "https",
            protocols: ["http", "https", "mailto"],
            isAllowedUri: (url) => allowedHref(url),
            shouldAutoLink: (url) => allowedHref(url),
          },
        }),
        Image.configure({ inline: false }),
        Placeholder.configure({ placeholder: host.dataset.placeholder || "" }),
        CharacterCount.configure({ wordCounter: wordCount }),
        TypographyLtr,
      ],
      content,
      editorProps: {
        attributes: {
          dir: host.dataset.dir || "auto",
          class: "px-3 py-2",
        },
        transformPasted: (slice) => cleanPasted(slice),
      },
      onUpdate: ({ editor: current }) => {
        input.value = JSON.stringify(current.getJSON());
        scheduleAutosave(host, current);
      },
    });
    input.value = JSON.stringify(editor.getJSON());
    editor.on("transaction", () => syncToolbar(editor, host));
    syncToolbar(editor, host);

    host.querySelectorAll("[data-cmd]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        run(editor, button.dataset.cmd, host, button);
      });
    });
  });
}
