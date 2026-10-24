// PR 173 の画面モックの動き（用語集のプリセットの選択・補正に使うプリセットの切り替え・足す・消す・名前・使う用語集の選択と並べ替え、用語集の一覧と行の表）

const TRASH = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 8.5h5.6l.7-8.5"/></svg>';
const CROSS = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const GRIP = '<span class="grip" aria-hidden="true" title="掴んで動かす"><svg viewBox="0 0 12 16" aria-hidden="true"><circle cx="4" cy="4" r="1.3"/><circle cx="8" cy="4" r="1.3"/><circle cx="4" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="4" cy="12" r="1.3"/><circle cx="8" cy="12" r="1.3"/></svg></span>';
const USE_EMPTY = "使う用語集がありません。このプリセットでは何も置き換えません。";
const USE_HELP = {
  check: "チェックした用語集を上から順に当てる。同じ誤変換は上の用語集の行が当たる。行は左端を掴むか、Alt+↑ / Alt+↓ で動かす。",
  picked: "上の用語集から順に当てる。同じ誤変換は上の用語集の行が当たる。行は左端を掴むか、Alt+↑ / Alt+↓ で動かす。",
};

/** 画面に入れる文字列の記号を置き換える */
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** HTML の文字列を表の行も崩さずに要素へ組み立てる */
const build = (markup) => {
  const holder = document.createElement("template");
  holder.innerHTML = markup;
  return holder.content;
};

/** プリセットと用語集を並べた範囲（設定画面はまとまり、部品の見本はプリセットの欄） */
const scopeOf = (el) => el.closest("fieldset[data-group]") || el.closest("[data-gp-root]");

/** 範囲の中の用語集を [ID, 名前, 行の数] で並べる。用語集の一覧が無い部品の見本は属性から読む */
const listGlossaries = (scope) => {
  const gl = scope.querySelector("[data-gl-root]");
  if (!gl) return JSON.parse(scope.dataset.glossaries);
  return [...gl.querySelectorAll("[data-item]")].map((row) => {
    const id = row.dataset.select;
    return [id, gl.querySelector(`[data-name="${id}"]`).value, gl.querySelectorAll(`[data-detail="${id}"] [data-entry]`).length];
  });
};

/** 案 A の使う用語集の行（使わない用語集も並べ、チェックで選ぶ） */
const checkRow = ([id, name, rows]) => `<tr data-use="${id}" draggable="true" data-off="true"><td class="col-grip">${GRIP}</td><td class="col-on"><input type="checkbox" data-use-on aria-label="${esc(name)}を使う"></td><td class="col-order"><span class="order" data-order>-</span></td><td><span class="clip" data-name-view="${id}">${esc(name)}</span></td><td class="col-rows"><span class="count" data-rows="${id}">${rows} 行</span></td></tr>`;

/** 案 B の使う用語集の行（使う用語集だけを並べ、× で外す） */
const pickedRow = ([id, name, rows]) => `<tr data-use="${id}" draggable="true"><td class="col-grip">${GRIP}</td><td class="col-order"><span class="order" data-order>1</span></td><td><span class="clip" data-name-view="${id}">${esc(name)}</span></td><td class="col-rows"><span class="count" data-rows="${id}">${rows} 行</span></td><td class="col-tools"><button type="button" class="btn btn--icon" data-use-remove aria-label="${esc(name)}を外す">${CROSS}</button></td></tr>`;

// ===== 用語集のプリセット =====

/** 使う用語集の並びに順を振り直し、空のときの文・追加の欄・一覧の数・用語集の一覧の使うプリセットを出し直す */
const refreshUses = (root, detail) => {
  const variant = root.dataset.gpRoot;
  const rows = [...detail.querySelectorAll("[data-use]")];
  let n = 0;
  rows.forEach((row) => {
    const on = variant === "picked" || row.querySelector("[data-use-on]").checked;
    if (on) n += 1;
    row.dataset.off = String(!on);
    row.querySelector("[data-order]").textContent = on ? String(n) : "-";
  });
  detail.querySelector("[data-uses-empty]").hidden = n > 0;
  if (variant === "picked") {
    detail.querySelector("[data-uses-wrap]").hidden = rows.length === 0;
    // 追加の選択欄には、まだ使っていない用語集だけを入れる
    const used = new Set(rows.map((r) => r.dataset.use));
    const unused = listGlossaries(scopeOf(root)).filter(([id]) => !used.has(id));
    const select = detail.querySelector("[data-use-select]");
    select.replaceChildren(...unused.map(([id, name]) => new Option(name || "（名前未入力）", id)));
    detail.querySelector("[data-use-add-row]").hidden = unused.length === 0;
    detail.querySelector("[data-use-full]").hidden = unused.length > 0;
  }
  root.querySelector(`[data-use-count="${detail.dataset.detail}"]`).textContent = `${n} 件`;
  refreshUsers(scopeOf(root));
};

