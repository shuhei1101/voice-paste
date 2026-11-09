// PR 101 の画面モックの動き（保存の後の知らせを、欄を変えたら消し、「保存」で出す）
// 場面・まとまりの切り替えとホットキーの入力は refs/44 の app.js が受ける

/** ホットキーの欄が開いたときの値から変わっているときに添える文 */
const HOTKEY_NOTE = "新しいホットキーは、設定画面を閉じると効きます。";

/** 欄のうち、開いたときの値（data-opened）から変わったものを返す */
const changedFrom = (win, selector) => [...win.querySelectorAll(selector)]
  .filter((field) => field.value !== field.dataset.opened);

/** 窓のフッターの知らせとボタンを、保存した直後か欄を変えた後かに合わせて出し分ける */
const showFoot = (win, justSaved) => {
  // 件数は保存済みの欄も含めて、開いたときの値から数える
  const count = changedFrom(win, '[data-reload="restart"] [data-opened]').length;
  // ホットキーは設定画面を閉じるまで受け付けないため、開いたときから変わっていれば閉じると効くことを添える
  const hotkeyChanged = changedFrom(win, "input.hotkey[data-opened]").length > 0;
  if (justSaved) {
    const restartText = count > 0 ? `「再起動で反映」の設定 ${count} 件は、再起動するまで前の値で動きます。` : "";
    win.querySelector("[data-saved-text]").textContent = `保存しました。${hotkeyChanged ? HOTKEY_NOTE : ""}${restartText}`;
    win.querySelector("[data-restart-now]").hidden = count === 0;
  }
  win.querySelectorAll("[data-restart-count]").forEach((el) => { el.textContent = String(count); });
  win.querySelector("[data-saved-notice]").hidden = !justSaved;
  win.querySelector("[data-restart-notice]").hidden = justSaved || count === 0;
  win.querySelector("[data-restart-button]").hidden = justSaved || count === 0;
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
