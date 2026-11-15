"use strict";
/* ============================================================================
 * ai-monitor ドキュメントサイト 共通スクリプト
 *
 * docs/ 配下すべてのページで読み込む単一 JS。
 * 各機能は「対象 DOM が無ければ何もしない」形で並べており、
 * Mock demo / Jekyll 描画ページ / 公開ドキュメントなど、ページ種別を問わず同じファイルで動く。
 * 上タブの生成だけは _layouts/default.html の Liquid が担う（ここでは扱わない）。
 *
 * 本文の Markdown は変換せずに画面へ渡され（textarea[data-mdmark-source]）、ここで mdmark の mount で描く。
 * 表・注意書き・タブ・ステップ・ファイルツリー・コードの行の印・バッジ・見出しの節の開閉・見出しのアンカーは mdmark が描く。
 * ここが持つのは、mdmark が持たない表示（コード・Mermaid・目次・図の埋め込み）と、本文の外の機能。
 *
 * 提供する機能:
 *   1.  パンくずリスト     ... [data-breadcrumb] があれば URL 階層から自動生成
 *   3.  見出しの識別子     ... mdmark が見出しに振る識別子と同じ識別子を作る
 *   4.  コピーの部品       ... コードの右上のボタン群・コピーボタン・クリップボードへの書き込み・写せなかったときの面
 *   7.  Mermaid 描画・拡大 ... code.language-mermaid をレンダリングし、押下で全画面拡大
 *   8.  目次               ... [data-toc] に h2/h3 を並べ、現在位置ハイライト
 *   9.  サイドバー         ... [data-sidebar-source] の目次表からセクション別に生成
 *   10. ドロワー・幅の切り替え ... 720px / 960px でサイドバー・目次の配置を切り替える
 *   11. ダークモード切替   ... [data-theme-toggle] で light/dark 切替、localStorage 保存
 *   12. コード言語ラベル   ... pre 左上に言語名を表示
 *   13. 見出し単位の検索   ... /search.json をロードして検索モーダルで見出し単位に絞り込み
 *   14. 起票               ... 読んでいるページから Issue の下書きを作り、GitHub の起票画面を開く
 *   15. トップに戻る       ... [data-back-to-top] のボタンをスクロール量で表示切替
 *   16. Mock demo 用       ... 検索・行クリック・新規追加・編集モード・トースト
 *   17. コード内の Markdown ... markdown のコードブロックの中身を mdmark で描き、元のコードとの切り替えを付ける
 *   18. 図の埋め込み       ... 段落にリンク 1 本だけを置いた位置へ、リンク先の見出しの下の図を置く
 *   19. コメント           ... 選んだ文字列へのコメント・見出しへの移動・まとめてのコピーと起票
 *   20. 本文の描画         ... 本文の Markdown を mdmark で描き、閉じる見出しを決め、閉じた節を開く
 * ============================================================================ */
/* ---------- 定数 ---------- */
const TOAST_DISPLAY_MS = 1800;
const BACK_TO_TOP_THRESHOLD_PX = 300;
const MOBILE_WIDTH = 720;
const TOC_INLINE_WIDTH = 960;
const mobileQuery = window.matchMedia(`(max-width: ${MOBILE_WIDTH}px)`);
const tocInlineQuery = window.matchMedia(`(max-width: ${TOC_INLINE_WIDTH}px)`);
/* 幅の切り替えで動かすナビゲーションの要素への参照と、開いているドロワーを閉じる手段 */
const layout = { nav: null, toc: null, tocInline: null, tocAside: null, article: null, closeDrawer: null };
/* パンくず階層のラベル辞書。URL セグメント → 表示名。未登録は素通し。 */
const BREADCRUMB_LABELS = {
    "": "トップ",
    "docs": "ドキュメント",
    "mock": "モック",
    "pages": "画面",
    "components": "コンポーネント",
    "styles": "スタイル",
    "issues": "Issue",
    "assets": "アセット",
};
/* ============================================================================
 * 1. パンくずリスト
 * ---------------------------------------------------------------------------- */
/** ルート（末尾スラッシュ付き）とパス配下のセグメントに分割する */
function splitPathBySiteRoot() {
    // _layouts/default.html が data-site-root="{{ '/' | relative_url }}" を注入する
    // GitHub Pages（project pages）だと "/ai-monitor/"、ローカルルート配信だと "/"
    const bodyRoot = document.body?.dataset?.siteRoot || "/";
    const siteRoot = bodyRoot.endsWith("/") ? bodyRoot : bodyRoot + "/";
    const pathname = decodeURIComponent(window.location.pathname);
    // 末尾のファイル名を落として必ずディレクトリ形にする
    const dir = pathname.endsWith("/") ? pathname : pathname.replace(/\/[^\/]*$/, "/");
    // site root 直下の相対パスを取り出す
    const rel = dir.startsWith(siteRoot) ? dir.slice(siteRoot.length) : dir.replace(/^\//, "");
    const segs = rel.split("/").filter(Boolean);
    return { siteRoot, segs };
}
/** その中間層セグメントを「非リンクの中間表示」にするかどうか */
function isNonLinkableSegment(seg, index, segs) {
    // pages/{画面名}/issues/ は index.md を置かない中間層（規約）→ リンクにしない
    return seg === "issues" && segs[index - 2] === "pages";
}
/** URL パスの各セグメントを辿ってパンくずリンクを組み立てる */
function buildBreadcrumb() {
    const host = document.querySelector("[data-breadcrumb]");
    if (!host)
        return;
    const { siteRoot, segs } = splitPathBySiteRoot();
    const parts = [];
    parts.push(`<a href="${siteRoot}">${BREADCRUMB_LABELS[""]}</a>`);
    // 各セグメントの累積 URL を絶対パス（site root からの絶対）で組む
    let acc = siteRoot;
    segs.forEach((seg, i) => {
        acc += seg + "/";
        const label = BREADCRUMB_LABELS[seg] || seg;
        const isLast = i === segs.length - 1;
        parts.push(`<span class="sep">/</span>`);
        if (isLast || isNonLinkableSegment(seg, i, segs)) {
            // 現在地 or 中間層 → リンクにしない
            parts.push(`<span class="current">${label}</span>`);
        }
        else {
            parts.push(`<a href="${acc}">${label}</a>`);
        }
    });
    host.innerHTML = parts.join("");
}
/* ============================================================================
 * 3. 見出しの識別子
 * ---------------------------------------------------------------------------- */
/** 見出しの文字列から、mdmark が見出しに振る識別子と同じ識別子を作る（日本語はそのまま残す） */
function slugify(text) {
    return text
        .toLowerCase()
        .trim()
        // 文字・数字・結合文字・`_`・`-`・空白以外を落とす
        .replace(/[^\p{L}\p{N}\p{M}_\-\s]/gu, "")
        // 空白 1 つにつき `-` 1 つにする
        .replace(/\s/g, "-");
}
/* ============================================================================
 * 4. コピーの部品
 * ---------------------------------------------------------------------------- */
/* 写せなかったときの面で利用者の目に触れる文言 */
const COPY_FALLBACK_LABELS = {
    title: "コピーできませんでした",
    note: "下の欄の中身を選んで Ctrl+C（スマホは長押し）でコピーしてください。",
    areaName: "コピーする中身",
    close: "閉じる",
};
/* 写せなかったときの面の位置の基準に付ける名前を振る連番 */
let copyAnchorSeq = 0;
/** 要素を作る（文字は textContent で入れ、アイコンの SVG だけ html で入れる） */
function tableEl(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
        if (key === "class")
            node.className = value;
        else if (key === "html")
            node.innerHTML = value;
        else if (key === "text")
            node.textContent = value;
        else
            node.setAttribute(key, value);
    });
    node.append(...children);
    return node;
}
/** 入れ物の右上に置く、ボタンを並べる入れ物を返す（無ければ作る） */
function codeActions(container) {
    const existing = container.querySelector(":scope > .code-actions");
    if (existing)
        return existing;
    const actions = document.createElement("div");
    actions.className = "code-actions";
    container.appendChild(actions);
    // 入れ物を position: relative にして右上に置く
    container.style.position = "relative";
    return actions;
}
/** 押すと中身を写しへ入れるボタンを作る */
function createCopyButton(getText) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "code-copy";
    btn.textContent = "コピー";
    btn.addEventListener("click", async () => {
        if (await writeClipboard(getText())) {
            btn.textContent = "コピー済";
            window.setTimeout(() => { btn.textContent = "コピー"; }, 1500);
        }
        else {
            btn.textContent = "失敗";
        }
    });
    return btn;
}
/** 文字列を写しへ入れ、入れられたかを返す（安全な接続では navigator.clipboard、使えない配信では選択範囲を使う写し方） */
async function writeClipboard(text) {
    if (window.isSecureContext && navigator.clipboard) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        }
        catch {
            return false;
        }
    }
    return copyWithSelection(text);
}
/** 画面に出さないテキスト欄を選択して写しへ入れ、写せたかを返す */
function copyWithSelection(text) {
    const area = document.createElement("textarea");
    area.value = text;
    // 画面に出さず、スクロール位置も動かさない
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
}
/* 写せなかったときの面（ページに 1 つだけ置く）と、面を開いた要素 */
let copyFallbackPanel = null;
let copyFallbackSource = null;
/** 写せなかったときの面を作る（ページに 1 つだけ置く） */
function ensureCopyFallbackPanel() {
    if (copyFallbackPanel)
        return copyFallbackPanel;
    const area = tableEl("textarea", { class: "copy-fallback-area", readonly: "", rows: "6", "aria-label": COPY_FALLBACK_LABELS.areaName });
    const close = tableEl("button", { type: "button", class: "ghost", popovertarget: "copy-fallback", popovertargetaction: "hide", text: COPY_FALLBACK_LABELS.close });
    const panel = tableEl("div", { id: "copy-fallback", class: "column-menu table-menu copy-fallback", popover: "", role: "alertdialog", "aria-labelledby": "copy-fallback-title" }, [
        tableEl("p", { id: "copy-fallback-title", class: "copy-fallback-title", text: COPY_FALLBACK_LABELS.title }),
        tableEl("p", { class: "copy-fallback-note", text: COPY_FALLBACK_LABELS.note }),
        area,
        tableEl("div", { class: "column-menu-actions" }, [close]),
    ]);
    // 閉じたら（外側の押下・Esc・閉じる）、面を開いた要素へフォーカスを戻す
    panel.addEventListener("toggle", (event) => {
        if (event.newState === "closed")
            copyFallbackSource?.focus();
    });
    document.body.append(panel);
    copyFallbackPanel = panel;
    return panel;
}
/** 押した要素の下に、写せなかった中身を選んだ状態で置いた面を出す */
function showCopyFallback(source, text) {
    const panel = ensureCopyFallbackPanel();
    // 位置の基準が無い要素には名前を付ける（表のメニューを開くボタンは自分の名前を使う）
    if (!source.style.getPropertyValue("anchor-name")) {
        copyAnchorSeq += 1;
        source.style.setProperty("anchor-name", `--copy-source-${copyAnchorSeq}`);
    }
    panel.style.setProperty("position-anchor", source.style.getPropertyValue("anchor-name"));
    copyFallbackSource = source;
    const area = panel.querySelector("textarea");
    area.value = text;
    panel.showPopover();
    area.focus();
    area.select();
}
/* ============================================================================
 * 7. Mermaid 描画・拡大
 * ---------------------------------------------------------------------------- */
