// PR 171 の画面モックの動き（場面の切り替え・確認のダイアログを開く・コピーした直後の表示）

const COPIED_MS = 2000;

/** 出している場面の中の確認のダイアログをモーダルで開き、ほかは閉じる */
const openDialogs = () => {
  document.querySelectorAll("dialog.web-dialog").forEach((d) => {
    const panel = d.closest("[data-scene-panel]");
    if (d.open) d.close();
    // 隠した場面のダイアログは開かない
    if (panel === null || !panel.hidden) d.showModal();
  });
};

/** モック専用の操作列のボタンか URL の ?scene= で、data-scene-panel（空白区切りの場面名）に含まれる場面だけを出す */
const setupScenes = () => {
  const buttons = [...document.querySelectorAll(".mock-bar [data-scene]")];
  const panels = document.querySelectorAll("[data-scene-panel]");
  const show = (name) => {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.scene === name)));
    panels.forEach((p) => { p.hidden = !p.dataset.scenePanel.split(" ").includes(name); });
    openDialogs();
  };
  buttons.forEach((b) => b.addEventListener("click", () => show(b.dataset.scene)));
  const asked = new URLSearchParams(location.search).get("scene");
  const first = buttons.find((b) => b.dataset.scene === asked) ?? buttons[0];
  if (first) show(first.dataset.scene);
};

/** コピーのボタンを押したら、少しの間「コピー済み」を出す */
const setupCopy = () => {
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    const label = btn.querySelector("[data-copy-label]");
    const idle = label.textContent;
    btn.addEventListener("click", () => {
      btn.dataset.copied = "true";
      label.textContent = "コピー済み";
      setTimeout(() => {
        btn.dataset.copied = "false";
        label.textContent = idle;
      }, COPIED_MS);
    });
  });
};

setupScenes();
setupCopy();