/** 用語集の一覧の「使うプリセット」に、その用語集を使うプリセットの名前を並べる */
const refreshUsers = (scope) => {
  const cells = scope.querySelectorAll("[data-users]");
  // 部品の見本は用語集の一覧を持たないため、書き換える欄が無い
  if (cells.length === 0) return;
  const gp = scope.querySelector("[data-gp-root]");
  cells.forEach((cell) => {
    const id = cell.dataset.users;
    const names = [...gp.querySelectorAll("[data-detail]")]
      .filter((d) => [...d.querySelectorAll(`[data-use="${id}"]`)].some((row) => row.dataset.off !== "true"))
      .map((d) => gp.querySelector(`[data-name="${d.dataset.detail}"]`).value || "（名前未入力）");
    cell.textContent = names.length > 0 ? names.join("・") : "なし";
  });
};

/** 補正に使うプリセットの「消す」を無効の見た目にして理由をツールチップに出し、ほかのプリセットの「消す」を押せるようにする */
const refreshRemovable = (root) => {
  root.querySelectorAll("[data-item]").forEach((row) => {
    const button = row.querySelector("[data-remove-item]");
    if (row.querySelector("[data-active]").checked) {
      // フォーカスとツールチップを残すため disabled ではなく aria-disabled にする
      button.setAttribute("aria-disabled", "true");
      button.title = "補正に使うプリセットは消せません";
    } else {
      button.removeAttribute("aria-disabled");
      button.removeAttribute("title");
    }
  });
};

/** 一覧で選んだ項目の欄だけを出し、選んだことを名前のボタンに付ける */
const selectItem = (root, id) => {
  root.querySelectorAll(":scope > .targets-wrap [data-item]").forEach((row) => {
    const selected = row.dataset.select === id;
    row.dataset.selected = String(selected);
    const pick = row.querySelector("[data-pick]");
    if (selected) pick.setAttribute("aria-current", "true");
    else pick.removeAttribute("aria-current");
  });
  root.querySelectorAll(":scope > [data-details] > [data-detail]").forEach((d) => { d.hidden = d.dataset.detail !== id; });
};

let addedPresets = 0;

/** 「プリセットを足す」: 一覧の末尾に足して選び、名前の欄へフォーカスを移す */
const addPreset = (root) => {
  addedPresets += 1;
  const id = `${root.id}-new${addedPresets}`;
  const variant = root.dataset.gpRoot;
  const glossaries = listGlossaries(scopeOf(root));
  root.querySelector("[data-item-list]").append(build(
    `<tr data-item data-select="${id}" data-selected="false"><td><label class="use"><input type="radio" name="${root.id}-active" value="${id}" data-active aria-label="足したプリセットを補正に使う"></label></td><td><button type="button" class="btn btn--quiet" data-pick><span class="clip" data-name-view="${id}"></span><span class="sr-only" data-unnamed>名前未入力のプリセット</span></button></td><td><span class="count" data-use-count="${id}">0 件</span></td><td><button type="button" class="btn btn--icon" data-remove-item aria-label="足したプリセットを消す">${TRASH}</button></td></tr>`,
  ));
  // 案 A は全ての用語集をチェックを外して並べ、案 B は空の並びと追加の欄を置く
  const uses = variant === "check"
    ? `<div class="targets-wrap"><table class="targets gp-uses gp-uses--check"><caption class="sr-only">プリセットで使う用語集（チェックした用語集を上から順に当てる）</caption><thead><tr><th scope="col" class="col-grip"><span class="sr-only">動かす</span></th><th scope="col" class="col-on">使う</th><th scope="col" class="col-order">順</th><th scope="col">用語集</th><th scope="col" class="col-rows">行</th></tr></thead><tbody data-uses>${glossaries.map(checkRow).join("")}</tbody></table></div><p class="entries-empty" data-uses-empty>${USE_EMPTY}</p>`
    : `<div class="targets-wrap" data-uses-wrap hidden><table class="targets gp-uses gp-uses--picked"><caption class="sr-only">プリセットで使う用語集（上の用語集から順に当てる）</caption><thead><tr><th scope="col" class="col-grip"><span class="sr-only">動かす</span></th><th scope="col" class="col-order">順</th><th scope="col">用語集</th><th scope="col" class="col-rows">行</th><th scope="col" class="col-tools"><span class="sr-only">外す</span></th></tr></thead><tbody data-uses></tbody></table></div><p class="entries-empty" data-uses-empty>${USE_EMPTY}</p><div class="gp-add" data-use-add-row><label for="${id}-add">追加する用語集</label><select id="${id}-add" data-use-select></select><button type="button" class="btn" data-use-add>追加</button></div><p class="field-help" data-use-full hidden>全ての用語集を使っています。</p>`;
  root.querySelector("[data-details]").append(build(
    `<div class="glossary-detail" data-detail="${id}"><p class="glossary-detail__title">プリセット「<span data-name-view="${id}"></span>」で使う用語集</p><div class="preset__field"><label for="${id}-name">名前</label><input type="text" class="wide" id="${id}-name" data-name="${id}" value="" placeholder="例: 会議"></div>${uses}<p class="field-help gp-help">${USE_HELP[variant]}</p><p class="sr-only" aria-live="polite" data-uses-status></p></div>`,
  ));
  selectItem(root, id);
  refreshUses(root, root.querySelector(`[data-detail="${id}"]`));
  document.getElementById(`${id}-name`).focus();
};