const ZOOM_WIDTH = "100%";
/** click 構文のリンク先 .md を Pages の .html に書き換える（Jekyll の relative_links はコードブロック内に効かないため） */
function rewriteMermaidLinks(holder) {
    holder.querySelectorAll("a").forEach((a) => {
        const attr = a.hasAttribute("href") ? "href" : "xlink:href";
        const href = a.getAttribute(attr);
        if (!href)
            return;
        a.setAttribute(attr, href.replace(/\.md(#|$)/, ".html$1"));
    });
}
/** 図の元のコードを描き、図の中のリンクと押下での拡大を効かせる */
async function renderMermaid(article) {
    if (!window.mermaid)
        return;
    const blocks = article.querySelectorAll("pre > code.language-mermaid");
    if (blocks.length === 0)
        return;
    // securityLevel: loose で click 構文をリンクとして描画する（GitHub 上では strict のため飾りになる）
    // suppressErrorRendering を外すと、構文エラーの図が body へ描かれたまま残る
    window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        suppressErrorRendering: true,
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
    });
    for (const [i, code] of blocks.entries()) {
        const pre = code.parentElement;
        const src = code.textContent;
        // div.mermaid-holder を pre の直前に置き、pre は元のコードの表示として隠しておく（元テキストは data-mermaid-src に退避）
        const holder = document.createElement("div");
        holder.className = "mermaid-holder";
        holder.dataset.mermaidSrc = src;
        holder.textContent = "図を描いています...";
        pre.before(holder);
        pre.hidden = true;
        try {
            const id = `mermaid-${Date.now()}-${i}`;
            const { svg, bindFunctions } = await window.mermaid.render(id, src);
            holder.innerHTML = svg;
            rewriteMermaidLinks(holder);
            // click が URL 形式なら <a> で描かれるが、コールバック形式は bindFunctions を呼ばないとハンドラが結ばれない
            bindFunctions?.(holder);
            holder.addEventListener("click", (event) => openZoom(holder, event));
            bindViewToggle(holder, pre, CODE_VIEW_LABELS.diagram);
        }
        catch (e) {
            holder.className = "mermaid-error";
            holder.innerHTML = `<p>図を描けませんでした: ${e?.message ?? e}</p><pre>${src}</pre>`;
        }
    }
}
/** テーマ切替時に既存の Mermaid ホルダーを再描画する */
async function rerenderMermaid() {
    if (!window.mermaid)
        return;
    const holders = document.querySelectorAll(".mermaid-holder[data-mermaid-src]");
    if (holders.length === 0)
        return;
    window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        suppressErrorRendering: true,
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
    });
    for (const [i, holder] of holders.entries()) {
        const src = holder.dataset.mermaidSrc;
        // 描き直しで中身ごと置き換わるので、操作ボタン群を退避しておく
        const actions = holder.querySelector(":scope > .code-actions");
        try {
            const id = `mermaid-re-${Date.now()}-${i}`;
            const { svg, bindFunctions } = await window.mermaid.render(id, src);
            holder.innerHTML = svg;
            rewriteMermaidLinks(holder);
            bindFunctions?.(holder);
            if (actions)
                holder.appendChild(actions);
        }
        catch (e) {
            holder.className = "mermaid-error";
            holder.innerHTML = `<p>図を描けませんでした: ${e?.message ?? e}</p><pre>${src}</pre>`;
        }
    }
}
/** 図を画面いっぱいに重ねて出し、閉じる手段を配る */
function openZoom(holder, event) {
    // URL 形式の click は <a>、コールバック形式は .clickable として描かれる。リンクの移動と操作ボタンの押下を優先する
    if (event.target.closest("a, .clickable, .code-actions"))
        return;
    const overlay = document.createElement("div");
    overlay.className = "zoom-overlay";
    // 操作ボタン群は複製せず、図だけを重ねる
    overlay.innerHTML = holder.querySelector("svg")?.outerHTML ?? "";
    const close = document.createElement("button");
    close.className = "overlay-close";
    close.textContent = "✕";
    overlay.appendChild(close);
    const svg = overlay.querySelector("svg");
    if (svg) {
        svg.style.width = ZOOM_WIDTH;
        // mermaid が SVG へ inline で入れる max-width に負けるので、こちらも inline で外す
        svg.style.maxWidth = "none";
    }
    const dismiss = () => {
        overlay.remove();
        document.removeEventListener("keydown", onKey);
    };
    const onKey = (key) => {
        if (key.key === "Escape")
            dismiss();
    };
    close.addEventListener("click", dismiss);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);
}
/* ============================================================================
 * 8. 目次
 * ---------------------------------------------------------------------------- */
/** 見出しの文言を、アンカーと変更の量を除いて返す */
function headingText(heading) {
    const copy = heading.cloneNode(true);
    copy.querySelectorAll(".mdmark-anchor, .change-count").forEach((mark) => mark.remove());
    return copy.textContent.trim();
}
/** 目次に載せる本文の大見出しと小見出し（描いた markdown の入れ物と埋め込んだ図の枠の中の見出しは除く） */
function tocHeadings(article) {
    return [...article.querySelectorAll("h2, h3")].filter((h) => h.id && !h.closest(".markdown-preview, .embed-figure"));
}
/** 本文の見出しから目次の並びを作る */
function renderToc(article) {
    const list = document.createElement("ul");
    tocHeadings(article).forEach((h) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = `#${h.id}`;
        a.textContent = headingText(h);
        if (h.tagName === "H3")
            a.className = "toc-h3";
        li.appendChild(a);
        list.appendChild(li);
    });
    return list;
}
const TOC_ACTIVE_RATIO = 0.2;
const TOC_LANDING_TOLERANCE_PX = 2;
/** 目次を置き、スクロール位置に応じて現在地を 1 つだけ示す */
function buildToc() {
    const aside = document.querySelector("[data-toc]");
    const article = document.querySelector(".markdown-body");
    if (!aside || !article)
        return;
    const headings = tocHeadings(article);
    if (headings.length < 2) {
        // 見出し 1 個以下では目次不要
        return;
    }
    aside.hidden = false;
    const toc = renderToc(article);
    const inline = document.createElement("details");
    inline.className = "toc-inline";
    inline.innerHTML = "<summary>目次</summary>";
    layout.toc = toc;
    layout.tocAside = aside;
    layout.tocInline = inline;
    layout.article = article;
    const links = Array.from(toc.querySelectorAll("a"));
    const linkById = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    // 飛んできた見出しが、飛んだときの位置に留まっていればその見出しを返す
    const jumpedId = (line) => {
        const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
        if (!target || !headings.includes(target))
            return null;
        const top = target.getBoundingClientRect().top;
        const landing = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
        // 着地の位置のまま（次の見出しが近くて線を越えていても、飛んだ先を示す）
        if (Math.abs(top - landing) <= TOC_LANDING_TOLERANCE_PX)
            return target.id;
        // ページの末尾では着地まで上がれないので、画面に入っていれば飛んだ先を示す
        const atBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 1;
        return atBottom && top > line && top < window.innerHeight ? target.id : null;
    };
    const updateActive = () => {
        const line = window.innerHeight * TOC_ACTIVE_RATIO;
        let currentId = null;
        for (const h of headings) {
            if (h.getBoundingClientRect().top > line)
                break;
            currentId = h.id;
        }
        currentId = jumpedId(line) || currentId;
        links.forEach((a) => a.classList.remove("active"));
        if (currentId)
            linkById.get(currentId)?.classList.add("active");
    };
    window.addEventListener("scroll", updateActive, { passive: true });
    window.addEventListener("resize", updateActive);
    window.addEventListener("hashchange", () => window.requestAnimationFrame(updateActive));
    updateActive();
}
/* ============================================================================
 * 9. サイドバー
 * ---------------------------------------------------------------------------- */
const OPEN_STATE_KEY = "docsSidebar";
/** 目次表の隠し要素からサイドバーの要素を組み立てる（表が無ければ null） */
function renderSidebar(source, tab, currentPage) {
    if (!source)
        return null;
    const nav = document.createElement("nav");
    nav.className = "docnav";
    // どのセクションにも属さない行（source 直下の表）を、セクションより前に置く
    const looseTable = source.querySelector(":scope > table");
    if (looseTable) {
        const looseRows = [...looseTable.querySelectorAll("tbody tr")];
        nav.appendChild(buildPageList(looseRows, currentPage, tab));
    }
    source.querySelectorAll("[data-section]").forEach((section) => {
        const name = section.dataset.section;
        const rows = [...section.querySelectorAll("tbody tr")];
        const holdsCurrent = rows.some((row) => pageName(row) === currentPage);
        nav.appendChild(buildSection(tab, name, groupRows(rows), currentPage, holdsCurrent));
    });
    if (!nav.hasChildNodes())
        return null;
    return nav;
}
/** 目次表の行を分類列でまとめる（分類列を持たない表はキーが空文字の 1 グループ） */
function groupRows(rows) {
    const groups = new Map();
    rows.forEach((row) => {
        const cell = row.querySelector('[data-col="分類"]');
        const category = cell ? cell.textContent.trim() : "";
        if (!groups.has(category))
            groups.set(category, []);
        groups.get(category).push(row);
    });
    return groups;
}
/** 目次表の行のページ列からページ名を取り出す */
function pageName(row) {
    return row.querySelector('[data-col="ページ"]').textContent.trim();
}
/** セクション 1 つ分の開閉ブロックを作る */
function buildSection(tab, name, groups, currentPage, holdsCurrent) {
    const key = `${tab}:${name}`;
    const open = resolveOpen(key, holdsCurrent);
    const button = openButton(name, open);
    const body = document.createElement("div");
    body.hidden = !open;
    groups.forEach((rows, category) => {
        if (category) {
            body.appendChild(buildSubsection(tab, key, category, rows, currentPage, holdsCurrent));
            return;
        }
        body.appendChild(buildPageList(rows, currentPage, tab));
    });
    bindToggle(button, body, key);
    const section = document.createElement("div");
    section.className = "docnav-section";
    section.append(button, body);
    return section;
}
/** 分類 1 つ分の開閉ブロックを作る */
function buildSubsection(tab, sectionKey, name, rows, currentPage, holdsCurrent) {
    const key = `${sectionKey}/${name}`;
    const holdsCurrentPage = holdsCurrent && rows.some((row) => pageName(row) === currentPage);
    const open = resolveOpen(key, holdsCurrentPage);
    const button = openButton(name, open);
    const list = buildPageList(rows, currentPage, tab);
    list.hidden = !open;
    bindToggle(button, list, key);
    const wrap = document.createElement("div");
    wrap.className = "docnav-subsection";
    wrap.append(button, list);
    return wrap;
}
/** セクション・分類の見出しになる開閉ボタンを作る */
function openButton(name, open) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-expanded", String(open));
    const label = document.createElement("span");
    label.textContent = name;
    const caret = document.createElement("span");
    caret.className = "docnav-caret";
    caret.textContent = "▸";
    button.append(label, caret);
    return button;
}
/** ボタンの押下に、中身の開閉と状態の記録を割り当てる */
function bindToggle(button, body, key) {
    button.addEventListener("click", () => {
        const next = button.getAttribute("aria-expanded") !== "true";
        button.setAttribute("aria-expanded", String(next));
        body.hidden = !next;
        localStorage.setItem(`${OPEN_STATE_KEY}:${key}`, String(next));
    });
}
/** セクション・分類を開いた状態で描くかを決める（現在地を含む場合は記録より優先して開く） */
function resolveOpen(key, holdsCurrent) {
    if (holdsCurrent)
        return true;
    return localStorage.getItem(`${OPEN_STATE_KEY}:${key}`) === "true";
}
/** 目次表の行順でページの並びを作る */
function buildPageList(rows, currentPage, tab) {
    const list = document.createElement("ul");
    list.className = "docnav-pages";
    rows.forEach((row) => {
        const name = pageName(row);
        const href = row.querySelector('[data-col="ページ"] a')?.getAttribute("href") || "#";
        const item = document.createElement("li");
        const a = document.createElement("a");
        a.textContent = name;
        if (name === currentPage) {
            a.setAttribute("aria-current", "page");
        }
        else {
            a.href = href;
        }
        // 今のタブのフォルダの外へ移るリンクには、別のページへ移るマークを付ける
        if (isOutsideTab(href, tab))
            a.classList.add("docnav-external");
        item.appendChild(a);
        list.appendChild(item);
    });
    return list;
}
/** リンク先が今のタブのフォルダの外（別のタブ・外部のサイト）かを返す */
function isOutsideTab(href, tab) {
    if (href === "#")
        return false;
    const url = new URL(href, window.location.href);
    // 別のサイト: 外
    if (url.origin !== window.location.origin)
        return true;
    // 同じサイト: パスにタブのフォルダを含まなければ外
    const segments = decodeURIComponent(url.pathname).split("/");
    return !segments.includes(tab);
}
/* ============================================================================
 * 10. ドロワー・幅の切り替え
 * ---------------------------------------------------------------------------- */
