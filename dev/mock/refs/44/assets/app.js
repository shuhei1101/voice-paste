// PR 44 の画面モックの動き（場面の切り替え・プリセットの種類の切り替え・足す・消す・並べ替え・選ぶ・ホットキーの入力）

/** モック専用の操作列のボタンで、data-scene が一致する場面だけを出す */
const setupScenes = () => {
  const buttons = document.querySelectorAll(".mock-bar [data-scene]");
  const panels = document.querySelectorAll("[data-scene-panel]");
  const show = (name) => {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.scene === name)));
    // 一致しない場面は hidden で隠す
    panels.forEach((p) => { p.hidden = p.dataset.scenePanel !== name; });
  };
  buttons.forEach((b) => b.addEventListener("click", () => show(b.dataset.scene)));
  if (buttons.length > 0) show(buttons[0].dataset.scene);
};

/** 種類のラジオに合わせて、その種類の欄だけを出す */
const applyKind = (radio) => {
  const box = radio.closest("[data-kind-box]");
  box.querySelectorAll("[data-kind-field]").forEach((f) => { f.hidden = f.dataset.kindField !== radio.value; });
  // 案 B は一覧の表の種類の文字も合わせる
  const cell = document.querySelector(`[data-row-kind="${box.dataset.kindBox}"]`);
  if (cell) cell.textContent = radio.parentElement.textContent.trim();
};

/** タイトルの欄に合わせて、プリセットの頭（案 B は一覧の表）の文字を変える */
const applyTitle = (input) => {
  const id = input.dataset.title;
  document.querySelectorAll(`[data-title-view="${id}"]`).forEach((v) => { v.textContent = input.value; });
};

/** 一覧の先頭の「上へ」と末尾の「下へ」を押せなくする */
const refreshMoves = (root) => {
  const items = [...root.querySelectorAll("[data-item]")];
  items.forEach((item, i) => {
    item.querySelector('[data-move="up"]').disabled = i === 0;
    item.querySelector('[data-move="down"]').disabled = i === items.length - 1;
  });
};

/** 一覧が空かどうかで、一覧と「まだ無い」の文を出し分ける */
const refreshEmpty = (root) => {
  const empty = root.querySelectorAll("[data-item]").length === 0;
  root.querySelector("[data-presets-empty]").hidden = !empty;
  root.querySelector("[data-presets-list]").hidden = empty;
  root.querySelectorAll("[data-presets-filled]").forEach((el) => { el.hidden = empty; });
};

/** 案 B: 一覧の表で選んだ行の欄だけを出す */
const selectRow = (row) => {
  const root = row.closest("[data-presets]");
  root.querySelectorAll("[data-item]").forEach((r) => {
    r.dataset.selected = String(r === row);
    // 選んだ行のタイトルのボタンに、選んでいることを読み上げ用に付ける
    const pick = r.querySelector("[data-pick]");
    if (r === row) pick.setAttribute("aria-current", "true");
    else pick.removeAttribute("aria-current");
  });
  root.querySelectorAll("[data-detail]").forEach((d) => { d.hidden = d.dataset.detail !== row.dataset.select; });
};

let added = 0;

/** 「プリセットを足す」: ひな形を写して末尾に足し、タイトルの欄へフォーカスを移す */
const addPreset = (root) => {
  added += 1;
  const id = `${root.id}-new${added}`;
  root.querySelectorAll("template[data-preset-template]").forEach((t) => {
    // 表の行も崩さずに組み立てるため template で解釈する
    const holder = document.createElement("template");
    holder.innerHTML = t.innerHTML.replaceAll("__ID__", id);
    // ひな形ごとに足す先が違う（一覧か、案 B の欄の置き場所か）
    root.querySelector(t.dataset.presetTemplate).append(holder.content);
  });
  refreshMoves(root);
  refreshEmpty(root);
  const row = root.querySelector(`[data-select="${id}"]`);
  if (row) selectRow(row);
  document.getElementById(`${id}-title`).focus();
};

/** プリセットを消し、一覧が空になれば「まだ無い」の文を出す */
const removePreset = (button) => {
  const root = button.closest("[data-presets]");
  const item = button.closest("[data-item]");
  const id = item.dataset.select;
  item.remove();
  // 案 B は選んだ行の欄も消し、先頭の行を選び直す
  if (id) {
    root.querySelector(`[data-detail="${id}"]`).remove();
    const first = root.querySelector("[data-item]");
    if (first) selectRow(first);
  }
  refreshMoves(root);
  refreshEmpty(root);
  root.querySelector("[data-add]").focus();
};

/** プリセットを 1 つ上か下へ動かし、押したボタンにフォーカスを残す */
const movePreset = (button) => {
  const root = button.closest("[data-presets]");
  const item = button.closest("[data-item]");
  if (button.dataset.move === "up") item.previousElementSibling.before(item);
  else item.nextElementSibling.after(item);
  refreshMoves(root);
  // 端まで動いてボタンが押せなくなったら、もう一方のボタンへ移す
  if (button.disabled) item.querySelector(`[data-move="${button.dataset.move === "up" ? "down" : "up"}"]`).focus();
  else button.focus();
};

/** プリセットの一覧の操作を、一覧ごとにまとめて受ける */
const setupPresets = () => {
  document.querySelectorAll("[data-presets]").forEach((root) => {
    refreshMoves(root);
    root.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add]");
      const remove = e.target.closest("[data-remove]");
      const move = e.target.closest("[data-move]");
      const pick = e.target.closest("[data-pick]");
      if (add) addPreset(root);
      else if (remove) removePreset(remove);
      else if (move) movePreset(move);
      else if (pick) selectRow(pick.closest("[data-select]"));
      else {
        // 案 B: 行の中の入力・ボタン以外を押したときも、その行を選ぶ
        const row = e.target.closest("[data-select]");
        if (row && !e.target.closest("input, button, label")) selectRow(row);
      }
    });
    root.addEventListener("change", (e) => {
      if (e.target.matches("input[data-kind]")) applyKind(e.target);
    });
    root.addEventListener("input", (e) => {
      if (e.target.matches("input[data-title]")) applyTitle(e.target);
    });
  });
};

/** ホットキーの欄: 押したキーの組み合わせを欄に入れる */
const setupHotkeys = () => {
  const modifiers = ["Control", "Alt", "Shift", "Meta"];
  document.addEventListener("focusin", (e) => {
    if (e.target.matches("input.hotkey")) { e.target.readOnly = true; e.target.dataset.capturing = "true"; }
  });
  document.addEventListener("focusout", (e) => {
    if (e.target.matches("input.hotkey")) e.target.dataset.capturing = "false";
  });
  document.addEventListener("keydown", (e) => {
    const input = e.target;
    if (!input.matches("input.hotkey")) return;
    // Tab と Esc は欄の移動と画面の取り消しに残す
    if (e.key === "Tab" || e.key === "Escape") return;
    e.preventDefault();
    if (modifiers.includes(e.key)) return;
    const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Win"].filter(Boolean);
    input.value = [...mods, e.key.length === 1 ? e.key.toUpperCase() : e.key].join("+");
    input.dataset.capturing = "false";
  });
};

setupScenes();
setupPresets();
setupHotkeys();