/** 補正に使っていないプリセットを消し、補正に使うプリセットを選び直す */
const removePreset = (root, button) => {
  const row = button.closest("[data-item]");
  root.querySelector(`[data-detail="${row.dataset.select}"]`).remove();
  row.remove();
  selectItem(root, root.querySelector("[data-active]:checked").value);
  refreshUsers(scopeOf(root));
  root.querySelector("[data-add-item]").focus();
};

/** 動かした結果を読み上げに知らせる */
const announce = (detail, text) => {
  detail.querySelector("[data-uses-status]").textContent = text;
};

/** 使う用語集の行を 1 つ上か下へ動かす */
const moveUse = (root, row, dir) => {
  const target = dir === "up" ? row.previousElementSibling : row.nextElementSibling;
  if (!target) return;
  if (dir === "up") target.before(row);
  else target.after(row);
  const detail = row.closest("[data-detail]");
  refreshUses(root, detail);
  announce(detail, `${[...detail.querySelectorAll("[data-use]")].indexOf(row) + 1} 行目へ動かしました`);
};

/** 使う用語集の行を、つまみを掴んで動かす */
const setupDrag = (root) => {
  let dragging = null;
  root.addEventListener("dragstart", (e) => {
    dragging = e.target.closest("[data-use]");
    if (!dragging) return;
    dragging.dataset.dragging = "true";
    e.dataTransfer.effectAllowed = "move";
  });
  root.addEventListener("dragover", (e) => {
    if (!dragging) return;
    e.preventDefault();
    const over = e.target.closest("[data-use]");
    if (!over || over === dragging || over.parentElement !== dragging.parentElement) return;
    // 掴んだ行を、指している行の上半分なら前へ、下半分なら後ろへ入れる
    const box = over.getBoundingClientRect();
    if (e.clientY < box.top + box.height / 2) over.before(dragging);
    else over.after(dragging);
  });
  root.addEventListener("dragend", () => {
    if (!dragging) return;
    dragging.dataset.dragging = "false";
    const detail = dragging.closest("[data-detail]");
    refreshUses(root, detail);
    announce(detail, `${[...detail.querySelectorAll("[data-use]")].indexOf(dragging) + 1} 行目へ動かしました`);
    dragging = null;
  });
};

/** 案 B: 選択欄で選んだ用語集を並びの末尾に足す */
const addUse = (root, detail) => {
  const select = detail.querySelector("[data-use-select]");
  const glossary = listGlossaries(scopeOf(root)).find(([id]) => id === select.value);
  detail.querySelector("[data-uses]").append(build(pickedRow(glossary)));
  refreshUses(root, detail);
  // 追加の欄が残っていれば続けて選べるよう選択欄へ、全て使ったら足した行の外すボタンへ移す
  if (!detail.querySelector("[data-use-add-row]").hidden) select.focus();
  else [...detail.querySelectorAll("[data-use-remove]")].at(-1).focus();
};