/** サイドバーを本文の上へ重ねて出し、背景の押下と戻る操作で閉じられるようにする */
function openDrawer(nav) {
    nav.hidden = false;
    const backdrop = document.createElement("div");
    backdrop.className = "drawer-backdrop";
    document.body.appendChild(backdrop);
    history.pushState({ drawer: true }, "");
    const close = () => {
        nav.hidden = true;
        backdrop.remove();
        window.removeEventListener("popstate", close);
        layout.closeDrawer = null;
    };
    layout.closeDrawer = close;
    backdrop.addEventListener("click", () => {
        close();
        history.back();
    });
    window.addEventListener("popstate", close);
}
/** 幅に応じてサイドバーと目次の配置を切り替える */
function applyWidth() {
    // ドロワーを開いたまま広い幅へ変わった場合、閉じて積んだ履歴を戻す
    if (!mobileQuery.matches && layout.closeDrawer) {
        layout.closeDrawer();
        history.back();
    }
    if (layout.nav)
        layout.nav.hidden = mobileQuery.matches;
    if (!layout.toc)
        return;
    if (tocInlineQuery.matches) {
        layout.tocInline.appendChild(layout.toc);
        layout.article.prepend(layout.tocInline);
        return;
    }
    layout.tocInline.remove();
    layout.tocAside.appendChild(layout.toc);
}
/* ============================================================================
 * 11. ダークモード切替
 * ---------------------------------------------------------------------------- */
const THEME_STORAGE_KEY = "docs-theme";
/** 現在のテーマを html[data-theme] に反映 */
function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    // Mermaid にも反映（再描画）
    if (window.mermaid && typeof window.mermaid.initialize === "function") {
        window.mermaid.initialize({ startOnLoad: false, securityLevel: "loose", theme: theme === "dark" ? "dark" : "default" });
    }
}
/** ボタン + localStorage + OS 設定でテーマを決める */
function bindThemeToggle() {
    const btn = document.querySelector("[data-theme-toggle]");
    // OS 設定 → localStorage の順で初期値
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const initial = stored || (prefersDark ? "dark" : "light");
    applyTheme(initial);
    if (!btn)
        return;
    btn.addEventListener("click", () => {
        const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        applyTheme(next);
        localStorage.setItem(THEME_STORAGE_KEY, next);
        // 既存の mermaid をテーマ変更後に再描画（グラフを破棄して再生成）
        rerenderMermaid();
    });
}
/* ============================================================================
 * 12. コードブロックの言語ラベル
 * ---------------------------------------------------------------------------- */
/** code か構文ハイライトの外枠の class="language-xxx" から言語名を取り出して pre 左上に付ける */
function addCodeLangLabels() {
    document.querySelectorAll(".markdown-body pre").forEach((pre) => {
        // 言語のクラスは code 自身か、rouge が pre.highlight を包む外枠のどちらかに付いている
        const langHolder = pre.classList.contains("highlight")
            ? pre.closest(".highlighter-rouge")
            : pre.querySelector(":scope > code[class*='language-']");
        if (!langHolder)
            return;
        if (pre.dataset.langReady === "true")
            return;
        pre.dataset.langReady = "true";
        const m = /language-([^\s]+)/.exec(langHolder.className);
        if (!m)
            return;
        const lang = m[1];
        // mermaid はラベル不要（図として表示するので）
        if (lang === "mermaid")
            return;
        const label = document.createElement("span");
        label.className = "code-lang";
        label.textContent = lang;
        pre.style.position = "relative";
        pre.appendChild(label);
    });
}
/* ============================================================================
 * 13. 見出し単位の検索
 * ---------------------------------------------------------------------------- */
