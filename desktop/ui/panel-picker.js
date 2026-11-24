// The model picker (H5): one component for every place the panel lets you
// choose a model. A button shows the current choice; it opens a search box
// over four groups (your keys, this computer, free and paid on OrcaRouter)
// with prices and tags. Models that can't be used say why; choosing one
// explains what would make it work instead of failing silently.
import { pickerChoice, pickerView } from "./panel-lib.js";

const CHEVRON =
  '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>';

let pickerSeq = 0;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

// opts: { label, value, defaultLabel, defaultDetail, load() -> {groups},
//   context() -> {hostedConfigured, hostedModels}, onChoose(id|null),
//   onNeedsKey(), onNeedsPaid() -> Promise<boolean>, onResize() }
export function createPicker(opts) {
  const id = `pick-${++pickerSeq}`;
  let value = opts.value ?? null;
  let groups = null;
  let active = 0;
  let options = []; // [{node, item|null}]

  const labelEl = el("span", { class: "field-label", id: `${id}-label` }, opts.label);
  const valEl = el("span", { class: "pick-val" });
  const btn = el("button", { class: "pick-btn", type: "button", id: `${id}-btn`, "aria-haspopup": "listbox", "aria-expanded": "false", "aria-labelledby": `${id}-label ${id}-btn` }, valEl);
  btn.insertAdjacentHTML("beforeend", CHEVRON);
  const search = el("input", {
    class: "pick-search", type: "search", role: "combobox", "aria-expanded": "true", "aria-controls": `${id}-list`,
    "aria-autocomplete": "list", "aria-label": `Search models for ${opts.label}`, autocomplete: "off", spellcheck: "false",
    placeholder: "Search models",
  });
  const list = el("div", { class: "pick-list", role: "listbox", id: `${id}-list`, "aria-label": opts.label, tabindex: "-1" });
  const noteText = el("span", {});
  const noteBtn = el("button", { class: "btn btn-primary btn-sm", type: "button" });
  const note = el("div", { class: "pick-note", role: "status", hidden: true }, noteText, noteBtn);
  const status = el("p", { class: "pick-status", "aria-live": "polite" });
  const fine = el("p", { class: "fine" }, "OrcaRouter models need an OrcaRouter key; free models cost nothing.");
  const pop = el("div", { class: "picker", hidden: true }, search, list, note, status, fine);
  const root = el("div", { class: "field" }, labelEl, btn, pop);

  function showValue() {
    valEl.className = value ? "pick-val mono" : "pick-val muted";
    valEl.textContent = value || opts.defaultLabel;
  }
  showValue();

  function setActive(i) {
    if (!options.length) return;
    active = Math.max(0, Math.min(options.length - 1, i));
    options.forEach((o, n) => o.node.classList.toggle("active", n === active));
    const node = options[active].node;
    search.setAttribute("aria-activedescendant", node.id);
    node.scrollIntoView({ block: "nearest" });
  }

  function renderList() {
    if (!groups) {
      list.replaceChildren(el("p", { class: "pick-empty" }, "Loading models…"));
      return;
    }
    const ctx = opts.context();
    const v = pickerView(groups, { query: search.value, ...ctx });
    search.placeholder = `Search ${v.total} models`;
    options = [];
    const nodes = [];
    let n = 0;
    const option = (item, content) => {
      const node = el("div", {
        class: `pick-opt${item && !item.available ? " off" : ""}`,
        role: "option",
        id: `${id}-o${n++}`,
        "aria-selected": String((item ? item.id : null) === value),
        "aria-disabled": item && !item.available ? "true" : null,
      }, ...content);
      node.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the search box
      node.addEventListener("click", () => choose(item));
      options.push({ node, item });
      return node;
    };
    if (!search.value.trim()) {
      nodes.push(option(null, [el("span", { class: "po-main" }, el("b", {}, opts.defaultLabel), el("small", {}, opts.defaultDetail))]));
    }
    for (const g of v.groups) {
      const gid = `${id}-g-${g.id}`;
      const grp = el("div", { role: "group", "aria-labelledby": gid }, el("div", { class: "pick-group", id: gid, role: "presentation" }, g.label));
      for (const item of g.items) {
        grp.append(option(item, [
          el("span", { class: "po-main" }, el("b", { class: "mono" }, item.name), el("small", {}, item.price), item.available ? null : el("small", { class: "why" }, item.reason)),
          el("span", { class: `tag ${item.tagTone}` }, item.tag),
        ]));
      }
      nodes.push(grp);
    }
    if (!options.length) nodes.push(el("p", { class: "pick-empty" }, "No models match."));
    list.replaceChildren(...nodes);
    setActive(0);
  }

  async function load(force = false) {
    if (groups && !force) return;
    try {
      groups = (await opts.load()).groups;
    } catch (err) {
      groups = [];
      status.textContent = `Couldn't load models: ${err.message}`;
    }
    renderList();
    opts.onResize?.();
  }

  function open() {
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    note.hidden = true;
    search.value = "";
    renderList();
    search.focus();
    load();
    document.addEventListener("mousedown", outside, true);
    opts.onResize?.();
  }

  function close(focusButton = true) {
    if (pop.hidden) return;
    pop.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", outside, true);
    if (focusButton) btn.focus();
    opts.onResize?.();
  }

  function outside(e) {
    if (!root.contains(e.target)) close(false);
  }

  function explain(text, action, run) {
    noteText.textContent = text;
    noteBtn.hidden = !action;
    noteBtn.textContent = action || "";
    noteBtn.onclick = run || null;
    note.hidden = false;
    opts.onResize?.();
  }

  async function choose(item) {
    if (!item) return commit(null);
    const choice = pickerChoice(item.model, item.groupId, opts.context());
    if (choice.kind === "select") return commit(item.id);
    if (choice.kind === "needs_key") {
      explain(`${item.name} needs an OrcaRouter key.`, "Get an OrcaRouter key", () => opts.onNeedsKey());
    } else if (choice.kind === "needs_paid") {
      explain(`${item.name} is a paid model, and paid models are off.`, "Use paid models", async () => {
        noteBtn.disabled = true;
        const ok = await opts.onNeedsPaid();
        noteBtn.disabled = false;
        if (!ok) return;
        note.hidden = true;
        await load(true);
        await commit(item.id);
      });
    } else {
      explain(`${item.name} can't be used right now: ${item.reason.toLowerCase()}.`, null, null);
    }
  }

  async function commit(next) {
    const before = value;
    value = next;
    showValue();
    close();
    try {
      await opts.onChoose(next);
    } catch {
      value = before;
      showValue();
    }
  }

  btn.addEventListener("click", () => (pop.hidden ? open() : close()));
  search.addEventListener("input", () => {
    note.hidden = true;
    renderList();
  });
  search.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") setActive(active + 1);
    else if (e.key === "ArrowUp") setActive(active - 1);
    else if (e.key === "Home" && e.ctrlKey) setActive(0);
    else if (e.key === "Enter") {
      if (options[active]) choose(options[active].item);
    } else if (e.key === "Escape") close();
    else return;
    e.preventDefault();
    e.stopPropagation();
  });

  return {
    root,
    setValue(v) {
      value = v ?? null;
      showValue();
    },
    isOpen: () => !pop.hidden,
    reload: () => load(true),
  };
}