/** 案 B: 使う用語集を並びから外し、次の行（無ければ追加の選択欄）へフォーカスを移す */
const removeUse = (root, button) => {
  const row = button.closest("[data-use]");
  const detail = row.closest("[data-detail]");
  const next = row.nextElementSibling || row.previousElementSibling;
  row.remove();
  refreshUses(root, detail);
  if (next) next.querySelector("[data-use-remove]").focus();
  else detail.querySelector("[data-use-select]").focus();
};

/** 用語集のプリセットの欄の操作を、欄ごとにまとめて受ける */
const setupPresets = () => {
  document.querySelectorAll("[data-gp-root]").forEach((root) => {
    refreshRemovable(root);
    root.querySelectorAll("[data-detail]").forEach((d) => refreshUses(root, d));
    root.addEventListener("click", (e) => {
      const pick = e.target.closest("[data-pick]");
      const add = e.target.closest("[data-add-item]");
      const remove = e.target.closest("[data-remove-item]");
      const addU = e.target.closest("[data-use-add]");
      const removeU = e.target.closest("[data-use-remove]");
      if (pick) selectItem(root, pick.closest("[data-item]").dataset.select);
      else if (add) addPreset(root);
      else if (remove && remove.getAttribute("aria-disabled") !== "true") removePreset(root, remove);
      else if (addU) addUse(root, addU.closest("[data-detail]"));
      else if (removeU) removeUse(root, removeU);
      else {
        // 一覧の行の中の入力・ボタン以外を押したときも、そのプリセットを選ぶ
        const row = e.target.closest("[data-select]");
        if (row && !e.target.closest("input, button, label")) selectItem(root, row.dataset.select);
      }
    });
    root.addEventListener("change", (e) => {
      if (e.target.matches("[data-active]")) refreshRemovable(root);
      if (e.target.matches("[data-use-on]")) refreshUses(root, e.target.closest("[data-detail]"));
    });
    root.addEventListener("input", (e) => {
      if (!e.target.matches("[data-name]")) return;
      // 名前の欄に合わせて、一覧の名前と見出しと用語集の一覧の使うプリセットを書き換える
      const id = e.target.dataset.name;
      root.querySelectorAll(`[data-name-view="${id}"]`).forEach((v) => { v.textContent = e.target.value; });
      root.querySelector(`[data-select="${id}"] [data-unnamed]`).hidden = e.target.value !== "";
      refreshUsers(scopeOf(root));
    });
    // 使う用語集の行の中で Alt+↑ / Alt+↓ を押すと、フォーカスを残したまま行を動かす
    root.addEventListener("keydown", (e) => {
      if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
      const row = e.target.closest("[data-use]");
      if (!row) return;
      e.preventDefault();
      moveUse(root, row, e.key === "ArrowUp" ? "up" : "down");
      e.target.focus();
    });
    setupDrag(root);
  });
};

// ===== 用語集の一覧 =====

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

/** 用語集の行の数を一覧とプリセットの並びに出し、行が無ければ表の代わりの文を出す */
const refreshCount = (scope, detail) => {
  const id = detail.dataset.detail;
  const rows = detail.querySelectorAll("[data-entry]").length;
  scope.querySelectorAll(`[data-count="${id}"], [data-rows="${id}"]`).forEach((c) => { c.textContent = `${rows} 行`; });
  detail.querySelector("[data-entries-wrap]").hidden = rows === 0;
  detail.querySelector("[data-entries-empty]").hidden = rows > 0;
};

let addedGlossaries = 0;

/** 「用語集を足す」: 一覧の末尾に足して選び、プリセットの並びにも出してから名前の欄へフォーカスを移す */
const addGlossary = (root) => {
  addedGlossaries += 1;
  const id = `${root.id}-new${addedGlossaries}`;
  root.querySelectorAll("template[data-item-template]").forEach((t) => {
    root.querySelector(t.dataset.itemTemplate).append(build(t.innerHTML.replaceAll("__ID__", id)));
  });
  selectItem(root, id);
  // 案 A は全てのプリセットの並びの末尾にチェックを外して足し、案 B は追加の選択欄に入れる
  const scope = scopeOf(root);
  scope.querySelectorAll("[data-gp-root]").forEach((gp) => {
    gp.querySelectorAll("[data-detail]").forEach((d) => {
      if (gp.dataset.gpRoot === "check") d.querySelector("[data-uses]").append(build(checkRow([id, "", 0])));
      refreshUses(gp, d);
    });
  });
  document.getElementById(`${id}-name`).focus();
};

