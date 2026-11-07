// PR 274 の画面モックの動き（エンジンのタブの切り替え・使用中のマーカー・エラーの一覧から区画へ移る）

/** 案 A: タブを押すか矢印キー・Home・End で、そのエンジンの中身だけを出す */
const setupEngineTabs = () => {
  document.querySelectorAll("[data-engine-tabs]").forEach((list) => {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    const select = (tab, focus) => {
      tabs.forEach((t) => {
        const selected = t === tab;
        t.setAttribute("aria-selected", String(selected));
        t.tabIndex = selected ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !selected;
      });
      if (focus) tab.focus();
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => select(tab, false));
      tab.addEventListener("keydown", (e) => {
        const moves = {
          ArrowRight: tabs[(index + 1) % tabs.length],
          ArrowLeft: tabs[(index - 1 + tabs.length) % tabs.length],
          Home: tabs[0],
          End: tabs[tabs.length - 1],
        };
        if (!(e.key in moves)) return;
        e.preventDefault();
        select(moves[e.key], true);
      });
    });
  });
};

/** エンジンの選択を変えたら、使用中のマーカーをそのエンジンの区画へ移す（出している区画は替えない） */
const setupEngineSelect = () => {
  document.querySelectorAll("[data-engine-select]").forEach((select) => {
    const group = select.closest("fieldset");
    select.addEventListener("change", () => {
      group.querySelectorAll("[data-using]").forEach((badge) => {
        badge.hidden = badge.dataset.using !== select.value;
      });
    });
  });
};

/** エラーの一覧の行を押したら、欄のある区画を出してから欄へフォーカスを移す */
const setupErrorLinks = () => {
  document.querySelectorAll("[data-engine-error-link]").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const field = document.getElementById(link.getAttribute("href").slice(1));
      const panel = field.closest("[data-engine-panel]");
      const tab = document.querySelector(`[aria-controls="${panel.id}"]`);
      if (tab) tab.click();
      const section = field.closest("details");
      if (section) section.open = true;
      field.focus();
    });
  });
};

setupEngineTabs();
setupEngineSelect();
setupErrorLinks();
