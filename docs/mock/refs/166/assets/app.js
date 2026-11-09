// PR 166 の画面モックの動き（ハルシネーションの文言の一覧の足す・消す・並べ替え）

/** 行の番号に合わせて読み上げの名前を付け直し、端の行の上へ・下へを押せなくし、行が無いときの文を出し分ける */
const refreshPhrases = (root) => {
  const rows = [...root.querySelectorAll("[data-phrase]")];
  rows.forEach((row, i) => {
    const n = i + 1;
    row.querySelector("[data-text]").setAttribute("aria-label", `${n} 行目の文言`);
    row.querySelector("[data-where]").setAttribute("aria-label", `${n} 行目の位置`);
    row.querySelector("[data-remove]").setAttribute("aria-label", `${n} 行目を消す`);
    const up = row.querySelector('[data-move="up"]');
    const down = row.querySelector('[data-move="down"]');
    if (up) { up.setAttribute("aria-label", `${n} 行目を上へ`); up.disabled = i === 0; }
    if (down) { down.setAttribute("aria-label", `${n} 行目を下へ`); down.disabled = i === rows.length - 1; }
  });
  const empty = rows.length === 0;
  root.querySelector("[data-phrases-wrap]").hidden = empty;
  root.querySelector("[data-phrases-empty]").hidden = !empty;
};

/** 動かした結果を読み上げに知らせる */
const announce = (root, text) => {
  root.querySelector("[data-phrases-status]").textContent = text;
};

/** 行を 1 つ上か下へ動かす */
const moveRow = (root, row, dir) => {
  const target = dir === "up" ? row.previousElementSibling : row.nextElementSibling;
  if (!target) return;
  if (dir === "up") target.before(row);
  else target.after(row);
  refreshPhrases(root);
  const n = [...root.querySelectorAll("[data-phrase]")].indexOf(row) + 1;
  announce(root, `${n} 行目へ動かしました`);
};

/** 「行を足す」: ひな形を写して末尾に足し、文言の欄へフォーカスを移す */
const addRow = (root) => {
  const holder = document.createElement("template");
  holder.innerHTML = root.querySelector("template[data-phrase-template]").innerHTML;
  root.querySelector("[data-phrase-list]").append(holder.content);
  refreshPhrases(root);
  const rows = root.querySelectorAll("[data-phrase]");
  rows[rows.length - 1].querySelector("[data-text]").focus();
};

/** 行を消し、次の行（無ければ前の行、どちらも無ければ足すボタン）へフォーカスを移す */
const removeRow = (root, row) => {
  const next = row.nextElementSibling || row.previousElementSibling;
  row.remove();
  refreshPhrases(root);
  if (next) next.querySelector("[data-text]").focus();
  else root.querySelector("[data-add-phrase]").focus();
};

/** 案 B: つまみを掴んで行を動かす */
const setupDrag = (root) => {
  const list = root.querySelector("[data-phrase-list]");
  let dragging = null;
  list.addEventListener("dragstart", (e) => {
    dragging = e.target.closest("[data-phrase]");
    if (!dragging) return;
    dragging.dataset.dragging = "true";
    e.dataTransfer.effectAllowed = "move";
  });
  list.addEventListener("dragover", (e) => {
    if (!dragging) return;
    e.preventDefault();
    const over = e.target.closest("[data-phrase]");
    if (!over || over === dragging) return;
    // 掴んだ行を、指している行の上半分なら前へ、下半分なら後ろへ入れる
    const box = over.getBoundingClientRect();
    if (e.clientY < box.top + box.height / 2) over.before(dragging);
    else over.after(dragging);
  });
  list.addEventListener("dragend", () => {
    if (!dragging) return;
    dragging.dataset.dragging = "false";
    refreshPhrases(root);
    const n = [...root.querySelectorAll("[data-phrase]")].indexOf(dragging) + 1;
    announce(root, `${n} 行目へ動かしました`);
    dragging = null;
  });
};

/** 文言の一覧の操作を、一覧ごとにまとめて受ける */
const setupPhrases = () => {
  document.querySelectorAll("[data-phrases]").forEach((root) => {
    refreshPhrases(root);
    root.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add-phrase]");
      const remove = e.target.closest("[data-remove]");
      const move = e.target.closest("[data-move]");
      if (add) addRow(root);
      else if (remove) removeRow(root, remove.closest("[data-phrase]"));
      else if (move) {
        const row = move.closest("[data-phrase]");
        moveRow(root, row, move.dataset.move);
        // 端まで動いてボタンが押せなくなったら、もう一方のボタンへ移す
        if (move.disabled) row.querySelector(`[data-move="${move.dataset.move === "up" ? "down" : "up"}"]`).focus();
        else move.focus();
      }
    });
    // 案 B: 行の中で Alt+↑ / Alt+↓ を押すと、フォーカスを残したまま行を動かす
    if (root.dataset.phrases === "grip") {
      root.addEventListener("keydown", (e) => {
        if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
        const row = e.target.closest("[data-phrase]");
        if (!row) return;
        e.preventDefault();
        moveRow(root, row, e.key === "ArrowUp" ? "up" : "down");
        e.target.focus();
      });
      setupDrag(root);
    }
  });
};

setupPhrases();
