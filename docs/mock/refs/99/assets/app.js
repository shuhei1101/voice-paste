// PR 99 の画面モックの動き（表記のヒントの語の足す・消す、語の数と長さの数え直し、エラーの一覧からの移動）
// プリセットの足す・消す・並べ替え・名前の写しは refs/44 の app.js が受ける

/** 語をつなぐ区切り */
const SEPARATOR = "、";

/** 文字列の UTF-8 のバイト数を返す */
const byteLength = (text) => new TextEncoder().encode(text).length;

/** プリセットの語のうち、空でないものを一覧の順に返す */
const wordsOf = (preset) => [...preset.querySelectorAll("[data-word-input]")]
  .map((input) => input.value)
  .filter((value) => value !== "");

/** 語の一覧に、何番目の語かを読み上げ用の名前で振り直し、語が無ければ一覧の代わりの文を出す */
const refreshWords = (preset) => {
  const items = [...preset.querySelectorAll("[data-word]")];
  items.forEach((item, i) => {
    const n = i + 1;
    item.querySelector("[data-word-input]").setAttribute("aria-label", `${n} つ目の語`);
    item.querySelector("[data-remove-word]").setAttribute("aria-label", `${n} つ目の語を消す`);
  });
  preset.querySelector("[data-words]").hidden = items.length === 0;
  preset.querySelector("[data-words-empty]").hidden = items.length > 0;
};

/** プリセットの頭に語の数と長さを出し、無効のプリセットに印を付ける */
const refreshPreset = (preset) => {
  const words = wordsOf(preset);
  preset.dataset.off = String(!preset.querySelector("[data-hint-on]").checked);
  preset.querySelector("[data-hint-count]").textContent =
    `${words.length} 語・${byteLength(words.join(SEPARATOR))} バイト`;
};

/** 有効なプリセットの語をつないだ長さを数え、バーと今の長さの文言に出す */
const refreshTotal = (root) => {
  const limit = Number(root.dataset.limit);
  const words = [...root.querySelectorAll("[data-hint]")]
    .filter((preset) => preset.querySelector("[data-hint-on]").checked)
    .flatMap(wordsOf);
  const total = byteLength(words.join(SEPARATOR));
  const box = root.querySelector("[data-total-box]");
  const over = total > limit;
  box.dataset.over = String(over);
  // バーは上限で止め、超えた分は文言で伝える
  box.querySelector("meter").value = Math.min(total, limit);
  box.querySelector("[data-total]").textContent = over
    ? `${total} / ${limit} バイト（${total - limit} バイト超過）`
    : `${total} / ${limit} バイト`;
};

/** 一覧の全てのプリセットと長さの表示を数え直す */
const refreshHints = (root) => {
  root.querySelectorAll("[data-hint]").forEach((preset) => {
    refreshWords(preset);
    refreshPreset(preset);
  });
  refreshTotal(root);
};

/** 「語を足す」: 語の一覧の末尾に空の欄を足し、その欄へフォーカスを移す */
const addWord = (root, preset) => {
  const holder = document.createElement("template");
  holder.innerHTML = root.querySelector("template[data-word-template]").innerHTML;
  preset.querySelector("[data-words]").append(holder.content);
  refreshWords(preset);
  [...preset.querySelectorAll("[data-word-input]")].at(-1).focus();
};

/** 語を消し、「語を足す」へフォーカスを移す */
const removeWord = (button) => {
  const preset = button.closest("[data-hint]");
  button.closest("[data-word]").remove();
  preset.querySelector("[data-add-word]").focus();
};

/** 表記のヒントの欄の操作を、欄ごとにまとめて受ける */
const setupHints = () => {
  document.querySelectorAll("[data-hints]").forEach((root) => {
    refreshHints(root);
    root.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add-word]");
      const remove = e.target.closest("[data-remove-word]");
      if (add) addWord(root, add.closest("[data-hint]"));
      else if (remove) removeWord(remove);
      // プリセットの足す・消すの後も数え直す
      refreshHints(root);
    });
    root.addEventListener("input", () => refreshHints(root));
    root.addEventListener("change", () => refreshHints(root));
  });
};

/** エラーの一覧のリンク: 指した欄へフォーカスを移す */
const setupHintErrorLinks = () => {
  document.querySelectorAll("[data-hint-error-link]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById(a.getAttribute("href").slice(1)).focus();
  }));
};

setupHints();
setupHintErrorLinks();