/** 用語集を消し、その用語集を使っているプリセットからも外す */
const removeGlossary = (root, button) => {
  const row = button.closest("[data-item]");
  const id = row.dataset.select;
  const wasSelected = row.dataset.selected === "true";
  root.querySelector(`[data-detail="${id}"]`).remove();
  row.remove();
  const scope = scopeOf(root);
  scope.querySelectorAll(`[data-use="${id}"]`).forEach((r) => r.remove());
  scope.querySelectorAll("[data-gp-root]").forEach((gp) => {
    gp.querySelectorAll("[data-detail]").forEach((d) => refreshUses(gp, d));
  });
  // 消した用語集を開いていたら、一覧の先頭の用語集を開く
  const first = root.querySelector("[data-item]");
  if (wasSelected && first) selectItem(root, first.dataset.select);
  root.querySelector("[data-add-item]").focus();
};

/** 「行を足す」: 行の表の末尾に空の行を足し、誤変換の欄へフォーカスを移す */
const addEntry = (root, detail) => {
  detail.querySelector("[data-entries]").append(build(root.querySelector("template[data-entry-template]").innerHTML));
  renumberEntries(detail);
  refreshCount(scopeOf(root), detail);
  [...detail.querySelectorAll("[data-wrong]")].at(-1).focus();
};

/** 行を消し、「行を足す」へフォーカスを移す */
const removeEntry = (root, button) => {
  const detail = button.closest("[data-detail]");
  button.closest("[data-entry]").remove();
  renumberEntries(detail);
  refreshCount(scopeOf(root), detail);
  detail.querySelector("[data-add-entry]").focus();
};

/** 用語集の一覧の操作を、一覧ごとにまとめて受ける */
const setupGlossaries = () => {
  document.querySelectorAll("[data-gl-root]").forEach((root) => {
    root.addEventListener("click", (e) => {
      const pick = e.target.closest("[data-pick]");
      const add = e.target.closest("[data-add-item]");
      const remove = e.target.closest("[data-remove-item]");
      const addE = e.target.closest("[data-add-entry]");
      const removeE = e.target.closest("[data-remove-entry]");
      if (pick) selectItem(root, pick.closest("[data-item]").dataset.select);
      else if (add) addGlossary(root);
      else if (remove) removeGlossary(root, remove);
      else if (addE) addEntry(root, addE.closest("[data-detail]"));
      else if (removeE) removeEntry(root, removeE);
      else {
        // 一覧の行の中の入力・ボタン以外を押したときも、その用語集を選ぶ
        const row = e.target.closest("[data-select]");
        if (row && !e.target.closest("input, button, label")) selectItem(root, row.dataset.select);
      }
    });
    root.addEventListener("change", (e) => {
      // オフの行は文字を薄くする
      if (e.target.matches("[data-on]")) e.target.closest("[data-entry]").dataset.off = String(!e.target.checked);
    });
    root.addEventListener("input", (e) => {
      if (!e.target.matches("[data-name]")) return;
      // 名前の欄に合わせて、一覧・見出し・プリセットの並びの名前と、案 B の追加の選択欄を書き換える
      const id = e.target.dataset.name;
      const scope = scopeOf(root);
      scope.querySelectorAll(`[data-name-view="${id}"]`).forEach((v) => { v.textContent = e.target.value; });
      root.querySelector(`[data-select="${id}"] [data-unnamed]`).hidden = e.target.value !== "";
      scope.querySelectorAll('[data-gp-root="picked"]').forEach((gp) => {
        gp.querySelectorAll("[data-detail]").forEach((d) => refreshUses(gp, d));
      });
    });
  });
};

/** エラーの一覧のリンク: 欄のある項目を選んでから、その欄へフォーカスを移す */
const setupErrorLinks = () => {
  document.querySelectorAll("[data-error-link]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const field = document.getElementById(a.getAttribute("href").slice(1));
    const detail = field.closest("[data-detail]");
    selectItem(detail.closest("[data-gp-root], [data-gl-root]"), detail.dataset.detail);
    field.focus();
  }));
};

setupPresets();
setupGlossaries();
setupErrorLinks();
