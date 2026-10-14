// PR 101 の画面モックの動き（保存の後の知らせを、欄を変えたら消し、「保存」で出す）
// 場面・まとまりの切り替えとホットキーの入力は refs/44 の app.js が受ける

/** 開いたときの値（data-opened）から変わった「再起動で反映」の欄の数を返す */
const countRestartChanges = (win) => [...win.querySelectorAll("[data-opened]")]
  .filter((field) => field.value !== field.dataset.opened).length;

/** 窓のフッターの知らせとボタンを、保存した直後か欄を変えた後かに合わせて出し分ける */
const showFoot = (win, justSaved) => {
  const count = countRestartChanges(win);
  // 件数は保存済みの欄も含めて、開いたときの値から数える
  win.querySelectorAll("[data-restart-count], [data-saved-count]").forEach((el) => { el.textContent = String(count); });
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
