// PR 347 の画面モックの動き（場面とデータの量の切り替え・結果の一覧の描画・折りたたみ・コピーした直後の表示）

const COPIED_MS = 2000;
const RESULTS_MAX = 10;
const DATA_NAMES = ["normal", "long", "many", "over", "empty"];

const LONG_NAME = "2026-10-22_定例ミーティング_議事メモ用の録音_最終版_確認済み_共有用_外の端末から送信_第二部.mp3";
const URL_TEXT = "https://voice-paste.example.com/web/transcriptions/3f9c2a7e5b1d4c8a9e0f6b2d7c1a5e8f3f9c2a7e5b1d4c8a";
const LONG_WORD = "SupercalifragilisticexpialidociousTranscriptionWorkerIdentifier";

const SHORT_TEXT = "ホットキーの録音中でもブラウザから送れるかを確認する。";
const MIDDLE_TEXT = "定例の議題は三つです。一つ目はリリースの日程、二つ目は外の端末からの文字起こし、三つ目は用語集の見直しです。";
const MEETING_TEXT = [
  "来週の打ち合わせは火曜日の午後に移します。資料は月曜日までに共有フォルダへ配置してください。",
  "voice-paste の API は今のままで、外の端末からはゲートウェイを通して使用します。",
  "録音の上限は 30 分のままにし、長い会議は区切って送信します。",
  "用語集のプリセットは会議用を既定にして、固有名詞の補正を確認します。",
  "次回までに、スマホの幅で結果をコピーしやすいかを確認しておきます。",
  "以上です。質問があればチャットに記載してください。",
].join("\n");

/** 長い・上限を超える場面の起こした文字: 切れ目の無い URL・長い英単語・桁の多い数・負の数を入れ、段落を重ねる */
const longText = (repeat) => {
  const paragraph = [
    MEETING_TEXT,
    `議事録は ${URL_TEXT} に保存しました。`,
    `識別子 ${LONG_WORD} の件は、差分が -12,345,678 件から 98,765,432,100 件に増えた原因を調べます。`,
  ].join("\n");
  return Array.from({ length: repeat }, () => paragraph).join("\n\n");
};

/** データの量ごとの結果の一覧（最新の件が先頭） */
const DATA = {
  normal: [
    { time: "10/23 14:05", src: "画面録音・2:14", text: MEETING_TEXT },
    { time: "10/23 13:52", src: "画面録音・0:41", text: SHORT_TEXT },
    { time: "10/22 18:30", src: "2026-10-22_定例ミーティング_議事メモ用の録音_最終版.mp3", text: MIDDLE_TEXT },
  ],
  long: [
    { time: "10/23 14:05", src: LONG_NAME, text: longText(3) },
    { time: "10/23 13:52", src: LONG_NAME, text: SHORT_TEXT },
  ],
  many: Array.from({ length: RESULTS_MAX }, (_, i) => ({
    time: `10/${String(23 - Math.floor(i / 3)).padStart(2, "0")} ${String(14 - i).padStart(2, "0")}:05`,
    src: i % 2 === 0 ? "画面録音・2:14" : "interview-part2.m4a",
    text: i % 3 === 0 ? MEETING_TEXT : i % 3 === 1 ? SHORT_TEXT : MIDDLE_TEXT,
  })),
  // 上限の 10 件を超えた分は保存日時の最も前の件から削除するため、一覧は 10 件のまま。起こした文字は 30 分の録音に近い長さ
  over: Array.from({ length: RESULTS_MAX }, (_, i) => ({
    time: `10/${String(23 - Math.floor(i / 3)).padStart(2, "0")} ${String(14 - i).padStart(2, "0")}:05`,
    src: LONG_NAME,
    text: i === 0 ? longText(24) : longText(2),
  })),
  empty: [],
};

/** データの量ごとの録音中の経過時間（長い・上限を超える場面は上限の直前） */
const TIMER = {
  normal: { elapsed: "02:14", label: "経過時間 2 分 14 秒", value: 134, left: "27:46", low: false },
  long: { elapsed: "29:12", label: "経過時間 29 分 12 秒", value: 1752, left: "0:48", low: true },
  many: { elapsed: "02:14", label: "経過時間 2 分 14 秒", value: 134, left: "27:46", low: false },
  over: { elapsed: "29:59", label: "経過時間 29 分 59 秒", value: 1799, left: "0:01", low: true },
  empty: { elapsed: "00:03", label: "経過時間 0 分 3 秒", value: 3, left: "29:57", low: false },
};

const params = new URLSearchParams(location.search);
const dataName = DATA_NAMES.includes(params.get("data")) ? params.get("data") : "normal";