const SEARCH_RESULT_MAX = 10;
const RECENT_SEARCH_KEY = "docsRecentSearches";
const RECENT_SEARCH_MAX = 5;
let searchIndexCache = null;
/** search.json を初回だけ fetch する（取りに行っている最中の Promise も控える） */
async function loadSearchIndex() {
    if (searchIndexCache)
        return searchIndexCache;
    const url = document.body?.dataset?.searchIndex;
    if (!url)
        return [];
    searchIndexCache = fetch(url)
        .then((res) => {
        if (!res.ok)
            throw new Error("search index fetch failed");
        return res.json();
    })
        .catch(() => {
        // 次の呼び出しで取りに行き直せるよう、失敗した控えは残さない
        searchIndexCache = null;
        return [];
    });
    return searchIndexCache;
}
/** 検索語で索引を絞り、当てはまりの強い順に上位を返す */
function filterSearch(entries, query) {
    const q = query.trim().toLowerCase();
    if (!q)
        return [];
    return entries
        .map((e) => {
        const inHeading = e.heading.toLowerCase().includes(q);
        const inPage = `${e.title} ${e.path}`.toLowerCase().includes(q);
        const inContent = e.content.toLowerCase().includes(q);
        if (!inHeading && !inPage && !inContent)
            return null;
        // 見出し一致を最上位、次に題名 / パス、最後に本文
        const score = (inHeading ? 0 : 100) + (inPage ? 0 : 50);
        return { entry: e, score };
    })
        .filter((x) => x !== null)
        .sort((a, b) => a.score - b.score)
        .slice(0, SEARCH_RESULT_MAX)
        .map((x) => x.entry);
}
/** 結果を入れ物へ並べる。0 件のときはその旨を出す */
function renderResults(container, entries, keyword) {
    container.innerHTML = "";
    if (entries.length === 0) {
        const empty = document.createElement("p");
        empty.className = "search-empty";
        empty.textContent = `「${keyword}」に当たる見出しはありません`;
        container.appendChild(empty);
        return;
    }
    entries.forEach((e) => {
        const a = document.createElement("a");
        a.className = "search-hit";
        a.setAttribute("role", "option");
        a.href = resultHref(e);
        a.innerHTML = `<span class="search-crumb"><span class="search-crumb-page">${escapeHtml(e.title)}</span> › <span class="search-crumb-heading">${highlightMatch(e.heading, keyword)}</span></span><span class="search-excerpt">${highlightMatch(e.content, keyword)}</span>`;
        container.appendChild(a);
    });
}
/** 項目の URL に、その見出しが本文で持つ id を付けた行き先を作る（mdmark は同じ見出しの 2 つ目に `-1` を付ける） */
function resultHref(entry) {
    if (entry.headingSeq === 0)
        return entry.url;
    let id = slugify(entry.heading);
    if (entry.headingSeq >= 2)
        id += `-${entry.headingSeq - 1}`;
    return `${entry.url}#${id}`;
}
/** 文字列の中で検索語に当たった箇所を強調した HTML を返す */
function highlightMatch(text, query) {
    const q = query.trim();
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (!q || i < 0)
        return escapeHtml(text);
    return `${escapeHtml(text.slice(0, i))}<mark>${escapeHtml(text.slice(i, i + q.length))}</mark>${escapeHtml(text.slice(i + q.length))}`;
}
/** 記録から最近の検索語を読む */
function readRecentSearches() {
    try {
        return JSON.parse(localStorage.getItem(RECENT_SEARCH_KEY) || "[]");
    }
    catch {
        return [];
    }
}
/** 結果を開いたときの検索語を、最近の検索の先頭へ足す */
function pushRecentSearch(query) {
    const q = query.trim();
    if (!q)
        return;
    const next = [q, ...readRecentSearches().filter((r) => r !== q)].slice(0, RECENT_SEARCH_MAX);
    localStorage.setItem(RECENT_SEARCH_KEY, JSON.stringify(next));
}
/** 検索語が空のときに、最近の検索を押せる形で並べる */
function renderRecentSearches(container, input) {
    const recent = readRecentSearches();
    if (recent.length === 0) {
        container.innerHTML = `<p class="search-empty">検索語を入れると、見出しごとに結果が並びます</p>`;
        return;
    }
    container.innerHTML = `<p class="search-group">最近の検索</p>` +
        recent.map((r) => `<button type="button" class="search-recent" data-recent="${escapeHtml(r)}">${OCTICONS.history}<span>${escapeHtml(r)}</span></button>`).join("");
    container.querySelectorAll("[data-recent]").forEach((b) => {
        b.addEventListener("click", () => {
            input.value = b.dataset.recent;
            input.dispatchEvent(new Event("input"));
            input.focus();
        });
    });
}
/** 入力・キー操作・押下を結果の入れ物へ紐付け、今の検索語で描き直す手段を返す */
function bindResultList(container, input, close) {
    let items = [];
    let selected = -1;
    const select = (i) => {
        selected = i;
        container.querySelectorAll(".search-hit").forEach((el, n) => {
            el.classList.toggle("is-selected", n === i);
            el.setAttribute("aria-selected", String(n === i));
            if (n === i)
                el.scrollIntoView({ block: "nearest" });
        });
    };
    const open = (entry) => {
        pushRecentSearch(input.value);
        close();
        navigateWithin(resultHref(entry));
    };
    const render = async () => {
        const query = input.value;
        if (query.trim() === "") {
            renderRecentSearches(container, input);
            items = [];
            selected = -1;
            return;
        }
        if (!searchIndexCache) {
            container.innerHTML = `<p class="search-loading" role="status">索引を読み込んでいます...</p>`;
        }
        const entries = await loadSearchIndex();
        if (input.value !== query)
            return;
        items = filterSearch(entries, query);
        renderResults(container, items, query);
        container.querySelectorAll(".search-hit").forEach((el, i) => {
            el.addEventListener("mousemove", () => select(i));
            el.addEventListener("click", () => {
                pushRecentSearch(input.value);
                close();
            });
        });
        select(items.length ? 0 : -1);
    };
    input.addEventListener("input", render);
    input.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown" && items.length) {
            e.preventDefault();
            select((selected + 1) % items.length);
        }
        else if (e.key === "ArrowUp" && items.length) {
            e.preventDefault();
            select((selected - 1 + items.length) % items.length);
        }
        else if (e.key === "Enter" && selected >= 0) {
            e.preventDefault();
            open(items[selected]);
        }
        else if (e.key === "Escape") {
            e.preventDefault();
            close();
        }
    });
    return render;
}
/** 入力欄・結果・キー操作の案内を持つモーダルを組み立て、開く手段を返す */
function buildSearchModal() {
    const modal = document.createElement("div");
    modal.className = "search-modal";
    modal.hidden = true;
    modal.innerHTML = `
    <div class="search-modal-backdrop" data-modal-close></div>
    <div class="search-modal-dialog" role="dialog" aria-label="全ページ検索">
      <div class="search-modal-head">
        <input type="search" placeholder="見出しを検索..." aria-label="全ページ検索">
        <button type="button" class="ghost search-modal-close" data-modal-close>閉じる</button>
      </div>
      <div class="search-modal-results" role="listbox"></div>
      <p class="search-modal-keys"><kbd>↑</kbd><kbd>↓</kbd> 選ぶ　<kbd>Enter</kbd> 開く　<kbd>Esc</kbd> 閉じる</p>
    </div>`;
    document.body.appendChild(modal);
    const input = modal.querySelector("input");
    const close = () => {
        modal.hidden = true;
        document.body.classList.remove("search-modal-open");
    };
    const render = bindResultList(modal.querySelector(".search-modal-results"), input, close);
    modal.querySelectorAll("[data-modal-close]").forEach((el) => el.addEventListener("click", close));
    return {
        open() {
            modal.hidden = false;
            document.body.classList.add("search-modal-open");
            render();
            input.focus();
            input.select();
        },
    };
}
/** ヘッダーの入力欄・検索アイコン・Ctrl+K を、同じモーダルへ繋ぐ */
function bindSearchEntries() {
    const modal = buildSearchModal();
    const headerInput = document.querySelector("[data-search-input]");
    if (headerInput) {
        // 入力欄は押すとモーダルを開くだけの見た目にする
        headerInput.readOnly = true;
        headerInput.addEventListener("focus", () => {
            headerInput.blur();
            modal.open();
        });
    }
    document.querySelector("[data-search-toggle]")?.addEventListener("click", () => modal.open());
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            modal.open();
        }
    });
}
/** 結果に出す文字列の記号を無害な表記へ置き換える */
function escapeHtml(s) {
    return String(s ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}
/* ============================================================================
 * 14. 起票
 * ---------------------------------------------------------------------------- */
const ISSUE_DRAFT_KEY = "issue-draft";
const ISSUE_URL_MAX = 6000;
const ISSUE_TRUNCATED_NOTE = "\n\n…（長さの上限を超えたため、引用の末尾を切り詰めました）";
/* 開いている起票サイドバーの入力への参照（閉じても要素ごと残す） */
const issueDraft = { panel: null, title: null, body: null, warn: null, initialBody: "" };
/** 共通レイアウトが持つ付けるラベルを並びのまま配列で返す */
function issueLabels() {
    return (document.body?.dataset?.issueLabels || "").split(",");
}
/** 起票サイドバーを組み立てて閉じた状態で置く */
function buildIssuePanel() {
    const panel = document.createElement("aside");
    panel.className = "issue-panel";
    panel.hidden = true;
    panel.setAttribute("aria-label", "Issue を書く");
    const badges = issueLabels().map((label) => `<span class="badge">${escapeHtml(label)}</span>`).join("");
    panel.innerHTML = `
    <div class="issue-panel-head">
      <h2>Issue を書く</h2>
      <button type="button" class="ghost" data-issue-close aria-label="閉じる">✕</button>
    </div>
    <label class="issue-field">
      <span>題名</span>
      <input type="text" data-issue-title>
    </label>
    <label class="issue-field">
      <span>本文</span>
      <textarea data-issue-body rows="12"></textarea>
    </label>
    <p class="issue-warn" data-issue-warn hidden>本文が長いため、GitHub で開くときに引用の末尾を切り詰めます</p>
    <div class="issue-meta">
      <span>付くラベル</span>
      ${badges}
    </div>
    <p class="issue-hint">GitHub の起票画面が別のタブで開きます。送る前にそこで内容を直せます。</p>
    <div class="issue-actions">
      <button type="button" class="ghost" data-issue-clear>クリア</button>
      <button type="button" class="primary" data-issue-submit>GitHub で開く</button>
    </div>`;
    document.querySelector(".docs-layout")?.appendChild(panel);
    issueDraft.panel = panel;
    issueDraft.title = panel.querySelector("[data-issue-title]");
    issueDraft.body = panel.querySelector("[data-issue-body]");
    issueDraft.warn = panel.querySelector("[data-issue-warn]");
    issueDraft.initialBody = issueBodyTemplate();
    issueDraft.body.value = issueDraft.initialBody;
    // 残した下書きがあれば入力欄へ戻す（ページを移ったときと再読み込みしたとき）
    restoreIssueDraft();
    panel.querySelector("[data-issue-close]").addEventListener("click", closeIssuePanel);
    panel.querySelector("[data-issue-clear]").addEventListener("click", clearIssuePanel);
    panel.querySelector("[data-issue-submit]").addEventListener("click", submitIssue);
    issueDraft.body.addEventListener("input", updateIssueWarn);
    issueDraft.title.addEventListener("input", updateIssueWarn);
    // 題名と本文の入力のたびに下書きを残す
    issueDraft.body.addEventListener("input", saveIssueDraft);
    issueDraft.title.addEventListener("input", saveIssueDraft);
}
/** 題名と本文を同じタブの sessionStorage へ残す */
function saveIssueDraft() {
    try {
        sessionStorage.setItem(ISSUE_DRAFT_KEY, JSON.stringify({ title: issueDraft.title.value, body: issueDraft.body.value }));
    }
    catch {
        // sessionStorage が使えない: 残さずに続ける
    }
}
/** sessionStorage に残した題名と本文を入力欄へ戻す */
function restoreIssueDraft() {
    let draft;
    try {
        draft = JSON.parse(sessionStorage.getItem(ISSUE_DRAFT_KEY) || "null");
    }
    catch {
        // 読めない・JSON として壊れている: 何もしない
        return;
    }
    if (!draft)
        return;
    issueDraft.title.value = draft.title || "";
    issueDraft.body.value = draft.body || issueBodyTemplate();
}
/** 該当箇所と内容の 1 ブロックを組み立てる */
function issueBodyTemplate() {
    // ページのパスに、開いている画面の条件を表すクエリ文字列を続ける（無ければパスだけ）
    const pagePath = `${document.body?.dataset?.pagePath || ""}${location.search}`;
    return ["### 該当箇所", "", `- ページ: \`${pagePath}\``, "", "### 内容", "", "", "", "---", ""].join("\n");
}
/** サイドバーを開く */
function openIssuePanel() {
    const { panel, body, title } = issueDraft;
    // 何も書いていなければ、開いた時点の URL で本文を組み直して差し替える（書きかけは変えない）
    const untouched = body.value.trim() === "" || body.value === issueDraft.initialBody;
    if (untouched) {
        body.value = issueBodyTemplate();
        issueDraft.initialBody = body.value;
    }
    panel.hidden = false;
    document.body.classList.add("issue-open");
    updateIssueWarn();
    title.focus();
}
/** サイドバーを閉じる（入力は残す） */
function closeIssuePanel() {
    issueDraft.panel.hidden = true;
    document.body.classList.remove("issue-open");
}
/** 題名・本文・長さの注意を初期状態へ戻す */
function clearIssuePanel() {
    issueDraft.title.value = "";
    issueDraft.initialBody = issueBodyTemplate();
    issueDraft.body.value = issueDraft.initialBody;
    issueDraft.warn.hidden = true;
    // 残した下書きも消す
    try {
        sessionStorage.removeItem(ISSUE_DRAFT_KEY);
    }
    catch {
        // sessionStorage が使えない: 消すものも無い
    }
}
/** 題名・本文・固定のラベルを問い合わせに載せた起票画面の URL を作る */
function buildIssueUrl(title, body) {
    const repo = document.body?.dataset?.issueRepo || "";
    const params = new URLSearchParams({ title, body, labels: issueLabels().join(",") });
    return `https://github.com/${repo}/issues/new?${params.toString()}`;
}
/** URL の長さが上限を超えるときだけ、本文の末尾を切り詰めた URL を返す */
function fitIssueUrl(title, body) {
    const full = buildIssueUrl(title, body);
    if (full.length <= ISSUE_URL_MAX)
        return full;
    let lo = 0;
    let hi = body.length;
    // 収まる本文の長さを二分探索で求める
    while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (buildIssueUrl(title, body.slice(0, mid) + ISSUE_TRUNCATED_NOTE).length <= ISSUE_URL_MAX)
            lo = mid;
        else
            hi = mid - 1;
    }
    return buildIssueUrl(title, body.slice(0, lo) + ISSUE_TRUNCATED_NOTE);
}
/** 今の入力で組み立てた URL が上限を超えるときだけ注意を出す */
function updateIssueWarn() {
    const url = buildIssueUrl(issueDraft.title.value, issueDraft.body.value);
    issueDraft.warn.hidden = url.length <= ISSUE_URL_MAX;
}
/** 組み立てた URL を別のタブで開き、サイドバーの入力を消す */
function submitIssue() {
    const url = fitIssueUrl(issueDraft.title.value, issueDraft.body.value);
    window.open(url, "_blank", "noopener");
    clearIssuePanel();
}
/** ヘッダーの起票ボタンと起票サイドバーを繋ぐ */
function bindIssueEntries() {
    // ヘッダーの起票ボタンが無いページ（Pages）では何もしない（起票はコメントのパネルから行う）
    if (!document.querySelector("[data-issue-open]"))
        return;
    buildIssuePanel();
    document.querySelector("[data-issue-open]").addEventListener("click", openIssuePanel);
}
/* ============================================================================
 * 15. トップに戻るボタン
 * ---------------------------------------------------------------------------- */
/** スクロール量で表示切替し、クリックで先頭へスムーズスクロール */
function bindBackToTop() {
    const btn = document.querySelector("[data-back-to-top]");
    if (!btn)
        return;
    const update = () => {
        btn.classList.toggle("visible", window.scrollY > BACK_TO_TOP_THRESHOLD_PX);
    };
    window.addEventListener("scroll", update, { passive: true });
    update();
    btn.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: "smooth" });
    });
}
/* ============================================================================
 * 16. Mock demo 用ハンドラ
 * 対象 DOM が無いページでは何もしない（早期 return）。
 * ---------------------------------------------------------------------------- */
