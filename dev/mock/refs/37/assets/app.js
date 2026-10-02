// PR 37 の画面モックの動き（場面の切り替え・設定のまとまりの切り替え・ホットキーの入力・再起動の知らせ）

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

/** 設定画面の左のメニューで、選んだまとまりの欄だけを出す */
const setupGroups = () => {
  document.querySelectorAll(".settings--full").forEach((win) => {
    const links = win.querySelectorAll(".settings__nav a");
    const groups = win.querySelectorAll("fieldset[data-group]");
    const select = (id) => {
      links.forEach((a) => {
        // 選んだまとまりのリンクにだけ aria-current を付ける
        if (a.getAttribute("href") === `#${id}`) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      });
      groups.forEach((g) => { g.hidden = g.id !== id; });
    };
    links.forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      select(a.getAttribute("href").slice(1));
    }));
    const current = win.querySelector('.settings__nav a[aria-current="page"]');
    if (current) select(current.getAttribute("href").slice(1));
  });
};

/** ホットキーの欄: 押したキーの組み合わせを欄に入れる */
const setupHotkeys = () => {
  const modifiers = ["Control", "Alt", "Shift", "Meta"];
  document.querySelectorAll("input.hotkey").forEach((input) => {
    input.readOnly = true;
    input.addEventListener("focus", () => { input.dataset.capturing = "true"; });
    input.addEventListener("blur", () => { input.dataset.capturing = "false"; });
    input.addEventListener("keydown", (e) => {
      // Tab と Esc は欄の移動と画面の取り消しに残す
      if (e.key === "Tab" || e.key === "Escape") return;
      e.preventDefault();
      if (modifiers.includes(e.key)) return;
      const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Win"].filter(Boolean);
      input.value = [...mods, e.key.length === 1 ? e.key.toUpperCase() : e.key].join("+");
      input.dataset.capturing = "false";
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
};

/** 反映が restart の欄を変えたら「保存して再起動」と知らせを出す */
const setupRestartNotice = () => {
  document.querySelectorAll(".settings--full").forEach((win) => {
    const notice = win.querySelector("[data-restart-notice]");
    const button = win.querySelector("[data-restart-button]");
    if (!notice || !button) return;
    win.addEventListener("change", (e) => {
      // data-reload="restart" の行の中の変更だけを数える
      if (!e.target.closest('[data-reload="restart"]')) return;
      notice.hidden = false;
      button.hidden = false;
    });
  });
};

setupScenes();
setupGroups();
setupHotkeys();
setupRestartNotice();