/** 結果の一覧を、テンプレートからデータの量の場面の件数だけ描く */
const renderResults = () => {
  const list = document.querySelector("[data-results]");
  const template = document.querySelector("#result-template");
  const rows = DATA[dataName];
  rows.forEach((row) => {
    const item = template.content.firstElementChild.cloneNode(true);
    item.querySelector("[data-time]").textContent = row.time;
    item.querySelector("[data-src]").textContent = row.src;
    item.querySelector("[data-src]").title = row.src;
    item.querySelector("[data-text]").textContent = row.text;
    list.append(item);
  });
  list.hidden = rows.length === 0;
  document.querySelector("[data-results-empty]").hidden = rows.length !== 0;
  document.querySelector("[data-results-count]").textContent = rows.length === 0
    ? `最大 ${RESULTS_MAX} 件・保存 7 日`
    : `${rows.length} 件・最大 ${RESULTS_MAX} 件・保存 7 日`;
};

/** 5 行を超える起こした文字だけを折りたたみ、続きを読む・折りたたむのボタンを出す */
const setupCollapse = () => {
  document.querySelectorAll("[data-results] .result").forEach((item, i) => {
    const text = item.querySelector("[data-text]");
    const toggle = item.querySelector("[data-toggle]");
    const label = toggle.querySelector("[data-toggle-label]");
    text.id = `result-text-${i}`;
    toggle.setAttribute("aria-controls", text.id);
    text.dataset.collapsed = "true";
    // 折りたたんで高さが変わらない（5 行以内の）件はボタンを出さず、全文のまま出す
    if (text.scrollHeight <= text.clientHeight) {
      text.dataset.collapsed = "false";
      toggle.hidden = true;
      return;
    }
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      text.dataset.collapsed = String(expanded);
      label.textContent = expanded ? "続きを読む" : "折りたたむ";
    });
  });
};

/** コピーのボタンを押したら、少しの間アイコンだけをチェックに替える（文言は「コピー」のまま。読み上げには「コピーしました」を伝える） */
const setupCopy = () => {
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    const status = btn.querySelector("[data-copy-status]");
    btn.addEventListener("click", () => {
      btn.dataset.copied = "true";
      status.textContent = "コピーしました";
      setTimeout(() => {
        btn.dataset.copied = "false";
        status.textContent = "";
      }, COPIED_MS);
    });
  });
};

/** 録音中・一時停止中の経過時間と残り時間を、データの量の場面の値にする */
const renderTimer = () => {
  const timer = TIMER[dataName];
  document.querySelectorAll("[data-elapsed]").forEach((el) => {
    el.textContent = timer.elapsed;
    el.setAttribute("aria-label", timer.label);
  });
  document.querySelectorAll("[data-progress]").forEach((el) => { el.value = timer.value; });
  document.querySelectorAll("[data-left]").forEach((el) => {
    el.textContent = timer.left;
    el.closest("[data-left-row]").classList.toggle("recorder__left--low", timer.low);
  });
  document.querySelectorAll("[data-left-note]").forEach((el) => { el.hidden = !timer.low; });
};

/** 場面（?scene=）とデータの量（?data=）を、モック専用の操作列のボタン・リンクと URL にそろえる */
const setupScenes = () => {
  const buttons = [...document.querySelectorAll(".mock-bar [data-scene]")];
  const panels = document.querySelectorAll("[data-scene-panel]");
  const dataLinks = document.querySelectorAll(".mock-bar [data-data]");
  const show = (name) => {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.scene === name)));
    panels.forEach((p) => { p.hidden = !p.dataset.scenePanel.split(" ").includes(name); });
    dataLinks.forEach((a) => {
      a.href = `?scene=${name}&data=${a.dataset.data}`;
      if (a.dataset.data === dataName) a.setAttribute("aria-current", "page");
    });
    const url = new URL(location.href);
    url.searchParams.set("scene", name);
    url.searchParams.set("data", dataName);
    history.replaceState(null, "", url);
  };
  buttons.forEach((b) => b.addEventListener("click", () => show(b.dataset.scene)));
  // 画面の中の一時停止・再開のボタンでも場面を切り替える
  document.querySelectorAll("[data-go-scene]").forEach((b) => b.addEventListener("click", () => show(b.dataset.goScene)));
  const asked = params.get("scene");
  const first = buttons.find((b) => b.dataset.scene === asked) ?? buttons[0];
  show(first.dataset.scene);
};

renderResults();
renderTimer();
setupScenes();
setupCollapse();
setupCopy();