/** 検索ボックスの入力語で顧客一覧の行を絞り込む */
function bindSearchFilter() {
    const input = document.getElementById("search");
    if (!input)
        return;
    input.addEventListener("input", () => {
        const keyword = input.value.trim().toLowerCase();
        document.querySelectorAll("#customer-table tbody tr").forEach((row) => {
            const text = row.textContent.toLowerCase();
            row.classList.toggle("hidden", keyword !== "" && !text.includes(keyword));
        });
    });
}
/** 行クリックで疑似遷移トーストを表示する */
function bindRowClick() {
    document.querySelectorAll("#customer-table tbody tr").forEach((row) => {
        row.addEventListener("click", (event) => {
            if (event.target instanceof HTMLInputElement)
                return;
            const id = row.dataset.id;
            showToast(`顧客 ${id} を選択しました（モック）`);
        });
    });
}
/** 新規追加ボタンでトーストを一時表示する */
function bindNewButton() {
    const button = document.getElementById("new-btn");
    if (!button)
        return;
    button.addEventListener("click", () => {
        showToast("新規追加ダイアログを開きました（モック）");
    });
}
/** 詳細画面の編集モードを切り替える */
function bindEditMode() {
    const editBtn = document.getElementById("edit-btn");
    const cancelBtn = document.getElementById("cancel-btn");
    const saveBtn = document.getElementById("save-btn");
    if (!editBtn || !cancelBtn || !saveBtn)
        return;
    /** 編集可能フィールドの readonly 属性を切り替える */
    function setEditing(editing) {
        document.querySelectorAll(".field-value input, .field-value textarea").forEach((field) => {
            if (editing)
                field.removeAttribute("readonly");
            else
                field.setAttribute("readonly", "readonly");
        });
        editBtn.hidden = editing;
        cancelBtn.hidden = !editing;
        saveBtn.hidden = !editing;
    }
    editBtn.addEventListener("click", () => setEditing(true));
    cancelBtn.addEventListener("click", () => setEditing(false));
    saveBtn.addEventListener("click", () => {
        setEditing(false);
        showToast("変更を保存しました（モック）");
    });
}
/* showToast の表示を消すタイマー（重ねて呼ばれたときに前のタイマーを止める） */
let toastTimer;
/** 画面下部のトーストを一定時間表示する */
function showToast(message) {
    const toast = document.getElementById("toast");
    if (!toast)
        return;
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
        toast.hidden = true;
    }, TOAST_DISPLAY_MS);
}
/* ============================================================================
 * エントリポイント
 * ---------------------------------------------------------------------------- */
/** Mock demo 画面用にトースト要素が無ければ差し込む（他画面の共通機能でも使うため） */
function ensureToastElement() {
    if (document.getElementById("toast"))
        return;
    const t = document.createElement("div");
    t.className = "toast";
    t.id = "toast";
    t.hidden = true;
    document.body.appendChild(t);
}
/* ============================================================================
 * 17. コード内の Markdown
 * ---------------------------------------------------------------------------- */
/* 中身を描いて見せる言語指定 */
const MARKDOWN_LANGS = ["markdown", "md"];
/* 描いた表示と元のコードの切り替えで、利用者の目に触れる文言 */
const CODE_VIEW_LABELS = {
    badge: "Markdown プレビュー",
    raw: "raw",
    preview: "プレビュー",
    diagram: "図",
};
/** 言語指定が markdown のコードブロックの中身を mdmark で描き、元のコードとの切り替えを付ける */
async function renderMarkdownBlocks(article) {
    // 言語のクラスは code 自身か、構文ハイライトが包む外枠のどちらかに付いている
    const blocks = [...article.querySelectorAll("pre")].flatMap((pre) => {
        const code = pre.querySelector(":scope > code");
        const langHolder = pre.classList.contains("highlight") ? pre.closest(".highlighter-rouge") : code;
        const lang = /language-([^\s]+)/.exec(langHolder?.className ?? "")?.[1];
        return code && MARKDOWN_LANGS.includes(lang) ? [{ pre, src: code.textContent }] : [];
    });
    if (blocks.length === 0)
        return;
    // mdmark を読めなかったときは元のコードのまま出す
    const mdmark = await loadMdmark();
    if (!mdmark)
        return;
    blocks.forEach(({ pre, src }) => {
        // 描いた表示の入れ物に中身を描き、左上にバッジを、右上のボタン群に中身を写すボタンを置く
        const preview = document.createElement("div");
        preview.className = "markdown-preview";
        mdmark.mount(preview, { markdown: src });
        const badge = document.createElement("span");
        badge.className = "markdown-preview-badge";
        badge.textContent = CODE_VIEW_LABELS.badge;
        preview.prepend(badge);
        codeActions(preview).appendChild(createCopyButton(() => src));
        pre.before(preview);
        pre.hidden = true;
        bindViewToggle(preview, pre, CODE_VIEW_LABELS.preview);
    });
}
/** 描いた表示と元のコードの両方へ、互いに切り替えるボタンを置く */
function bindViewToggle(rendered, raw, backLabel) {
    const toRaw = document.createElement("button");
    toRaw.type = "button";
    toRaw.className = "code-view-toggle";
    toRaw.textContent = CODE_VIEW_LABELS.raw;
    codeActions(rendered).appendChild(toRaw);
    const toRendered = document.createElement("button");
    toRendered.type = "button";
    toRendered.className = "code-view-toggle";
    toRendered.textContent = backLabel;
    codeActions(raw).appendChild(toRendered);
    // 押した側を隠して、もう一方を見せる
    toRaw.addEventListener("click", () => {
        rendered.hidden = true;
        raw.hidden = false;
    });
    toRendered.addEventListener("click", () => {
        raw.hidden = true;
        rendered.hidden = false;
    });
}
/* ============================================================================
 * 18. 図の埋め込み
 * ---------------------------------------------------------------------------- */
/** リンクの断片を除いた場所を作る */
function withoutHash(url) {
    const bare = new URL(url);
    bare.hash = "";
    return bare;
}
/** 段落にリンク 1 本だけを置いた位置へ、リンク先の見出しの下の図を置く */
async function embedDiagrams(article) {
    // 埋め込みのリンクを持つ段落: 中身がリンク 1 本だけで、断片を持ち、同じ配信の別のページを指す
    // （本文の直下と節の入れ物の直下の段落。表・箇条書き・引用の中の段落は含めない）
    const targets = [];
    article.querySelectorAll(":scope > p, :scope .mdmark-section-body > p").forEach((p) => {
        const link = p.firstElementChild;
        if (p.childElementCount !== 1 || link.tagName !== "A")
            return;
        if (p.textContent.trim() !== link.textContent.trim())
            return;
        const url = new URL(link.href, location.href);
        if (url.hash.length <= 1)
            return;
        if (url.origin !== location.origin || url.pathname === location.pathname)
            return;
        targets.push({ paragraph: p, url });
    });
    if (targets.length === 0)
        return;
    // 同じページを指すリンクで 1 度だけ読むための入れ物
    const cache = new Map();
    await Promise.all(targets.map(async ({ paragraph, url }) => {
        // 断片をパーセントデコードする。デコードできなければ段落を残す
        let fragment;
        try {
            fragment = decodeURIComponent(url.hash.slice(1));
        }
        catch (e) {
            console.warn("埋め込みのリンクの断片をデコードできません", url.href, e);
            return;
        }
        // リンク先のページを読む。読めなければ段落を残す
        const pageUrl = withoutHash(url);
        const doc = await fetchSourcePage(pageUrl, cache);
        if (!doc)
            return;
        // 断片が指す見出しの下の図を取り出す。取り出せなければ段落を残す
        const extracted = await extractDiagramSources(doc, fragment);
        if (!extracted)
            return;
        // 図ごとにリンクを直して枠に入れ、段落を枠の並びで置き換える
        const figures = extracted.sources.map((source) => buildEmbedFigure(rebaseDiagramLinks(source, pageUrl), extracted, pageUrl));
        paragraph.replaceWith(...figures);
    }));
}
/** 埋め込み元のページを、今のページと同じ配信から読む */
async function fetchSourcePage(url, cache) {
    // 同じ場所の読み込みが入れ物にあれば、その結果を返す
    const cached = cache.get(url.href);
    if (cached)
        return cached;
    const loading = (async () => {
        try {
            const res = await fetch(url);
            // 応答が成功でない場合は読めなかったものとして扱う
            if (!res.ok)
                return null;
            return new DOMParser().parseFromString(await res.text(), "text/html");
        }
        catch (e) {
            console.warn("埋め込み元のページを読めません", url.href, e);
            return null;
        }
    })();
    cache.set(url.href, loading);
    return loading;
}
/** 断片が指す見出しの下にある図の元のコードを、文書順に集める（元のページの本文の Markdown を mdmark の render で描いてから探す） */
async function extractDiagramSources(doc, fragment) {
    // 元のページの本文の Markdown を探す
    const source = doc.querySelector("textarea[data-mdmark-source]");
    if (!source)
        return null;
    const mdmark = await loadMdmark();
    if (!mdmark)
        return null;
    // 文書に繋がない要素の中へ描く
    const body = document.createElement("div");
    body.innerHTML = mdmark.render(source.value.replace(LIQUID_RAW_PATTERN, ""));
    // 断片と一致する最初の見出しを探す
    const heading = [...body.querySelectorAll("h1, h2, h3, h4, h5, h6")].find((h) => h.id === fragment);
    if (!heading)
        return null;
    // 見出しの節の中から図の元のコードを集める。節の入れ物が無い見出しは、深さが同じか浅い見出しに当たるまで辿る
    const sources = [];
    const section = heading.nextElementSibling?.matches(".mdmark-section-body") ? heading.nextElementSibling : null;
    if (section) {
        section.querySelectorAll("pre > code.language-mermaid").forEach((code) => sources.push(code.textContent));
    }
    else {
        const depth = Number(heading.tagName[1]);
        for (let el = heading.nextElementSibling; el; el = el.nextElementSibling) {
            if (/^H[1-6]$/.test(el.tagName) && Number(el.tagName[1]) <= depth)
                break;
            el.querySelectorAll("pre > code.language-mermaid").forEach((code) => sources.push(code.textContent));
        }
    }
    if (sources.length === 0)
        return null;
    // ページの題名は本文の h1、無ければ文書の title
    const pageTitle = body.querySelector("h1")?.textContent.trim() || doc.title;
    return { pageTitle, headingText: headingText(heading), headingId: heading.id, sources };
}
/** 図の元のコードの中のリンクを、差し込み先のページでも同じ先を指す形へ直す */
function rebaseDiagramLinks(source, fromUrl) {
    return source.replace(/(\bclick\s+\S+\s+(?:href\s+)?")([^"]*)(")/g, (whole, head, link, tail) => {
        // スキーム付きの絶対 URL はそのままにする
        if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(link))
            return whole;
        // 相対リンクは元の場所を基準に解決し、配信のルートからのパスと断片へ置き換える
        let resolved;
        try {
            resolved = new URL(link, fromUrl);
        }
        catch (e) {
            // 解決できないリンクはその行をそのままにして、他のリンクと図の埋め込みは続ける
            console.warn("図の中のリンクを解決できません", link, e);
            return whole;
        }
        return `${head}${resolved.pathname}${resolved.search}${resolved.hash}${tail}`;
    });
}
/** 図の元のコードと埋め込み元の表示を、1 つの枠に組む */
function buildEmbedFigure(source, extracted, pageUrl) {
    // 自ページの図と同じ形にして、Mermaid の描画が同じ描き方で拾えるようにする
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.className = "language-mermaid";
    code.textContent = source;
    pre.appendChild(code);
    // 図の下に、埋め込み元の見出しへのリンクを置く
    const from = new URL(pageUrl);
    from.hash = extracted.headingId;
    const link = document.createElement("a");
    link.href = `${from.pathname}${from.search}${from.hash}`;
    link.textContent = `${extracted.pageTitle} › ${extracted.headingText}`;
    const caption = document.createElement("figcaption");
    caption.className = "embed-caption";
    caption.append("埋め込み元: ", link);
    const figure = document.createElement("figure");
    figure.className = "embed-figure";
    figure.append(pre, caption);
    return figure;
}
/* ============================================================================
 * 19. コメント
 * 選んだ文字列へのコメントを溜め、見出しと行き来し、まとめてコピー・起票する。トップバーのコメントのボタンを持たないページでは何もしない
 * ---------------------------------------------------------------------------- */
