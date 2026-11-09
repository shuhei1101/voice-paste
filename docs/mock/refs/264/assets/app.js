// PR 264 の画面モック: 読みの欄（refs/99 の app.js の語の操作の後に、読みの欄の読み上げの名前と列の見出しを揃える）

/** プリセットごとに、読みの欄の読み上げの名前と、語の削除の読み上げの名前を番号に揃え、語が無い間は列の見出しを隠す */
const refreshReadings = () => {
  document.querySelectorAll("[data-hint]").forEach((preset) => {
    const items = [...preset.querySelectorAll("[data-word]")];
    items.forEach((item, index) => {
      const n = index + 1;
      item.querySelector("[data-reading-input]").setAttribute("aria-label", `${n} つ目の語の読み`);
      item.querySelector("[data-remove-word]").setAttribute("aria-label", `${n} つ目の語を削除`);
    });
    preset.querySelector("[data-words-head]").hidden = items.length === 0;
  });
};

document.addEventListener("click", refreshReadings);
refreshReadings();
