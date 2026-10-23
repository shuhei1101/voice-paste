"use strict";
// 外の端末のブラウザで開く文字起こしの画面。
// 録音（MediaRecorder）かファイルを PC の常駐アプリへ送り、結果を取りに行って端末に残す。
// 端末に残すのは、画面で録った直近 1 件の音声（IndexedDB）と、結果の一覧（localStorage）。
// ===== 定数 =====
/** 本文の上限（バイト。これ以上は送らない）。常駐アプリの BodyLimitMiddleware と同じ値。 */
const BODY_LIMIT_BYTES = 100_000_000;
/** 画面の録音の上限時間（秒）。 */
const RECORDING_LIMIT_SEC = 1800;
/** MediaRecorder に渡すビットレート（bps）。 */
const AUDIO_BITS_PER_SECOND = 32000;
/** 残り時間をこの秒数より少なくなったら注意の色にする。 */
const LOW_REMAINING_SEC = 60;
/** MediaRecorder の形式の候補。先に isTypeSupported が真になったものを使う。 */
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'];
/** 結果を取りに行く間隔（ミリ秒）。 */
const POLL_INTERVAL_MS = 2000;
/** 端末に残す期間（ミリ秒。保存日時から 7 日）。 */
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
/** 結果を端末に残す件数。 */
const MAX_RESULTS = 10;
/** コピーした直後の表示を保つ時間（ミリ秒）。 */
const COPIED_MS = 2000;
/** 音声と結果を送る・取りに行く API の相対パス（画面は /web/ で開く）。 */
const API_PATH = 'transcriptions';
/** IndexedDB の名前・ストア・固定のキー。 */
const DB_NAME = 'voice-paste';
const DB_STORE = 'kept_audio';
const DB_KEY = 'latest';
/** 結果の一覧を残す localStorage のキー。 */
const RESULTS_STORAGE_KEY = 'voice-paste.results';
/** 画面で録った音声の元の名前。 */
const RECORDED_SOURCE = '画面録音';
/** 日時の表示に使う時間帯。 */
const TIME_ZONE = 'Asia/Tokyo';
// ===== 状態 =====
const state = {
    recording: null,
    kept: null,
    keptPercent: 0,
    fileSending: null,
    sendError: null,
    limitNotice: false,
    results: [],
    pendingDelete: null,
};
let pollTimer = null;
// ===== 要素 =====
/** 値があることを確かめる。無ければ画面の組み立ての誤りなので例外にする。 */
function present(value, name) {
    if (value === null || value === undefined)
        throw new Error(`画面に必要なものがありません: ${name}`);
    return value;
}
/** data-element の項目 ID で要素を引く。 */
const $ = (id) => present(document.querySelector(`[data-element="${id}"]`), id);
/** id 属性で要素を引く。 */
const byId = (id) => present(document.getElementById(id), id);
// ===== 整形 =====
const dateTimeFormat = new Intl.DateTimeFormat('ja-JP', {
    timeZone: TIME_ZONE,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
});
const numberFormat = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 });
/** ISO 8601 の日時を `MM/DD HH:mm` にする。 */
function formatDateTime(iso) {
    return dateTimeFormat.format(new Date(iso));
}
/** 秒数を `m:ss` にする。 */
function formatDuration(totalSec) {
    const sec = Math.max(0, Math.floor(totalSec));
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}
/** 秒数を `mm:ss` にする。 */
function formatClock(totalSec) {
    const sec = Math.max(0, Math.floor(totalSec));
    return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
}
/** バイト数を `540 KB`・`7.2 MB` の形にする（1 MB = 1,000,000 バイト）。 */
function formatBytes(bytes) {
    if (bytes < 1_000_000) {
        return `${numberFormat.format(Math.round(bytes / 1000))} KB`;
    }
    return `${numberFormat.format(bytes / 1_000_000)} MB`;
}
/** MediaRecorder の形式から、形式の名前と拡張子（webm・mp4・ogg）を返す。 */
function formatName(mimeType) {
    if (mimeType.includes('webm'))
        return 'webm';
    if (mimeType.includes('mp4'))
        return 'mp4';
    if (mimeType.includes('ogg'))
        return 'ogg';
    return 'webm';
}
/** ダウンロードのファイル名 `voice-paste_YYYYMMDD-HHmmss.{拡張子}` を作る。 */
function downloadName(kept) {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: TIME_ZONE,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hourCycle: 'h23',
    })
        .formatToParts(new Date(kept.recorded_at))
        .map((part) => [part.type, part.value]));
    const stamp = `${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}${parts.second}`;
    return `voice-paste_${stamp}.${formatName(kept.mime_type)}`;
}
// ===== 端末への保存 =====
/** IndexedDB を開く。 */
function openDb() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onupgradeneeded = () => request.result.createObjectStore(DB_STORE);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error ?? new Error('IndexedDB を開けません'));
    });
}
/** 端末内の音声のストアに対する 1 回の操作を実行して、その結果を返す。 */
async function withStore(mode, operation) {
    const db = await openDb();
    try {
        return await new Promise((resolve, reject) => {
            const transaction = db.transaction(DB_STORE, mode);
            const request = operation(transaction.objectStore(DB_STORE));
            transaction.oncomplete = () => resolve(request.result);
            transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB の操作に失敗しました'));
        });
    }
    finally {
        db.close();
    }
}
/** 端末内の音声を読む。無ければ undefined を返す。 */
const loadKept = () => withStore('readonly', (store) => store.get(DB_KEY));
/** 端末内の音声を置き換えて残す。 */
const saveKept = (kept) => withStore('readwrite', (store) => store.put(kept, DB_KEY));
/** 端末内の音声を消す。 */
const deleteKept = () => withStore('readwrite', (store) => store.delete(DB_KEY));
/** localStorage の結果の一覧を読む。読めなければ空にする。 */
function loadStoredResults() {
    try {
        const stored = JSON.parse(localStorage.getItem(RESULTS_STORAGE_KEY) ?? '[]');
        return Array.isArray(stored) ? stored : [];
    }
    catch {
        return [];
    }
}
/** 終わっていない件と届いた件だけを localStorage に残す（失敗・結果消失の件は画面を開いている間だけ出す）。 */
function saveResults() {
    const persisted = state.results
        .filter((entry) => entry.state === 'queued' || entry.state === 'running' || entry.state === 'done')
        .map((entry) => ({
        job_id: entry.jobId,
        state: entry.state,
        source: entry.source,
        duration_sec: entry.durationSec,
        sent_at: entry.sentAt,
        text: entry.text,
    }));
    localStorage.setItem(RESULTS_STORAGE_KEY, JSON.stringify(persisted));
}
/** 保存日時から期限を過ぎているか。 */
function isExpired(iso) {
    return Date.now() - new Date(iso).getTime() > RETENTION_MS;
}
// ===== 送信 =====
/** 音声を multipart の audio で送り、ステータスと本文を返す。届かなければ status を 0 にする。 */
function upload(blob, filename, onProgress) {
    return new Promise((resolve) => {
        const request = new XMLHttpRequest();
        request.open('POST', API_PATH);
        request.upload.onprogress = (event) => {
            if (event.lengthComputable)
                onProgress(Math.round((event.loaded / event.total) * 100));
        };
        request.onload = () => {
            resolve({ status: request.status, body: parseCreatedJob(request.responseText) });
        };
        request.onerror = () => resolve({ status: 0, body: null });
        request.onabort = () => resolve({ status: 0, body: null });
        const form = new FormData();
        form.append('audio', blob, filename);
        request.send(form);
    });
}
/** 202 の本文を読む。JSON でなければ null を返す。 */
function parseCreatedJob(text) {
    try {
        return JSON.parse(text);
    }
    catch {
        return null;
    }
}
/** 送信の失敗のステータスから、画面に出すエラーの見出しと本文を作る。 */
function errorForStatus(status, name, size, isFile) {
    if (status === 415) {
        return {
            title: '非対応形式',
            body: `${name} は未送信。対応形式: WAV・MP3・webm・ogg・mp4`,
        };
    }
    if (status === 413) {
        return {
            title: 'ファイルサイズ超過',
            body: `${name}（${formatBytes(size)}）は未送信。上限: 100 MB 未満。MP3 等に圧縮して再選択`,
        };
    }
    const kept = isFile ? '' : '音声は端末内に保存済み。';
    return {
        title: '送信失敗',
        body: `PC の voice-paste に接続不可。${kept}PC の起動を確認後に再送信`,
    };
}
/** 結果の一覧の先頭に、受け付けられた件を待ちで足す。10 件を超えたら古い件を消す。 */
function addResult(added) {
    const { jobId, source, durationSec } = added;
    state.results.unshift({
        jobId,
        state: 'queued',
        source,
        durationSec,
        sentAt: new Date().toISOString(),
        text: null,
        progress: 0,
        error: null,
    });
    state.results.length = Math.min(state.results.length, MAX_RESULTS);
    saveResults();
    ensurePolling();
}
/** 端末内の音声を送る。成功で結果の一覧に待ちの件を足し、失敗で送信失敗にする。 */
async function sendKept() {
    const kept = present(state.kept, 'kept');
    state.keptPercent = 0;
    render();
    const { status, body } = await upload(kept.blob, `recording.${formatName(kept.mime_type)}`, (percent) => {
        state.keptPercent = percent;
        renderKept();
    });
    state.limitNotice = false;
    if (status === 202 && body?.job_id) {
        kept.state = 'sent';
        kept.job_id = body.job_id;
        state.sendError = null;
        addResult({ jobId: body.job_id, source: RECORDED_SOURCE, durationSec: kept.duration_sec });
    }
    else {
        kept.state = 'send_failed';
        state.sendError = errorForStatus(status, RECORDED_SOURCE, kept.size_bytes, false);
    }
    await saveKept(kept);
    render();
}
/** 選んだファイルを確かめずにすぐ送る。端末内の音声は置き換えない。 */
async function sendFile(file) {
    state.sendError = null;
    // 本文の上限以上は送らずに断る
    if (file.size >= BODY_LIMIT_BYTES) {
        state.sendError = errorForStatus(413, file.name, file.size, true);
        render();
        return;
    }
    state.fileSending = { name: file.name, size: file.size, percent: 0 };
    render();
    const { status, body } = await upload(file, file.name, (percent) => {
        if (state.fileSending)
            state.fileSending.percent = percent;
        renderFileSending();
    });
    state.fileSending = null;
    if (status === 202 && body?.job_id) {
        addResult({ jobId: body.job_id, source: file.name, durationSec: null });
    }
    else {
        state.sendError = errorForStatus(status, file.name, file.size, true);
    }
    render();
}
// ===== 録音 =====
/** マイクを開いて録音を始める。開けなければエラーを出す。 */
async function startRecording() {
    state.sendError = null;
    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }
    catch {
        state.sendError = { title: 'マイク使用不可', body: 'ブラウザのマイクの許可を確認' };
        render();
        return;
    }
    const mimeType = MIME_CANDIDATES.find((candidate) => MediaRecorder.isTypeSupported(candidate));
    const options = { audioBitsPerSecond: AUDIO_BITS_PER_SECOND };
    if (mimeType)
        options.mimeType = mimeType;
    const recorder = new MediaRecorder(stream, options);
    const chunks = [];
    recorder.ondataavailable = (event) => {
        if (event.data.size > 0)
            chunks.push(event.data);
    };
    recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        void finishRecording(recorder, chunks);
    };
    const recording = { recorder, startedAt: Date.now(), elapsedSec: 0, timer: null };
    recording.timer = window.setInterval(tickRecording, 1000);
    state.recording = recording;
    recorder.start();
    render();
}
/** 1 秒ごとに経過時間を進め、上限に達したら録音を止めて送る。 */
function tickRecording() {
    const recording = state.recording;
    if (!recording)
        return;
    recording.elapsedSec = Math.floor((Date.now() - recording.startedAt) / 1000);
    if (recording.elapsedSec >= RECORDING_LIMIT_SEC) {
        recording.elapsedSec = RECORDING_LIMIT_SEC;
        state.limitNotice = true;
        stopRecording();
        return;
    }
    renderRecording();
}
/** 録音を止める。止まった音声は finishRecording が端末に残して送る。 */
function stopRecording() {
    const recording = state.recording;
    if (!recording || recording.recorder.state === 'inactive')
        return;
    recording.recorder.stop();
}
/** 止まった録音を端末（IndexedDB）に残して送る。前の 1 件は置き換わる。 */
async function finishRecording(recorder, chunks) {
    const recording = present(state.recording, 'recording');
    if (recording.timer !== null)
        clearInterval(recording.timer);
    const blob = new Blob(chunks, { type: recorder.mimeType });
    state.recording = null;
    const kept = {
        blob,
        mime_type: recorder.mimeType,
        recorded_at: new Date().toISOString(),
        duration_sec: recording.elapsedSec,
        size_bytes: blob.size,
        state: 'sending',
        job_id: null,
    };
    state.kept = kept;
    await saveKept(kept);
    await sendKept();
}
// ===== 結果の取得 =====
/** 終わっていない件があれば、取りに行く間隔の後に結果を取りに行く。 */
function ensurePolling() {
    if (pollTimer !== null)
        return;
    if (!state.results.some(isPending))
        return;
    pollTimer = window.setTimeout(() => void pollResults(), POLL_INTERVAL_MS);
}
/** 終わっていない件か。 */
function isPending(entry) {
    return entry.state === 'queued' || entry.state === 'running';
}
/** 終わっていない件の結果を取りに行く。届かない・5xx の件は次の間隔で取りに行く。 */
async function pollResults() {
    pollTimer = null;
    for (const entry of state.results.filter(isPending)) {
        await fetchResult(entry);
    }
    saveResults();
    render();
    ensurePolling();
}
/** 1 件の結果を取りに行き、状態を反映する。 */
async function fetchResult(entry) {
    let response;
    try {
        response = await fetch(`${API_PATH}/${encodeURIComponent(entry.jobId)}`);
    }
    catch {
        return;
    }
    if (response.status === 404) {
        entry.state = 'not_found';
        await markNotTranscribed(entry.jobId);
        return;
    }
    if (!response.ok)
        return;
    const job = (await response.json());
    entry.state = job.state;
    entry.progress = Math.round(job.progress * 100);
    if (job.state === 'done') {
        entry.text = job.text;
    }
    else if (job.state === 'failed') {
        entry.error = job.error;
        await markNotTranscribed(entry.jobId);
    }
}
/** そのジョブの音声が端末内に残っていれば、文字起こし前にする。 */
async function markNotTranscribed(jobId) {
    if (state.kept === null || state.kept.job_id !== jobId)
        return;
    state.kept.state = 'not_transcribed';
    await saveKept(state.kept);
}
// ===== 描画 =====
/** 画面全体を状態に合わせて描き直す。 */
function render() {
    renderSend();
    renderRecording();
    renderFileSending();
    renderKept();
    renderError();
    renderResults();
}
/** 端末内の音声が、送れていない・文字にできていない状態か。 */
function keptNeedsResend() {
    return state.kept !== null && ['send_failed', 'not_transcribed'].includes(state.kept.state);
}
/** 送信中（選んだファイル・端末内の音声）か。 */
function isSending() {
    return state.fileSending !== null || state.kept?.state === 'sending';
}
/** 録る・ファイルを選ぶのボタンと、録音中の表示の出し分けを描く。 */
function renderSend() {
    const recording = state.recording !== null;
    const sending = isSending();
    $('send_actions').hidden = recording;
    byId('send-hint').hidden = recording;
    byId('recorder').hidden = !recording;
    byId('limit-notice').hidden = !state.limitNotice;
    const recordButton = $('record_button');
    recordButton.disabled = sending;
    recordButton.classList.toggle('btn--primary', !keptNeedsResend());
    const fileInput = $('file_input');
    fileInput.disabled = sending;
    byId('file-label').setAttribute('aria-disabled', String(sending));
}
/** 録音中の経過時間・上限までのバー・残り時間を描く。 */
function renderRecording() {
    const recording = state.recording;
    if (!recording)
        return;
    const elapsed = recording.elapsedSec;
    const remaining = RECORDING_LIMIT_SEC - elapsed;
    const elapsedElement = $('recording_elapsed');
    elapsedElement.textContent = formatClock(elapsed);
    elapsedElement.setAttribute('aria-label', `経過時間 ${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒`);
    $('recording_progress').value = elapsed;
    const remainingElement = $('recording_remaining');
    const low = remaining < LOW_REMAINING_SEC;
    remainingElement.classList.toggle('recorder__left--low', low);
    remainingElement.textContent = `残り ${formatDuration(remaining)}${low ? '（上限で自動送信）' : ''}`;
}
/** 選んだファイルの送信中の行を描く。 */
function renderFileSending() {
    const sending = state.fileSending;
    byId('file-sending').hidden = sending === null;
    if (!sending)
        return;
    $('file_sending_name').textContent = `${sending.name}・${formatBytes(sending.size)}`;
    byId('file-sending-text').textContent = `送信中 ${sending.percent}%`;
    $('file_sending_progress').value = sending.percent;
}
/** 端末内の音声の行（日時・長さ・形式・大きさ、状態、操作）を描く。 */
function renderKept() {
    const kept = state.kept;
    byId('kept').hidden = kept === null;
    if (!kept)
        return;
    $('kept_meta').textContent =
        `${formatDateTime(kept.recorded_at)} 録音・${formatDuration(kept.duration_sec)}・` +
            `${formatName(kept.mime_type)}・${formatBytes(kept.size_bytes)}`;
    const stateElement = $('kept_state');
    stateElement.replaceChildren();
    stateElement.className = 'kept__state';
    if (kept.state === 'sending') {
        stateElement.classList.add('kept__state--busy');
        stateElement.setAttribute('role', 'status');
        stateElement.append(spinnerElement(), `送信中 ${state.keptPercent}%`);
    }
    else if (kept.state === 'sent') {
        stateElement.classList.add('kept__state--ok');
        stateElement.removeAttribute('role');
        stateElement.append(iconElement('M5 12l5 5 9-10'), '送信済み');
    }
    else {
        stateElement.classList.add('kept__state--error');
        stateElement.removeAttribute('role');
        stateElement.append(iconElement('M12 8v5M12 16v.01', true), kept.state === 'send_failed' ? '送信失敗' : '文字起こし前');
    }
    const progress = $('kept_progress');
    progress.hidden = kept.state !== 'sending';
    progress.value = state.keptPercent;
    $('resend_button').hidden = !keptNeedsResend();
}
/** 回る印を作る。 */
function spinnerElement() {
    const spinner = document.createElement('span');
    spinner.className = 'spinner';
    spinner.setAttribute('aria-hidden', 'true');
    return spinner;
}
/** 線画の印（svg）を作る。circle を付けると丸で囲む。 */
function iconElement(path, circled = false) {
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    if (circled) {
        const circle = document.createElementNS(namespace, 'circle');
        circle.setAttribute('cx', '12');
        circle.setAttribute('cy', '12');
        circle.setAttribute('r', '9');
        svg.append(circle);
    }
    const line = document.createElementNS(namespace, 'path');
    line.setAttribute('d', path);
    svg.append(line);
    return svg;
}
/** 直前の送信か録音の開始の失敗を描く。 */
function renderError() {
    const error = state.sendError;
    byId('send-error').hidden = error === null;
    if (!error)
        return;
    byId('send-error-title').textContent = error.title;
    byId('send-error-body').textContent = error.body;
}
/** 結果の件数と、結果の一覧を描く。 */
function renderResults() {
    const count = state.results.length;
    $('results_meta').textContent =
        count === 0 ? '最大 10 件・保存 7 日' : `${count} 件・最大 10 件・保存 7 日`;
    byId('results-empty').hidden = count > 0;
    const list = byId('results');
    list.hidden = count === 0;
    list.replaceChildren(...state.results.map(resultElement));
}
/** 結果 1 件の要素を雛形から作る。 */
function resultElement(entry) {
    const template = byId('result-template');
    const item = present(template.content.firstElementChild, 'result-template').cloneNode(true);
    const field = (id) => present(item.querySelector(`[data-element="${id}"]`), id);
    field('result_time').textContent = formatDateTime(entry.sentAt);
    field('result_source').textContent =
        entry.durationSec === null ? entry.source : `${entry.source}・${formatDuration(entry.durationSec)}`;
    const status = field('result_status');
    const statusText = present(status.querySelector('.result__status-text'), 'status-text');
    const percent = present(status.querySelector('.result__pct'), 'pct');
    const spinner = present(status.querySelector('.spinner'), 'spinner');
    const icon = present(status.querySelector('.result__icon'), 'icon');
    const progress = field('result_progress');
    const text = field('result_text');
    const detail = field('result_detail');
    const actions = present(item.querySelector('.result__actions'), 'actions');
    if (entry.state === 'queued') {
        status.hidden = false;
        spinner.hidden = false;
        statusText.textContent = '文字起こし待ち';
    }
    else if (entry.state === 'running') {
        status.hidden = false;
        spinner.hidden = false;
        statusText.textContent = '文字起こし中';
        percent.hidden = false;
        percent.textContent = `${entry.progress}%`;
        progress.hidden = false;
        progress.value = entry.progress;
    }
    else if (entry.state === 'done') {
        text.hidden = false;
        text.textContent = entry.text === null || entry.text === '' ? '文字なし' : entry.text;
        actions.hidden = false;
        field('copy_button').addEventListener('click', (event) => {
            void copyResult(entry, event.currentTarget);
        });
        field('delete_button').addEventListener('click', () => {
            openDeleteDialog(entry);
        });
    }
    else {
        status.hidden = false;
        status.classList.add('result__status--error');
        icon.removeAttribute('hidden');
        detail.hidden = false;
        if (entry.state === 'failed') {
            statusText.textContent = '文字起こし失敗';
            detail.replaceChildren('PC の voice-paste で文字起こしが停止。端末内の音声から再送信可', document.createElement('br'), '詳細: ', codeElement(entry.error ?? ''));
        }
        else {
            statusText.textContent = '結果消失';
            detail.textContent = 'PC の voice-paste の再起動で結果が消失。端末内の音声から再送信可';
        }
    }
    return item;
}
/** 等幅の文字の要素を作る。 */
function codeElement(value) {
    const code = document.createElement('code');
    code.textContent = value;
    return code;
}
// ===== 操作 =====
/** 起こした文字をクリップボードへ入れ、押した直後の 2 秒だけ「コピー済み」にする。 */
async function copyResult(entry, button) {
    await navigator.clipboard.writeText(entry.text ?? '');
    const label = present(button.querySelector('span'), 'copy-label');
    button.dataset.copied = 'true';
    label.textContent = 'コピー済み';
    setTimeout(() => {
        button.dataset.copied = 'false';
        label.textContent = 'コピー';
    }, COPIED_MS);
}
/** 結果の削除の確認を開く。 */
function openDeleteDialog(entry) {
    state.pendingDelete = entry;
    byId('delete-quote').textContent = entry.text ?? '';
    byId('delete-dialog').showModal();
}
/** 確認のあとに、その結果を端末と一覧から消す。 */
function confirmDelete() {
    const target = state.pendingDelete;
    state.pendingDelete = null;
    byId('delete-dialog').close();
    state.results = state.results.filter((entry) => entry !== target);
    saveResults();
    render();
}
/** 文字起こし前の音声を置き換える確認を開く。 */
function openReplaceDialog() {
    const kept = present(state.kept, 'kept');
    byId('replace-body').textContent =
        `端末内の文字起こし前の音声（${formatDateTime(kept.recorded_at)}・${formatDuration(kept.duration_sec)}）` +
            'を削除して録音（復元不可）。保存する場合: キャンセル後にダウンロード';
    byId('replace-dialog').showModal();
}
/** 録音開始ボタン。文字にできていない音声があれば置換の確認へ、無ければ録音を始める。 */
function onRecordClick() {
    if (keptNeedsResend()) {
        openReplaceDialog();
        return;
    }
    void startRecording();
}
/** 端末内の音声を、録った日時の名前で端末へ保存する。 */
function downloadKept() {
    const kept = present(state.kept, 'kept');
    const url = URL.createObjectURL(kept.blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = downloadName(kept);
    anchor.click();
    URL.revokeObjectURL(url);
}
/** 端末内の音声をもう一度送る。失敗した前の件は一覧から外す。 */
async function resendKept() {
    const kept = present(state.kept, 'kept');
    state.sendError = null;
    state.results = state.results.filter((entry) => entry.jobId !== kept.job_id);
    saveResults();
    kept.state = 'sending';
    kept.job_id = null;
    await saveKept(kept);
    await sendKept();
}
// ===== 起動 =====
/** 操作を受け付けてから、期限を過ぎた音声と結果を消して読み込み、描く。 */
async function init() {
    $('record_button').addEventListener('click', onRecordClick);
    $('stop_button').addEventListener('click', stopRecording);
    $('file_input').addEventListener('change', (event) => {
        const input = event.currentTarget;
        const file = input.files?.[0];
        input.value = '';
        if (file)
            void sendFile(file);
    });
    $('download_button').addEventListener('click', downloadKept);
    $('resend_button').addEventListener('click', () => void resendKept());
    $('delete_cancel').addEventListener('click', () => byId('delete-dialog').close());
    $('delete_confirm').addEventListener('click', confirmDelete);
    $('replace_cancel').addEventListener('click', () => byId('replace-dialog').close());
    $('replace_confirm').addEventListener('click', () => {
        byId('replace-dialog').close();
        void startRecording();
    });
    const kept = await loadKept();
    if (kept && isExpired(kept.recorded_at)) {
        await deleteKept();
    }
    else if (kept) {
        // 送信の途中で画面を閉じた音声は、送れていないものとして扱う
        if (kept.state === 'sending') {
            kept.state = 'send_failed';
            await saveKept(kept);
        }
        state.kept = kept;
    }
    state.results = loadStoredResults()
        .filter((stored) => !isExpired(stored.sent_at))
        .map((stored) => ({
        jobId: stored.job_id,
        state: stored.state,
        source: stored.source,
        durationSec: stored.duration_sec,
        sentAt: stored.sent_at,
        text: stored.text,
        progress: 0,
        error: null,
    }));
    saveResults();
    render();
    ensurePolling();
}
void init();