/* Octicons（16px）の形。絵文字は使わない */
const OCTICONS = {
    x: '<svg class="icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></svg>',
    history: '<svg class="icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="m.427 1.927 1.215 1.215a8.002 8.002 0 1 1-1.6 5.685.75.75 0 1 1 1.493-.154 6.5 6.5 0 1 0 1.18-4.458l1.358 1.358A.25.25 0 0 1 3.896 6H.25A.25.25 0 0 1 0 5.75V2.104a.25.25 0 0 1 .427-.177ZM7.75 4a.75.75 0 0 1 .75.75v2.992l2.028.812a.75.75 0 0 1-.557 1.392l-2.5-1A.751.751 0 0 1 7 8.25v-3.5A.75.75 0 0 1 7.75 4Z"/></svg>',
    link: '<svg class="icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="m7.775 3.275 1.25-1.25a3.5 3.5 0 1 1 4.95 4.95l-2.5 2.5a3.5 3.5 0 0 1-4.95 0 .751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018 1.998 1.998 0 0 0 2.83 0l2.5-2.5a2.002 2.002 0 0 0-2.83-2.83l-1.25 1.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042Zm-4.69 9.64a1.998 1.998 0 0 0 2.83 0l1.25-1.25a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042l-1.25 1.25a3.5 3.5 0 1 1-4.95-4.95l2.5-2.5a3.5 3.5 0 0 1 4.95 0 .751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018 1.998 1.998 0 0 0-2.83 0l-2.5 2.5a1.998 1.998 0 0 0 0 2.83Z"/></svg>',
};
/* 数の書式 */
const numberFormat = new Intl.NumberFormat("ja-JP");
/* コメントのパネルの要素 */
let commentPanel = null;
/** コメントのパネルを、閉じた状態で本文の右の列に置く（あれば返す） */
function ensureCommentPanel(label) {
    if (commentPanel)
        return commentPanel;
    const panel = document.createElement("aside");
    panel.className = "side-panel comment-panel";
    panel.hidden = true;
    panel.setAttribute("aria-label", label);
    document.querySelector(".docs-layout")?.appendChild(panel);
    commentPanel = panel;
    return panel;
}
/* 溜めたコメントを持つ sessionStorage のキー（同じタブならページを移っても残る） */
const COMMENTS_KEY = "dev-comments";
/* 引用を短くし始める字数と、短くした引用の先頭と末尾に残す字数 */
const QUOTE_MAX = 30;
const QUOTE_KEEP = 12;
/* 移った先のコメントと見出しを目立たせる時間 */
const FLASH_MS = 1600;
/* コメントまわりの文言 */
const COMMENT_LABELS = {
    add: "コメントを追加",
    panel: "コメント",
    selectAll: "すべて選択（{selected} / {total}）",
    copy: "コピー",
    issue: "Issue を起票",
    empty: "コメントはありません",
    edit: "修正",
    delete: "削除",
    cancel: "キャンセル",
    save: "保存",
    submit: "追加",
    copied: "コピーしました",
    noSelection: "コメントを選択してください",
    required: "コメントを入力してください",
    jumpHeading: "見出しへ移動",
    jumpPage: "ページの先頭へ移動",
    open: "コメント（{count} 件）",
};
/* パネルの書く枠・修正しているコメント・移る先 */
const commentState = { draft: null, editing: null, focusId: null, sequence: 0 };
/** 溜めたコメントを読む（無い・読めない・壊れているときは空） */
function loadComments() {
    try {
        const comments = JSON.parse(sessionStorage.getItem(COMMENTS_KEY) || "[]");
        return Array.isArray(comments) ? comments : [];
    }
    catch {
        return [];
    }
}
/** コメントのボタン（Pages のトップバー）の数と読み上げ名を、溜めた数に合わせて描き直す */
function renderCommentButton(count) {
    const button = document.querySelector("[data-comment-open]");
    if (!button)
        return;
    button.setAttribute("aria-label", COMMENT_LABELS.open.replace("{count}", String(count)));
    const badge = button.querySelector("[data-comment-count]");
    if (badge)
        badge.textContent = numberFormat.format(count);
}
/** 溜めたコメントを書き、コメントのボタンの数を描き直す */
function saveComments(comments) {
    try {
        sessionStorage.setItem(COMMENTS_KEY, JSON.stringify(comments));
    }
    catch {
        // 書けなくても続ける
    }
    renderCommentButton(comments.length);
}
/** 選択範囲より前にある最後の本文の見出しの要素を返す（無ければ null） */
function headingBefore(node) {
    const article = document.querySelector(".markdown-body");
    let found = null;
    for (const heading of article.querySelectorAll("h2, h3")) {
        // 描いた markdown の中の見出しは本文の見出しではないので候補にしない
        if (heading.closest(".markdown-preview"))
            continue;
        // 見出しが選択範囲より前にあれば候補にする
        if (heading.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)
            found = heading;
    }
    return found;
}
/** 選んだ範囲の場所（ページのパスと直前の見出し）を返す */
function selectionLocation(range) {
    const heading = headingBefore(range.startContainer);
    return {
        file: document.body.dataset.pagePath,
        heading: heading ? headingText(heading) : null,
        headingId: heading?.id || null,
    };
}
/** 選んだ文字列を引用の形にする（書記素で数え、長ければ先頭と末尾だけを残す） */
function shortenQuote(text) {
    const flat = text.replace(/\s+/g, " ").trim();
    const graphemes = [...new Intl.Segmenter("ja", { granularity: "grapheme" }).segment(flat)].map((s) => s.segment);
    if (graphemes.length <= QUOTE_MAX)
        return flat;
    return `${graphemes.slice(0, QUOTE_KEEP).join("")} ... ${graphemes.slice(-QUOTE_KEEP).join("")}`;
}
/** コメントの場所の文言を作る */
function formatLocation(comment) {
    // 見出しがあれば見出しで、無ければページのパスだけで書く
    if (comment.heading)
        return `${comment.file} › ${comment.heading}`;
    return comment.file;
}
/** 今のページの URL（パスとクエリ） */
function currentPageUrl() {
    return `${window.location.pathname}${window.location.search}`;
}
/** 本文の文字列を選んだときに、選択の下へ「コメントを追加」を出す */
function bindCommentEntry(article) {
    // ボタンを作り、隠した状態で置く
    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary selection-comment";
    button.textContent = COMMENT_LABELS.add;
    button.hidden = true;
    document.body.appendChild(button);
    let pending = null;
    // 選択の変化のたびに出し分ける
    document.addEventListener("selectionchange", () => {
        const selection = document.getSelection();
        const text = selection?.toString().trim();
        // 選択が空、または本文の外なら隠す
        if (!selection || !text || !selection.rangeCount || !article.contains(selection.anchorNode)) {
            button.hidden = true;
            return;
        }
        // 場所と引用を控え、選択の下へボタンを置いて出す
        const range = selection.getRangeAt(0);
        const fragment = range.cloneContents();
        fragment.querySelectorAll(".mdmark-anchor, .mdmark-th-tools, .mdmark-row-toggle, .mdmark-visually-hidden").forEach((el) => el.remove());
        pending = { ...selectionLocation(range), quote: shortenQuote(fragment.textContent) };
        const rect = range.getBoundingClientRect();
        button.style.top = `${window.scrollY + rect.bottom + 8}px`;
        button.style.left = `${window.scrollX + Math.max(8, Math.min(rect.left, window.innerWidth - 160))}px`;
        button.hidden = false;
    });
    // 押し下げたときは、選択が外れないよう既定の動きを止める
    button.addEventListener("mousedown", (event) => event.preventDefault());
    // 出している間の Esc でボタンだけを隠す（選択は残し、次に選択が変わるまで出さない）
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape")
            button.hidden = true;
    });
    // 押下で書く枠を出してパネルを開き、ボタンを隠して選択を外す
    button.addEventListener("click", () => {
        button.hidden = true;
        openCommentPanel({ draft: pending });
        document.getSelection()?.removeAllRanges();
    });
}
/** コメントのパネルを開く */
function openCommentPanel({ draft = null, focusId = null } = {}) {
    // 書く枠の値を控えてパネルを描き、開いた状態にする
    commentState.draft = draft;
    commentState.focusId = focusId;
    const panel = ensureCommentPanel(COMMENT_LABELS.panel);
    renderCommentPanel();
    panel.hidden = false;
    document.body.classList.add("side-open");
    syncHeaderCommentButton(true);
    // 書く枠があれば書く枠まで送って入力欄へ、移る先があればそのコメントまで送って目立たせる
    const input = panel.querySelector("[data-comment-body]");
    if (input) {
        input.closest("form").scrollIntoView({ block: "nearest" });
        input.focus({ preventScroll: true });
    }
    else {
        panel.querySelector("h2").focus({ preventScroll: true });
    }
    flashComment(focusId);
}
/** Pages のヘッダーのコメントのボタンの押した状態を、パネルの開閉に合わせる */
function syncHeaderCommentButton(open) {
    document.querySelector(".topbar [data-comment-open]")?.setAttribute("aria-expanded", String(open));
}
/** 移る先のコメントまで送って一時だけ目立たせる */
function flashComment(id) {
    if (!id || !commentPanel)
        return;
    const item = commentPanel.querySelector(`[data-comment-id="${CSS.escape(id)}"]`);
    if (!item)
        return;
    item.scrollIntoView({ block: "nearest" });
    item.classList.add("flash");
    window.setTimeout(() => item.classList.remove("flash"), FLASH_MS);
}
/** コメントのパネルを閉じる（溜めたコメントは残す） */
function closeCommentPanel() {
    const panel = commentPanel;
    if (!panel || panel.hidden)
        return;
    panel.hidden = true;
    commentState.draft = null;
    commentState.editing = null;
    document.body.classList.remove("side-open");
    syncHeaderCommentButton(false);
}
/** コメント 1 つの HTML */
function commentItemHtml(comment) {
    const editing = commentState.editing === comment.id;
    // 移動のボタンの読み上げ名: 見出しがあれば見出し、無ければページの先頭
    const jumpLabel = comment.heading ? COMMENT_LABELS.jumpHeading : COMMENT_LABELS.jumpPage;
    const body = editing
        ? `<textarea rows="3" data-edit-body aria-label="${COMMENT_LABELS.panel}">${escapeHtml(comment.body)}</textarea>
       <p class="comment-error" hidden>${COMMENT_LABELS.required}</p>
       <div class="comment-actions">
         <button type="button" class="ghost" data-edit-cancel>${COMMENT_LABELS.cancel}</button>
         <button type="button" class="primary" data-edit-save>${COMMENT_LABELS.save}</button>
       </div>`
        : `<p class="comment-body">${escapeHtml(comment.body)}</p>
       <div class="comment-actions">
         <button type="button" class="ghost" data-comment-edit>${COMMENT_LABELS.edit}</button>
         <button type="button" class="ghost" data-comment-delete>${COMMENT_LABELS.delete}</button>
       </div>`;
    return `
    <li class="comment" data-comment-id="${escapeHtml(comment.id)}">
      <div class="comment-head">
        <input type="checkbox" data-comment-check${comment.selected ? " checked" : ""} aria-label="選択">
        <span class="comment-place">${escapeHtml(formatLocation(comment))}</span>
        <button type="button" class="ghost icon-button" data-comment-jump aria-label="${jumpLabel}" title="${jumpLabel}">${OCTICONS.link}</button>
      </div>
      <blockquote class="comment-quote">${escapeHtml(comment.quote)}</blockquote>
      ${body}
    </li>`;
}
/** 溜めたコメントからパネルの中身を描き直す */
function renderCommentPanel() {
    const panel = commentPanel;
    if (!panel)
        return;
    const comments = loadComments();
    const draft = commentState.draft;
    const selected = comments.filter((c) => c.selected).length;
    // 見出しと閉じるボタン、コメントがあれば一覧の上にすべて選択・起票・コピー
    const toolbar = comments.length === 0 ? "" : `
    <div class="comment-toolbar">
      <label class="comment-all"><input type="checkbox" data-comment-all> ${COMMENT_LABELS.selectAll.replace("{selected}", String(selected)).replace("{total}", String(comments.length))}</label>
      <div class="comment-toolbar-actions">
        <button type="button" class="ghost" data-comment-issue>${COMMENT_LABELS.issue}</button>
        <button type="button" class="primary" data-comment-copy>${COMMENT_LABELS.copy}</button>
      </div>
    </div>`;
    const list = comments.length === 0 ? "" : `<ul class="comment-list">${comments.map(commentItemHtml).join("")}</ul>`;
    // 書く枠の値があれば、最後のコメントのすぐ下（無ければ一番上）に置く
    const form = !draft ? "" : `
    <form class="comment-compose" data-comment-form novalidate>
      <p class="comment-place">${escapeHtml(formatLocation(draft))}</p>
      <blockquote class="comment-quote">${escapeHtml(draft.quote)}</blockquote>
      <textarea rows="3" data-comment-body aria-label="${COMMENT_LABELS.panel}"></textarea>
      <p class="comment-error" hidden>${COMMENT_LABELS.required}</p>
      <div class="comment-actions">
        <button type="button" class="ghost" data-comment-cancel>${COMMENT_LABELS.cancel}</button>
        <button type="submit" class="primary">${COMMENT_LABELS.submit}</button>
      </div>
    </form>`;
    // コメントも書く枠も無ければ、無いことを出す
    const empty = comments.length === 0 && !draft ? `<p class="comment-empty">${COMMENT_LABELS.empty}</p>` : "";
    const scrollTop = panel.scrollTop;
    panel.innerHTML = `
    <div class="side-panel-head">
      <h2 tabindex="-1">${COMMENT_LABELS.panel}</h2>
      <button type="button" class="ghost icon-button" data-comment-close aria-label="閉じる">${OCTICONS.x}</button>
    </div>
    ${toolbar}${list}${form}${empty}`;
    panel.scrollTop = scrollTop;
    panel.querySelector("[data-comment-close]").addEventListener("click", closeCommentPanel);
    // すべて選択: 全てなら選んだ状態、一部なら途中の状態、1 つも無ければ外した状態
    const all = panel.querySelector("[data-comment-all]");
    if (all) {
        all.checked = selected === comments.length;
        all.indeterminate = selected > 0 && selected < comments.length;
        all.addEventListener("change", () => {
            saveComments(loadComments().map((c) => ({ ...c, selected: all.checked })));
            renderCommentPanel();
        });
    }
    panel.querySelector("[data-comment-copy]")?.addEventListener("click", (event) => copyComments(event.currentTarget));
    panel.querySelector("[data-comment-issue]")?.addEventListener("click", (event) => openIssueFromComments(event.currentTarget));
    // コメントごとの操作
    panel.querySelectorAll("[data-comment-id]").forEach((item) => {
        const id = item.dataset.commentId;
        item.querySelector("[data-comment-check]").addEventListener("change", (event) => {
            saveComments(loadComments().map((c) => (c.id === id ? { ...c, selected: event.target.checked } : c)));
            renderCommentPanel();
        });
        item.querySelector("[data-comment-jump]").addEventListener("click", () => {
            const comment = loadComments().find((c) => c.id === id);
            if (comment)
                jumpToHeading(comment);
        });
        item.querySelector("[data-comment-edit]")?.addEventListener("click", () => {
            commentState.editing = id;
            renderCommentPanel();
            panel.querySelector("[data-edit-body]")?.focus();
        });
        item.querySelector("[data-comment-delete]")?.addEventListener("click", () => deleteComment(id));
        item.querySelector("[data-edit-cancel]")?.addEventListener("click", () => {
            commentState.editing = null;
            renderCommentPanel();
        });
        item.querySelector("[data-edit-save]")?.addEventListener("click", () => {
            updateComment(id, item.querySelector("[data-edit-body]").value);
        });
    });
    // 書く枠のキャンセルと追加
    panel.querySelector("[data-comment-cancel]")?.addEventListener("click", () => {
        commentState.draft = null;
        renderCommentPanel();
    });
    panel.querySelector("[data-comment-form]")?.addEventListener("submit", (event) => {
        event.preventDefault();
        addComment(draft, panel.querySelector("[data-comment-body]").value);
    });
}
/** 入力チェックのエラーを入力欄の下に出す */
function showCommentError(input) {
    const error = input.parentElement.querySelector(".comment-error");
    if (error)
        error.hidden = false;
    input.setAttribute("aria-invalid", "true");
    input.focus();
}
/** 書く枠の本文を、選んだ状態のコメントとして一覧の末尾へ足す */
function addComment(draft, body) {
    const input = commentPanel?.querySelector("[data-comment-body]");
    // 本文が空白だけなら、入力欄の下にエラーを出す（入力は消さない）
    if (!body.trim()) {
        if (input)
            showCommentError(input);
        return false;
    }
    commentState.sequence += 1;
    const id = `c-${Date.now()}-${commentState.sequence}`;
    const comment = { ...draft, id, body: body.trim(), page: currentPageUrl(), selected: true, copied: false };
    // 末尾へ足して保存し、書く枠を閉じてパネルを描き直す
    saveComments([...loadComments(), comment]);
    commentState.draft = null;
    renderCommentPanel();
    // 足したコメントまで送って一時だけ目立たせる
    flashComment(id);
    return true;
}
/** コメントの本文を直し、コピー済みを外す */
function updateComment(id, body) {
    const input = commentPanel?.querySelector("[data-edit-body]");
    if (!body.trim()) {
        if (input)
            showCommentError(input);
        return false;
    }
    saveComments(loadComments().map((c) => (c.id === id ? { ...c, body: body.trim(), copied: false } : c)));
    commentState.editing = null;
    renderCommentPanel();
    return true;
}
/** コメントを一覧から消す */
function deleteComment(id) {
    saveComments(loadComments().filter((c) => c.id !== id));
    renderCommentPanel();
}
/** 選んだコメントを一覧の順にクリップボードへ書く形にまとめる */
function buildClipboardText(comments) {
    return comments.map((c) => `${formatLocation(c)}\n> ${c.quote}\n\n${c.body}`).join("\n\n---\n\n");
}
/** 選んだコメントをまとめてクリップボードへ書く（写せなかったときは、押したボタンの下に写せなかったときの面を出す） */
async function copyComments(source) {
    const comments = loadComments();
    const selected = comments.filter((c) => c.selected);
    // 選んだコメントが無ければ通知を出して終わる
    if (selected.length === 0) {
        showToast(COMMENT_LABELS.noSelection);
        return false;
    }
    // 写せなければ、まとめた文字列を入れた写せなかったときの面を出して終わる（通知は出さない）
    const text = buildClipboardText(selected);
    if (!(await writeClipboard(text))) {
        showCopyFallback(source, text);
        return false;
    }
    // 選んだコメントの copied を付けて保存し、通知を出す
    saveComments(comments.map((c) => (c.selected ? { ...c, copied: true } : c)));
    showToast(COMMENT_LABELS.copied);
    return true;
}
/** 選んだコメントをコピーしてから、GitHub の Issue の起票画面を別のタブで開く */
async function openIssueFromComments(source) {
    // 書けなかった場合（選んだコメントが無い・写せなかったときの面を出した）、開かずに終わる
    if (!(await copyComments(source)))
        return;
    const repo = document.body.dataset.issueRepo || "";
    const params = new URLSearchParams({ labels: issueLabels().join(",") });
    window.open(`https://github.com/${repo}/issues/new?${params.toString()}`, "_blank", "noopener");
}
/** コメントの場所の見出しへ移り、見出しを一時だけ目立たせる（見出しが無いコメントはページの先頭へ移る） */
function jumpToHeading(comment) {
    // コメントのページが今のページでなければ、そのページを見出しの断片付き（無ければ断片なし）で開いて終わる
    const target = new URL(comment.page, window.location.href);
    if (`${target.pathname}${target.search}` !== currentPageUrl()) {
        target.hash = comment.headingId ?? "";
        navigateWithin(target.href);
        return;
    }
    // 狭い幅ならパネルを閉じる
    if (mobileQuery.matches)
        closeCommentPanel();
    const heading = comment.headingId ? document.getElementById(comment.headingId) : null;
    // 見出しが無いコメントはページの先頭へ移る
    if (!heading) {
        window.scrollTo({ top: 0 });
        return;
    }
    // 見出しを包む閉じた節を開いてから移り、一時だけ目立たせる
    revealSection(heading);
    heading.scrollIntoView({ block: "center" });
    heading.classList.add("line-flash");
    window.setTimeout(() => heading.classList.remove("line-flash"), FLASH_MS);
}
/** Pages のヘッダーのコメントのボタンに、パネルを開く動きと溜めた数を紐付ける */
function bindHeaderCommentButton() {
    const button = document.querySelector(".topbar [data-comment-open]");
    if (!button)
        return;
    renderCommentButton(loadComments().length);
    syncHeaderCommentButton(false);
    // 押下で書く枠を出さずにパネルを開く
    button.addEventListener("click", () => openCommentPanel());
}
/** 同じ配信の中へ移る間だけ立て、離脱の確認を出さない印 */
let movingWithin = false;
/** 行き先が同じ配信の中の別の文書（オリジンが同じで、パスが data-site-root の下にあり、パスかクエリ文字列が今のページと違う）か。断片だけが違うときはページを離れない */
function isOtherDocumentWithin(url) {
    const siteRoot = document.body.dataset.siteRoot || "/";
    return url.origin === window.location.origin
        && decodeURIComponent(url.pathname).startsWith(decodeURIComponent(siteRoot))
        && `${url.pathname}${url.search}` !== currentPageUrl();
}
/** スクリプトから別のページへ移る。同じ配信の中の別の文書へ移るときは、離脱の確認を出さない印を立ててから移る */
function navigateWithin(href) {
    // 同じ配信の中の別の文書へ移る場合だけ印を立てる（断片だけが違うと印が残り、後でタブを閉じても確認が出なくなる。違うオリジンと data-site-root の外はコピーしていないコメントがあれば確認が出る）
    if (isOtherDocumentWithin(new URL(href, window.location.href)))
        movingWithin = true;
    window.location.href = href;
}
/** コピーしていないコメントがあるままタブを閉じる・再読み込みするときに、離脱の確認を出す */
function bindLeaveGuard() {
    // 同じ配信の中の別の文書へのリンクの押下で、離脱の確認を出さない印を立てる
    window.addEventListener("click", (event) => {
        const link = event.target.closest?.("a[href]");
        if (!link || event.defaultPrevented || (link.target && link.target !== "_self"))
            return;
        if (isOtherDocumentWithin(new URL(link.href, window.location.href)))
            movingWithin = true;
    });
    window.addEventListener("beforeunload", (event) => {
        if (movingWithin || !loadComments().some((c) => !c.copied))
            return;
        event.preventDefault();
        event.returnValue = "";
    });
}
/** 入口・離脱の確認・ヘッダーのコメントのボタンをまとめて紐付ける */
function bindComments(article) {
    // トップバーのコメントのボタンを持たないページでは何もしない
    if (!document.querySelector(".topbar [data-comment-open]"))
        return;
    bindCommentEntry(article);
    bindLeaveGuard();
    bindHeaderCommentButton();
    // Esc でコメントのパネルを閉じる
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape")
            closeCommentPanel();
    });
}
/* ============================================================================
 * 20. 本文の描画
 * 本文の Markdown（textarea[data-mdmark-source]）を、既定で閉じる見出しの指定を差し込んでから mdmark の mount で描く。
 * 見出しの節の開閉・アンカー・表・タブ・ステップ・ファイルツリー・コードの行の印・バッジ・注意書きは mdmark が描く
 * ---------------------------------------------------------------------------- */
