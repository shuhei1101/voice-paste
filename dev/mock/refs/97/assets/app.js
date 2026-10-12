// PR 97 の画面モックの動き（用語集の選択・補正に使う用語集の切り替え・用語集と行の足す・消す・名前・行の使う / 使わない）

/** 行の表の行に、上から何行目かを読み上げ用の名前で振り直す */
const renumberEntries = (detail) => {
  detail.querySelectorAll("[data-entry]").forEach((row, i) => {
    const n = i + 1;
    row.querySelector("[data-on]").setAttribute("aria-label", `${n} 行目を補正に使う`);
    row.querySelector("[data-wrong]").setAttribute("aria-label", `${n} 行目の誤変換`);
    row.querySelector("[data-right]").setAttribute("aria-label", `${n} 行目の正しい表記`);
    row.querySelector("[data-remove-entry]").setAttribute("aria-label", `${n} 行目を消す`);
  });
};

/** 用語集の行の数とオンの行の数を一覧に出し、行が無ければ表の代わりの文を出す */
const refreshCount = (detail) => {
  const rows = [...detail.querySelectorAll("[data-entry]")];
  const on = rows.filter((row) => row.querySelector("[data-on]").checked).length;
  const id = detail.dataset.detail;
  document.querySelectorAll(`[data-count="${id}"]`).forEach((c) => {
    // 狭い幅では行の数とオンの数の間でだけ折り返すよう、2 つに分けて入れる
    const total = document.createElement("span");
    total.textContent = `${rows.length} 行`;
    const onCount = document.createElement("span");
    onCount.textContent = `（オン ${on}）`;
    c.replaceChildren(total, onCount);
  });
  detail.querySelector("[data-entries-wrap]").hidden = rows.length === 0;
  detail.querySelector("[data-entries-empty]").hidden = rows.length > 0;
};

/** 補正に使う用語集の「消す」を押せなくし、ほかの用語集の「消す」を押せるようにする */
const refreshRemovable = (root) => {
  root.querySelectorAll("[data-item]").forEach((row) => {
    row.querySelector("[data-remove-glossary]").disabled = row.querySelector("[data-active]").checked;
  });
};

/** 一覧で選んだ用語集の行の表だけを出し、選んだことを名前のボタンに付ける */
const selectGlossary = (root, id) => {
  root.querySelectorAll("[data-item]").forEach((row) => {
    const selected = row.dataset.select === id;
    row.dataset.selected = String(selected);
    const pick = row.querySelector("[data-pick]");
    if (selected) pick.setAttribute("aria-current", "true");
    else pick.removeAttribute("aria-current");
  });
  root.querySelectorAll("[data-detail]").forEach((d) => { d.hidden = d.dataset.detail !== id; });
};

let addedGlossaries = 0;

/** 「用語集を足す」: 一覧の末尾と行の表のひな形を写し、足した用語集を選んで名前の欄へフォーカスを移す */
const addGlossary = (root) => {
  addedGlossaries += 1;
  const id = `${root.id}-new${addedGlossaries}`;
  root.querySelectorAll("template[data-glossary-template]").forEach((t) => {
    // 表の行も崩さずに組み立てるため template で解釈する
    const holder = document.createElement("template");
    holder.innerHTML = t.innerHTML.replaceAll("__ID__", id).replaceAll("__GROUP__", root.id);
    root.querySelector(t.dataset.glossaryTemplate).append(holder.content);
  });
  selectGlossary(root, id);
  refreshCount(root.querySelector(`[data-detail="${id}"]`));
  document.getElementById(`${id}-name`).focus();
};

/** 補正に使っていない用語集を消し、補正に使う用語集を選び直す */
const removeGlossary = (root, button) => {
  const row = button.closest("[data-item]");
  const id = row.dataset.select;
  row.remove();
  root.querySelector(`[data-detail="${id}"]`).remove();
  const active = root.querySelector("[data-active]:checked").closest("[data-item]");
  selectGlossary(root, active.dataset.select);
  root.querySelector("[data-add-glossary]").focus();
};

/** 「行を足す」: 行の表の末尾に空の行を足し、誤変換の欄へフォーカスを移す */
const addEntry = (root, detail) => {
  const holder = document.createElement("template");
  holder.innerHTML = root.querySelector("template[data-entry-template]").innerHTML;
  detail.querySelector("[data-entries]").append(holder.content);
  renumberEntries(detail);
  refreshCount(detail);
  [...detail.querySelectorAll("[data-wrong]")].at(-1).focus();
};

/** 行を消し、「行を足す」へフォーカスを移す */
const removeEntry = (button) => {
  const detail = button.closest("[data-detail]");
  button.closest("[data-entry]").remove();
  renumberEntries(detail);
  refreshCount(detail);
  detail.querySelector("[data-add-entry]").focus();
};

/** 用語集の欄の操作を、用語集のまとまりごとにまとめて受ける */
const setupGlossaries = () => {
  document.querySelectorAll("[data-glossary-root]").forEach((root) => {
    refreshRemovable(root);
    root.querySelectorAll("[data-detail]").forEach((d) => { renumberEntries(d); refreshCount(d); });
    root.addEventListener("click", (e) => {
      const pick = e.target.closest("[data-pick]");
      const addG = e.target.closest("[data-add-glossary]");
      const removeG = e.target.closest("[data-remove-glossary]");
      const addE = e.target.closest("[data-add-entry]");
      const removeE = e.target.closest("[data-remove-entry]");
      if (pick) selectGlossary(root, pick.closest("[data-item]").dataset.select);
      else if (addG) addGlossary(root);
      else if (removeG) removeGlossary(root, removeG);
      else if (addE) addEntry(root, addE.closest("[data-detail]"));
      else if (removeE) removeEntry(removeE);
      else {
        // 一覧の行の中の入力・ボタン以外を押したときも、その用語集を選ぶ
        const row = e.target.closest("[data-select]");
        if (row && !e.target.closest("input, button, label")) selectGlossary(root, row.dataset.select);
      }
    });
    root.addEventListener("change", (e) => {
      if (e.target.matches("[data-active]")) refreshRemovable(root);
      if (e.target.matches("[data-on]")) {
        // オフの行は文字を薄くし、行の数を数え直す
        e.target.closest("[data-entry]").dataset.off = String(!e.target.checked);
        refreshCount(e.target.closest("[data-detail]"));
      }
    });
    root.addEventListener("input", (e) => {
      if (!e.target.matches("[data-name]")) return;
      // 名前の欄に合わせて、一覧の名前と行の表の見出しを書き換える
      const id = e.target.dataset.name;
      root.querySelectorAll(`[data-name-view="${id}"]`).forEach((v) => { v.textContent = e.target.value; });
      // 名前が空の間は、一覧の名前のボタンに読み上げ用の名前を残す
      root.querySelector(`[data-select="${id}"] [data-unnamed]`).hidden = e.target.value !== "";
    });
  });
};

/** エラーの一覧のリンク: 欄のある用語集を選んでから、その欄へフォーカスを移す */
const setupErrorLinks = () => {
  document.querySelectorAll("[data-error-link]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const field = document.getElementById(a.getAttribute("href").slice(1));
    const detail = field.closest("[data-detail]");
    selectGlossary(field.closest("[data-glossary-root]"), detail.dataset.detail);
    field.focus();
  }));
};

setupGlossaries();
setupErrorLinks();
