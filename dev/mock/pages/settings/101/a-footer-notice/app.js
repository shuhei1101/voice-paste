// PR 101 の画面モックの動き（保存の後の知らせを、欄を変えたら消し、「保存」で出す）
// 場面・まとまりの切り替えとホットキーの入力は refs/44 の app.js が受ける

/** 窓のフッターの知らせとボタンを、保存した直後か欄を変えた後かに合わせて出し分ける */
const showFoot = (win, justSaved) => {
  // 開いたときから変わった「再起動で反映」の欄が残っている窓だけ、欄を変えると再起動の知らせを出し直す
  const restartPending = win.dataset.restartPending === "true";
  win.querySelector("[data-saved-notice]").hidden = !justSaved;
  win.querySelector("[data-restart-notice]").hidden = justSaved || !restartPending;
  win.querySelector("[data-restart-button]").hidden = justSaved || !restartPending;
};

/** 欄を変えたら知らせを消し、「保存」を押したら知らせを出す */
const setupSavedNotice = () => {
  document.querySelectorAll("[data-saved-win]").forEach((win) => {
    const form = win.querySelector("form");
    form.addEventListener("input", () => showFoot(win, false));
    form.addEventListener("change", () => showFoot(win, false));
    // ホットキーの欄は refs/44 の app.js がキーの押下で値を入れ、input を起こさないため、押下で受ける
    form.addEventListener("keydown", (e) => {
      if (e.target.matches("input.hotkey") && e.key !== "Tab" && e.key !== "Escape") showFoot(win, false);
    });
    win.querySelector("[data-save]").addEventListener("click", () => showFoot(win, true));
  });
};

setupSavedNotice();
