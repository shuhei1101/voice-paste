// PR 108 の画面モック: 文字起こし中の表示の出力先のボタンを押すと、選んでいる出力先と案内の文を差し替える

/** 押した出力先のボタンだけを選んでいる状態にし、同じ窓の案内の文をその出力先の文にする */
const selectOutput = (button) => {
  const group = button.closest(".out-switch");
  // 同じ並びのボタンの選んでいる状態を付け直す
  for (const other of group.querySelectorAll(".btn--switch")) {
    other.setAttribute("aria-pressed", String(other === button));
  }
  const hint = button.closest(".busy").querySelector(".hint");
  hint.textContent = button.dataset.hint;
};

document.addEventListener("click", (event) => {
  const button = event.target.closest(".btn--switch");
  // 出力先のボタン以外の押下は扱わない
  if (!button) return;
  selectOutput(button);
});