/* mdmark の配布物の場所（app.js からの相対） */
const MDMARK_MODULE = "vendor/mdmark/index.js";
/* Liquid の `raw` / `endraw` のタグ（空白を削る `-` 付きのタグも当てる） */
const LIQUID_RAW_PATTERN = /\{%-?\s*(?:end)?raw\s*-?%\}/g;
/* ページを開いた時点で節を閉じる見出し。`#` の数が階層、空白の後ろが見出し名 */
const CLOSED_SECTION_HEADINGS = [
    "#### セットアップ",
    "#### フロー",
    "#### 期待値",
    "#### 単体テスト",
    "### 補足",
    "### 記述例",
    "### 異常系",
];
/* 見出しの直後のコメントから `section:` の値を取り出す */
const SECTION_DIRECTIVE_PATTERN = /^\s*section:\s*(\S+)\s*$/;
/* 既定で閉じる指定の行 */
const SECTION_CLOSED_LINE = "<!-- section: closed -->";
/* app.js を読み込んだ時点のスクリプトの場所（動的 import の基準。読み込みが終わると currentScript は無くなる） */
const APP_SCRIPT_URL = document.currentScript?.src ?? "";
/* mdmark の読み込みの結果（1 ページで 1 度だけ読む） */
let mdmarkLoading = null;
/** mdmark の配布物を読み込む（読めなければ null） */
function loadMdmark() {
    if (!mdmarkLoading) {
        const url = new URL(MDMARK_MODULE, APP_SCRIPT_URL || window.location.href).href;
        mdmarkLoading = import(url).then((module) => module).catch((e) => {
            console.warn("mdmark を読み込めません", url, e);
            return null;
        });
    }
    return mdmarkLoading;
}
/** 見出しの階層と文言が、既定で閉じる見出しに当たるかを返す */
function matchesClosedHeading(level, text) {
    return CLOSED_SECTION_HEADINGS.some((entry) => {
        const space = entry.indexOf(" ");
        const marks = entry.slice(0, space);
        const name = entry.slice(space + 1);
        // 同じ階層で、名前が同じか、名前の直後が全角の「（」で始まる
        return marks.length === level && (text === name || text.startsWith(`${name}（`));
    });
}
/** h2〜h4 の見出しのうち既定で閉じる見出しの直後に、mdmark の閉じる指定の行を差し込む（差し込んだ後の行 → 差し込む前の行を添える） */
function injectClosedSections(markdown) {
    const lines = markdown.split("\n");
    const out = [];
    const origins = [];
    // 開いているコードブロックの囲み（開いていなければ空）
    let fence = "";
    lines.forEach((line, index) => {
        out.push(line);
        origins.push(index);
        const fenceMatch = /^\s*(`{3,}|~{3,})/.exec(line);
        // コードブロックの中の行は見出しとして読まない（閉じは同じ文字で開きと同じ長さ以上の囲み）
        if (fence) {
            if (fenceMatch && fenceMatch[1][0] === fence[0] && fenceMatch[1].length >= fence.length)
                fence = "";
            return;
        }
        if (fenceMatch) {
            fence = fenceMatch[1];
            return;
        }
        const heading = /^(#{2,4})[ \t]+(.*?)[ \t]*#*[ \t]*$/.exec(line);
        if (!heading || !matchesClosedHeading(heading[1].length, heading[2].trim()))
            return;
        // 見出しの直後が開閉の指定のコメントなら、書き手の指定を使う
        const next = /^\s*<!--(.*)-->\s*$/.exec(lines[index + 1] ?? "");
        if (next && SECTION_DIRECTIVE_PATTERN.test(next[1]))
            return;
        out.push(SECTION_CLOSED_LINE);
        origins.push(index);
    });
    return { markdown: out.join("\n"), origins };
}
/** 本文に埋め込んだ Markdown を mdmark の mount で描く（描いたかを返す） */
async function mountBody(article) {
    // 埋め込んだ Markdown が無いページ（モックの実画面・計画画面）は何もしない
    const source = article.querySelector("textarea[data-mdmark-source]");
    if (!source)
        return false;
    // Liquid の raw のタグを取り除き、既定で閉じる見出しの指定を差し込む
    const { markdown } = injectClosedSections(source.value.replace(LIQUID_RAW_PATTERN, ""));
    const mdmark = await loadMdmark();
    // 読めなければ Markdown の文字のまま出す
    if (!mdmark) {
        const raw = document.createElement("pre");
        raw.textContent = source.value;
        article.replaceChildren(raw);
        return false;
    }
    mdmark.mount(article, { markdown });
    return true;
}
/** 要素を包む閉じた節を外側から順に開き、要素を包む隠れたタブを選ぶ */
function revealSection(target) {
    // 要素から親をたどって隠れた節の中身を集め、直前の見出しの開閉のボタンを外側から順に押す
    const closed = [];
    for (let body = target.closest(".mdmark-section-body[hidden]"); body; body = body.parentElement?.closest(".mdmark-section-body[hidden]") ?? null) {
        closed.unshift(body);
    }
    closed.forEach((body) => body.previousElementSibling?.querySelector(".mdmark-section-toggle")?.click());
    // 隠れたタブの中にあれば、その中身を指すタブを押して選ぶ
    const panel = target.closest(".mdmark-tab-panel[hidden]");
    if (panel)
        document.querySelector(`.mdmark-tab[aria-controls="${CSS.escape(panel.id)}"]`)?.click();
}
/** URL の断片（`#` 付き）が指す要素を返す。符号化が壊れていれば要素は無いものとして扱う */
function fragmentTarget(fragment) {
    try {
        return document.getElementById(decodeURIComponent(fragment.slice(1)));
    }
    catch (e) {
        console.warn("URL の断片をデコードできません", fragment, e);
        return null;
    }
}
/** 目次・本文のリンク・URL の見出しの指定で閉じた節の中の要素へ移るとき、移る前に包む節を開く */
function bindSectionReveal(article) {
    // 目次・本文のリンクで閉じた節の中の見出しへ移るときは、移る前に節を開く
    document.addEventListener("click", (event) => {
        const link = event.target.closest?.('a[href^="#"]');
        const target = link && fragmentTarget(link.getAttribute("href"));
        if (target)
            revealSection(target);
    }, true);
    // URL の見出しの指定へ移るとき、包む節を開いてから移る（開いた直後は着地の位置がずれるので移り直す）
    const revealFragment = () => {
        const target = fragmentTarget(window.location.hash);
        if (!target || !article.contains(target))
            return;
        revealSection(target);
        target.scrollIntoView();
    };
    window.addEventListener("hashchange", revealFragment);
    revealFragment();
}
async function init() {
    ensureToastElement();
    // 1. テーマを先に決める（フラッシュ抑止）
    bindThemeToggle();
    // 2. 共通レイアウトを組み立てる
    buildBreadcrumb();
    const article = document.querySelector(".markdown-body");
    const docsLayout = document.querySelector(".docs-layout");
    const sidebarSource = document.querySelector("[data-sidebar-source]");
    const nav = renderSidebar(sidebarSource, document.body.dataset.tab, document.body.dataset.page);
    const drawerToggle = document.querySelector("[data-drawer-toggle]");
    if (nav && docsLayout) {
        docsLayout.prepend(nav);
        layout.nav = nav;
        drawerToggle?.addEventListener("click", () => openDrawer(nav));
    }
    else {
        docsLayout?.classList.add("no-sidebar");
        if (drawerToggle)
            drawerToggle.hidden = true;
    }
    bindBackToTop();
    // 3. 本文を mdmark で描き、描いた本文へ後処理を掛ける（描かなかったページ＝埋め込んだ Markdown を持たないモックの実画面・計画画面では掛けない）
    const mounted = article ? await mountBody(article) : false;
    if (article && mounted) {
        addCodeLangLabels();
        // 閉じた節の中の見出しへ移るとき、移る前に包む節を開く
        bindSectionReveal(article);
    }
    // 4. 見出しが確定してから目次を置く
    buildToc();
    // コメントを紐付ける（トップバーにコメントのボタンを持たないページでは何もしない）
    if (article && mounted)
        bindComments(article);
    // 5. markdown のコードブロックの中身を描く（描いた見出しを目次に載せず、描いた中の Mermaid も図にするため、目次の後・図の前）
    if (article && mounted)
        await renderMarkdownBlocks(article);
    // 6. 検索と起票の入口を紐付ける
    bindSearchEntries();
    bindIssueEntries();
    // 7. 幅に応じてナビゲーションの配置を決め、以降の幅の変化にも追随させる
    applyWidth();
    mobileQuery.addEventListener("change", applyWidth);
    tocInlineQuery.addEventListener("change", applyWidth);
    // 8. モックのページであればデモの操作を紐付ける
    bindSearchFilter();
    bindRowClick();
    bindNewButton();
    bindEditMode();
    // 9. 別ページの見出しの図をリンクの位置へ置く（置いた図も描くため、図を描く前。元のページの応答待ちが、ここまでの処理を止めないよう最後の方に置く）
    if (article && mounted)
        await embedDiagrams(article);
    // 10. 図を描く
    if (article && mounted)
        await renderMermaid(article);
}
document.addEventListener("DOMContentLoaded", init);
