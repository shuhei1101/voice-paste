// 外の端末のブラウザで開く文字起こしの画面。
// 録音（MediaRecorder）かファイルを PC の常駐アプリへ送信し、結果を取りに行って端末に残す。
// 端末に残すのは、画面で録った直近 1 件の音声（IndexedDB）と、結果の一覧（localStorage）。

// ===== 定数 =====

/** 本文の上限（バイト。これ以上は送信しない）。常駐アプリの BodyLimitMiddleware と同じ値。 */
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
/** 音声と結果を送信する・取りに行く API の相対パス（画面は /web/ で開く）。 */
const API_PATH = 'transcriptions';
/** 用語集のプリセットの一覧を取りに行く API の相対パス（画面は /web/ で開く）。 */
const PRESETS_PATH = 'glossary-presets';
/** 選んだ用語集のプリセットの名前を残す localStorage のキー。 */
const PRESET_STORAGE_KEY = 'voice-paste.glossary_preset';
/** 「録音中は画面を暗くしない」の選択を残す localStorage のキー（ER図『ブラウザの端末のデータ』）。値はオンが `1`、オフが `0`。 */
const KEEP_SCREEN_STORAGE_KEY = 'voice-paste.keep_screen_on';
/** 「録音中は画面を暗くしない」のオフを残す値（キーが無い・ほかの値はオンとして扱う）。 */
const KEEP_SCREEN_OFF = '0';
/** 「録音中は画面を暗くしない」のオンを残す値。 */
const KEEP_SCREEN_ON = '1';
/** 選択欄の「設定に従う」の値。常駐アプリでは指定なしとして扱う。 */
const FOLLOW_SETTINGS = '';
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
/** 送信できていない・文字にできていない端末内の音声の状態の表示文言。 */
const KEPT_ERROR_LABELS = {
  send_failed: '送信失敗',
  preset_not_found: '未送信',
  not_transcribed: '文字起こし前',
} as const;

// ===== 型 =====

/** 端末内の音声の送信と文字起こしの状態（ER図『ブラウザの端末のデータ』の `state`）。 */
type KeptState = 'sending' | 'sent' | 'send_failed' | 'preset_not_found' | 'not_transcribed';

/** IndexedDB に残す、画面で録った直近 1 件の音声（ER図『ブラウザの端末のデータ』）。 */
interface KeptAudio {
  blob: Blob;
  mime_type: string;
  recorded_at: string;
  duration_sec: number;
  size_bytes: number;
  state: KeptState;
  job_id: string | null;
}

/** API が返すジョブの状態（`WebTranscriptionStatus` の `state`）。 */
type JobState = 'queued' | 'running' | 'done' | 'failed';

/** 結果の 1 件の状態。API の状態に、取りに行けなかった `not_found`（404）を追加する。 */
type ResultState = JobState | 'not_found';

/** `GET /web/transcriptions/{job_id}` の 200 の本文（`WebTranscriptionStatus`）。 */
interface JobStatus {
  job_id: string;
  state: JobState;
  progress: number;
  reports_progress: boolean;
  text: string | null;
  error: string | null;
}

/** `POST /web/transcriptions` の 202 の本文。 */
interface CreatedJob {
  job_id: string;
}

/** `GET /web/glossary-presets` の 200 の本文。 */
interface GlossaryPresets {
  presets: string[];
  active: string;
}

/** localStorage に残す結果 1 件（ER図『ブラウザの端末のデータ』）。 */
interface StoredResult {
  job_id: string;
  state: 'queued' | 'running' | 'done';
  source: string;
  duration_sec: number | null;
  sent_at: string;
  text: string | null;
}

/** 画面が持つ結果 1 件。失敗・結果消失の件は画面を開いている間だけ持つ。 */
interface ResultEntry {
  jobId: string;
  state: ResultState;
  source: string;
  durationSec: number | null;
  sentAt: string;
  text: string | null;
  progress: number;
  /** 設定のエンジンが途中の進みを返すか。取りに行くまでは false（進みを出さない）。 */
  reportsProgress: boolean;
  error: string | null;
}

/** 録音中の情報。 */
interface Recording {
  recorder: MediaRecorder;
  startedAt: number;
  elapsedSec: number;
  timer: number | null;
}

/** 選んだファイルの送信中の情報。 */
interface FileSending {
  name: string;
  size: number;
  percent: number;
  /** 送信した時点の選択欄の表示文言。 */
  presetLabel: string;
}

/** 選んだ用語集のプリセットが一覧に無く、送信が断られたこと。 */
interface PresetNotFound {
  /** 断られたプリセットの名前。 */
  name: string;
  /** 断られた選んだファイルの名前（画面で録った音声は null）。 */
  fileName: string | null;
}

/** 送信に付ける、選択欄の用語集のプリセット。 */
interface PresetChoice {
  /** 送信する値（「設定に従う」は空文字）。 */
  value: string;
  /** 選択欄の表示文言。 */
  label: string;
}

/** 画面に出すエラーの見出しと本文。 */
interface SendError {
  title: string;
  body: string;
}

/** 音声を送信した結果（届かなければ status は 0）。 */
interface UploadResult {
  status: number;
  body: CreatedJob | null;
}

/** 音声を送信するときの引数。 */
interface UploadParams {
  blob: Blob;
  filename: string;
  /** 補正に使う用語集のプリセットの名前（「設定に従う」は空文字）。 */
  glossaryPreset: string;
  onProgress: (percent: number) => void;
}

/** 画面の状態。 */
interface AppState {
  /** 録音中の情報（録音中でなければ null）。 */
  recording: Recording | null;
  /** 端末（IndexedDB）に残した音声（無ければ null）。 */
  kept: KeptAudio | null;
  /** 端末内の音声の送信の進み具合（0〜100）。 */
  keptPercent: number;
  /** 端末内の音声を送信した時点の選択欄の表示文言。 */
  keptPresetLabel: string;
  /** 用語集のプリセットの一覧（取得できていなければ null）。 */
  presets: GlossaryPresets | null;
  /** 画面を開いたときの一覧の取得が失敗したか。 */
  presetFetchFailed: boolean;
  /** 選んでいる用語集のプリセットの名前（「設定に従う」は空文字）。 */
  selectedPreset: string;
  /** 直前の送信が一覧に無いプリセットで断られたこと（無ければ null）。 */
  presetNotFound: PresetNotFound | null;
  /** 選んだファイルの送信中の情報（送信中でなければ null）。 */
  fileSending: FileSending | null;
  /** 直前の送信か録音の開始の失敗（無ければ null）。 */
  sendError: SendError | null;
  /** 上限で録音が止まってから、その送信が終わるまで真。 */
  limitNotice: boolean;
  /** 「録音中は画面を暗くしない」がオンか。 */
  keepScreenOn: boolean;
  /** 録音の間に取得している Screen Wake Lock（取得していなければ null）。 */
  wakeLock: WakeLockSentinel | null;
  /** 結果の一覧（新しい件が先頭）。 */
  results: ResultEntry[];
  /** 削除の確認を開いている件。 */
  pendingDelete: ResultEntry | null;
}

// ===== 状態 =====

const state: AppState = {
  recording: null,
  kept: null,
  keptPercent: 0,
  keptPresetLabel: '',
  presets: null,
  presetFetchFailed: false,
  selectedPreset: FOLLOW_SETTINGS,
  presetNotFound: null,
  fileSending: null,
  sendError: null,
  limitNotice: false,
  keepScreenOn: true,
  wakeLock: null,
  results: [],
  pendingDelete: null,
};

let pollTimer: number | null = null;

// ===== 要素 =====

/** 値があることを確かめる。無ければ画面の組み立ての誤りなので例外にする。 */
function present<T>(value: T | null | undefined, name: string): T {
  if (value === null || value === undefined) throw new Error(`画面に必要なものがありません: ${name}`);
  return value;
}
/** data-element の項目 ID で要素を引く。 */
const $ = <T extends HTMLElement = HTMLElement>(id: string): T =>
  present(document.querySelector<T>(`[data-element="${id}"]`), id);
/** id 属性で要素を引く。 */
const byId = <T extends HTMLElement = HTMLElement>(id: string): T =>
  present(document.getElementById(id) as T | null, id);

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
function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}

/** 秒数を `m:ss` にする。 */
function formatDuration(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

/** 秒数を `mm:ss` にする。 */
function formatClock(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec));
  return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
}

/** バイト数を `540 KB`・`7.2 MB` の形式にする（1 MB = 1,000,000 バイト）。 */
function formatBytes(bytes: number): string {
  if (bytes < 1_000_000) {
    return `${numberFormat.format(Math.round(bytes / 1000))} KB`;
  }
  return `${numberFormat.format(bytes / 1_000_000)} MB`;
}

/** MediaRecorder の形式から、形式の名前と拡張子（webm・mp4・ogg）を返す。 */
function formatName(mimeType: string): string {
  if (mimeType.includes('webm')) return 'webm';
  if (mimeType.includes('mp4')) return 'mp4';
  if (mimeType.includes('ogg')) return 'ogg';
  return 'webm';
}

/** ダウンロードのファイル名 `voice-paste_YYYYMMDD-HHmmss.{拡張子}` を作る。 */
function downloadName(kept: KeptAudio): string {
  const parts: Record<string, string> = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
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
      .map((part) => [part.type, part.value]),
  );
  const stamp = `${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}${parts.second}`;
  return `voice-paste_${stamp}.${formatName(kept.mime_type)}`;
}

// ===== 端末への保存 =====

/** IndexedDB を開く。 */
function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(DB_STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB を開けません'));
  });
}

/** 端末内の音声のストアに対する 1 回の操作を実行して、その結果を返す。 */
async function withStore<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction(DB_STORE, mode);
      const request = operation(transaction.objectStore(DB_STORE));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB の操作に失敗しました'));
    });
  } finally {
    db.close();
  }
}

/** 端末内の音声を読む。無ければ undefined を返す。 */
const loadKept = (): Promise<KeptAudio | undefined> =>
  withStore<KeptAudio | undefined>(
    'readonly',
    (store) => store.get(DB_KEY) as IDBRequest<KeptAudio | undefined>,
  );
/** 端末内の音声を置き換えて残す。 */
const saveKept = (kept: KeptAudio): Promise<IDBValidKey> =>
  withStore('readwrite', (store) => store.put(kept, DB_KEY));
/** 端末内の音声を削除する。 */
const deleteKept = (): Promise<undefined> =>
  withStore('readwrite', (store) => store.delete(DB_KEY));

/** localStorage の結果の一覧を読む。読めなければ空にする。 */
function loadStoredResults(): StoredResult[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(RESULTS_STORAGE_KEY) ?? '[]');
    return Array.isArray(stored) ? (stored as StoredResult[]) : [];
  } catch {
    return [];
  }
}

/** 終わっていない件と届いた件だけを localStorage に残す（失敗・結果消失の件は画面を開いている間だけ出す）。 */
function saveResults(): void {
  const persisted: StoredResult[] = state.results
    .filter(
      (entry): entry is ResultEntry & { state: StoredResult['state'] } =>
        entry.state === 'queued' || entry.state === 'running' || entry.state === 'done',
    )
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
function isExpired(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() > RETENTION_MS;
}

// ===== 用語集のプリセット =====

/** 端末に覚えた用語集のプリセットの名前を読む。無ければ「設定に従う」にする。 */
function loadStoredPreset(): string {
  return localStorage.getItem(PRESET_STORAGE_KEY) ?? FOLLOW_SETTINGS;
}

/** 選んだ用語集のプリセットの名前を端末に覚える。 */
function saveStoredPreset(name: string): void {
  localStorage.setItem(PRESET_STORAGE_KEY, name);
}

/** 用語集のプリセットの一覧を取りに行く。取得できなければ null を返す。 */
async function fetchPresets(): Promise<GlossaryPresets | null> {
  try {
    const response = await fetch(PRESETS_PATH);
    if (!response.ok) return null;
    return (await response.json()) as GlossaryPresets;
  } catch {
    return null;
  }
}

/**
 * 取りに行った一覧を取り込み、選択が一覧に無ければ「設定に従う」へ戻す。
 * 取得できなかったときは、端末に覚えた名前は残して画面の選択だけを「設定に従う」にする。
 */
function applyPresets(presets: GlossaryPresets | null): void {
  state.presets = presets;
  state.presetFetchFailed = presets === null;
  if (presets === null) {
    state.selectedPreset = FOLLOW_SETTINGS;
    return;
  }
  if (state.selectedPreset !== FOLLOW_SETTINGS && !presets.presets.includes(state.selectedPreset)) {
    state.selectedPreset = FOLLOW_SETTINGS;
    saveStoredPreset(FOLLOW_SETTINGS);
  }
}

/** 選択欄の表示文言。「設定に従う」には設定で選んでいるプリセットの名前を添える。 */
function presetLabel(name: string): string {
  if (name !== FOLLOW_SETTINGS) return name;
  return state.presets === null ? '設定に従う' : `設定に従う（${state.presets.active}）`;
}

/** 今の選択を、送信に付ける値と表示文言にして返す。 */
function currentPreset(): PresetChoice {
  return { value: state.selectedPreset, label: presetLabel(state.selectedPreset) };
}

/** 一覧に無いプリセットで送信が断られたか（「設定に従う」は指定なしなので断られない）。 */
function isPresetNotFound(status: number, preset: PresetChoice): boolean {
  return status === 400 && preset.value !== FOLLOW_SETTINGS;
}

/** 一覧に無いプリセットで断られたとき、選択を「設定に従う」へ戻して一覧を取り直し、エラーを出す。 */
async function handlePresetNotFound(notFound: PresetNotFound): Promise<void> {
  state.selectedPreset = FOLLOW_SETTINGS;
  saveStoredPreset(FOLLOW_SETTINGS);
  applyPresets(await fetchPresets());
  state.presetNotFound = notFound;
  renderPresetOptions();
}

/** 一覧に無いプリセットのエラーの本文を作る。 */
function presetNotFoundBody(notFound: PresetNotFound): string {
  const deleted = `「${notFound.name}」は PC の設定から削除済みのため、`;
  const reset = '一覧を再取得し、「設定に従う」に戻しました。プリセットを確認して、';
  if (notFound.fileName === null) {
    return `${deleted}録った音声は未送信です。${reset}再送信してください。`;
  }
  return `${deleted}${notFound.fileName} は未送信です。${reset}ファイルをもう一度選択してください。`;
}

// ===== 送信 =====

/** 音声を multipart の audio と glossary_preset で送信し、ステータスと本文を返す。届かなければ status を 0 にする。 */
function upload(params: UploadParams): Promise<UploadResult> {
  const { blob, filename, glossaryPreset, onProgress } = params;
  return new Promise((resolve) => {
    const request = new XMLHttpRequest();
    request.open('POST', API_PATH);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      resolve({ status: request.status, body: parseCreatedJob(request.responseText) });
    };
    request.onerror = () => resolve({ status: 0, body: null });
    request.onabort = () => resolve({ status: 0, body: null });
    const form = new FormData();
    form.append('audio', blob, filename);
    form.append('glossary_preset', glossaryPreset);
    request.send(form);
  });
}

/** 202 の本文を読む。JSON でなければ null を返す。 */
function parseCreatedJob(text: string): CreatedJob | null {
  try {
    return JSON.parse(text) as CreatedJob;
  } catch {
    return null;
  }
}

/** 送信の失敗のステータスから、画面に出すエラーの見出しと本文を作る。 */
function errorForStatus(
  status: number,
  name: string,
  size: number,
  isFile: boolean,
): SendError {
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

/** 結果の一覧の先頭に、受け付けられた件を待ちで追加する。10 件を超えたら古い件を削除する。 */
function addResult(added: { jobId: string; source: string; durationSec: number | null }): void {
  const { jobId, source, durationSec } = added;
  state.results.unshift({
    jobId,
    state: 'queued',
    source,
    durationSec,
    sentAt: new Date().toISOString(),
    text: null,
    progress: 0,
    reportsProgress: false,
    error: null,
  });
  state.results.length = Math.min(state.results.length, MAX_RESULTS);
  saveResults();
  ensurePolling();
}

/**
 * 端末内の音声を、送信した時点の用語集のプリセットの選択で送信する。
 * 成功で結果の一覧に待ちの件を追加し、一覧に無いプリセットで断られたら未送信、そのほかの失敗は送信失敗にする。
 */
async function sendKept(): Promise<void> {
  const kept = present(state.kept, 'kept');
  const preset = currentPreset();
  state.keptPercent = 0;
  state.keptPresetLabel = preset.label;
  state.presetNotFound = null;
  render();
  const { status, body } = await upload({
    blob: kept.blob,
    filename: `recording.${formatName(kept.mime_type)}`,
    glossaryPreset: preset.value,
    onProgress: (percent) => {
      state.keptPercent = percent;
      renderKept();
    },
  });
  state.limitNotice = false;
  if (status === 202 && body?.job_id) {
    kept.state = 'sent';
    kept.job_id = body.job_id;
    state.sendError = null;
    addResult({ jobId: body.job_id, source: RECORDED_SOURCE, durationSec: kept.duration_sec });
  } else if (isPresetNotFound(status, preset)) {
    kept.state = 'preset_not_found';
    state.sendError = null;
    await handlePresetNotFound({ name: preset.value, fileName: null });
  } else {
    kept.state = 'send_failed';
    state.sendError = errorForStatus(status, RECORDED_SOURCE, kept.size_bytes, false);
  }
  await saveKept(kept);
  render();
}

/** 選んだファイルを確かめずに、送信した時点の用語集のプリセットの選択ですぐ送信する。端末内の音声は置き換えない。 */
async function sendFile(file: File): Promise<void> {
  state.sendError = null;
  state.presetNotFound = null;
  // 本文の上限以上は送信せずに断る
  if (file.size >= BODY_LIMIT_BYTES) {
    state.sendError = errorForStatus(413, file.name, file.size, true);
    render();
    return;
  }
  const preset = currentPreset();
  state.fileSending = { name: file.name, size: file.size, percent: 0, presetLabel: preset.label };
  render();
  const { status, body } = await upload({
    blob: file,
    filename: file.name,
    glossaryPreset: preset.value,
    onProgress: (percent) => {
      if (state.fileSending) state.fileSending.percent = percent;
      renderFileSending();
    },
  });
  state.fileSending = null;
  if (status === 202 && body?.job_id) {
    addResult({ jobId: body.job_id, source: file.name, durationSec: null });
  } else if (isPresetNotFound(status, preset)) {
    await handlePresetNotFound({ name: preset.value, fileName: file.name });
  } else {
    state.sendError = errorForStatus(status, file.name, file.size, true);
  }
  render();
}

// ===== 録音 =====

/** マイクを開いて録音を始める。開けなければエラーを出す。 */
async function startRecording(): Promise<void> {
  state.sendError = null;
  state.presetNotFound = null;
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    state.sendError = { title: 'マイク使用不可', body: 'ブラウザのマイクの許可を確認' };
    render();
    return;
  }

  const mimeType = MIME_CANDIDATES.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  const options: MediaRecorderOptions = { audioBitsPerSecond: AUDIO_BITS_PER_SECOND };
  if (mimeType) options.mimeType = mimeType;
  const recorder = new MediaRecorder(stream, options);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop());
    void finishRecording(recorder, chunks);
  };

  const recording: Recording = { recorder, startedAt: Date.now(), elapsedSec: 0, timer: null };
  recording.timer = window.setInterval(tickRecording, 1000);
  state.recording = recording;
  recorder.start();
  render();
  void acquireWakeLock();
}

/** 1 秒ごとに経過時間を進め、上限に達したら録音を止めて送信する。 */
function tickRecording(): void {
  const recording = state.recording;
  if (!recording) return;
  recording.elapsedSec = Math.floor((Date.now() - recording.startedAt) / 1000);
  if (recording.elapsedSec >= RECORDING_LIMIT_SEC) {
    recording.elapsedSec = RECORDING_LIMIT_SEC;
    state.limitNotice = true;
    stopRecording();
    return;
  }
  renderRecording();
}

/** 録音を止める。止まった音声は finishRecording が端末に残して送信する。 */
function stopRecording(): void {
  const recording = state.recording;
  if (!recording || recording.recorder.state === 'inactive') return;
  recording.recorder.stop();
}

/** 止まった録音を端末（IndexedDB）に残して送信する。前の 1 件は置き換わる。 */
async function finishRecording(recorder: MediaRecorder, chunks: Blob[]): Promise<void> {
  const recording = present(state.recording, 'recording');
  releaseWakeLock();
  if (recording.timer !== null) clearInterval(recording.timer);
  const blob = new Blob(chunks, { type: recorder.mimeType });
  state.recording = null;
  const kept: KeptAudio = {
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

// ===== 画面の消灯の抑止 =====

/** ブラウザが Screen Wake Lock に対応しているか。 */
function isWakeLockSupported(): boolean {
  return 'wakeLock' in navigator;
}

/** 端末に残した「録音中は画面を暗くしない」の選択を読む。キーが無ければオン、対応しないブラウザではオフ。 */
function loadStoredKeepScreen(): boolean {
  if (!isWakeLockSupported()) return false;
  return localStorage.getItem(KEEP_SCREEN_STORAGE_KEY) !== KEEP_SCREEN_OFF;
}

/** 「録音中は画面を暗くしない」の選択を端末に残す。 */
function saveStoredKeepScreen(on: boolean): void {
  localStorage.setItem(KEEP_SCREEN_STORAGE_KEY, on ? KEEP_SCREEN_ON : KEEP_SCREEN_OFF);
}

/**
 * オンで録音中・画面が見えていれば Screen Wake Lock を取得する（取得済みなら何もしない）。
 * 取得できなければ（拒否）抑止せずに録音を続け、コンソールに警告を出す。
 */
async function acquireWakeLock(): Promise<void> {
  if (!state.keepScreenOn || !isWakeLockSupported()) return;
  if (state.recording === null || document.visibilityState !== 'visible') return;
  if (state.wakeLock !== null && !state.wakeLock.released) return;
  let sentinel: WakeLockSentinel;
  try {
    sentinel = await navigator.wakeLock.request('screen');
  } catch (error) {
    console.warn('画面の消灯を抑止できなかった', error);
    return;
  }
  // 取得を待つ間に録音が終わっていれば、すぐ解放する
  if (state.recording === null) {
    void sentinel.release();
    return;
  }
  state.wakeLock = sentinel;
}

/** 取得している Screen Wake Lock を解放する（取得していなければ何もしない）。 */
function releaseWakeLock(): void {
  const sentinel = state.wakeLock;
  state.wakeLock = null;
  if (sentinel === null || sentinel.released) return;
  sentinel.release().catch((error: unknown) => {
    console.warn('画面の消灯の抑止を解除できなかった', error);
  });
}

// ===== 結果の取得 =====

/** 終わっていない件があれば、取りに行く間隔の後に結果を取りに行く。 */
function ensurePolling(): void {
  if (pollTimer !== null) return;
  if (!state.results.some(isPending)) return;
  pollTimer = window.setTimeout(() => void pollResults(), POLL_INTERVAL_MS);
}

/** 終わっていない件か。 */
function isPending(entry: ResultEntry): boolean {
  return entry.state === 'queued' || entry.state === 'running';
}

/** 終わっていない件の結果を取りに行く。届かない・5xx の件は次の間隔で取りに行く。 */
async function pollResults(): Promise<void> {
  pollTimer = null;
  for (const entry of state.results.filter(isPending)) {
    await fetchResult(entry);
  }
  saveResults();
  render();
  ensurePolling();
}

/** 1 件の結果を取りに行き、状態を反映する。 */
async function fetchResult(entry: ResultEntry): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_PATH}/${encodeURIComponent(entry.jobId)}`);
  } catch {
    return;
  }
  if (response.status === 404) {
    entry.state = 'not_found';
    await markNotTranscribed(entry.jobId);
    return;
  }
  if (!response.ok) return;
  const job = (await response.json()) as JobStatus;
  entry.state = job.state;
  entry.progress = Math.round(job.progress * 100);
  entry.reportsProgress = job.reports_progress;
  if (job.state === 'done') {
    entry.text = job.text;
  } else if (job.state === 'failed') {
    entry.error = job.error;
    await markNotTranscribed(entry.jobId);
  }
}

/** そのジョブの音声が端末内に残っていれば、文字起こし前にする。 */
async function markNotTranscribed(jobId: string): Promise<void> {
  if (state.kept === null || state.kept.job_id !== jobId) return;
  state.kept.state = 'not_transcribed';
  await saveKept(state.kept);
}

// ===== 描画 =====

/** 画面全体を状態に合わせて描き直す。 */
function render(): void {
  renderSend();
  renderPreset();
  renderKeepScreen();
  renderRecording();
  renderFileSending();
  renderKept();
  renderError();
  renderResults();
}

/** 端末内の音声が、送信できていない・文字にできていない状態か。 */
function keptNeedsResend(): boolean {
  return (
    state.kept !== null &&
    ['send_failed', 'preset_not_found', 'not_transcribed'].includes(state.kept.state)
  );
}

/** 送信中（選んだファイル・端末内の音声）か。 */
function isSending(): boolean {
  return state.fileSending !== null || state.kept?.state === 'sending';
}

/** 録る・ファイルを選ぶのボタンと、録音中の表示の出し分けを描く。 */
function renderSend(): void {
  const recording = state.recording !== null;
  const sending = isSending();
  $('send_actions').hidden = recording;
  byId('send-hint').hidden = recording;
  byId('recorder').hidden = !recording;
  byId('limit-notice').hidden = !state.limitNotice;

  const recordButton = $<HTMLButtonElement>('record_button');
  recordButton.disabled = sending;
  recordButton.classList.toggle('btn--primary', !keptNeedsResend());
  const fileInput = $<HTMLInputElement>('file_input');
  fileInput.disabled = sending;
  byId('file-label').setAttribute('aria-disabled', String(sending));
}

/** 「録音中は画面を暗くしない」のチェックの値・押せるか・対応しないことの補足を描く。 */
function renderKeepScreen(): void {
  const check = $<HTMLInputElement>('keep_screen_check');
  const supported = isWakeLockSupported();
  check.checked = state.keepScreenOn;
  check.disabled = state.recording !== null || !supported;
  $('keep_screen_unsupported').hidden = supported;
  if (supported) {
    check.removeAttribute('aria-describedby');
  } else {
    check.setAttribute('aria-describedby', 'keep-screen-unsupported');
  }
}

/** 選択欄の選択肢を、取得した一覧に合わせて並べ直す。先頭は「設定に従う」。 */
function renderPresetOptions(): void {
  const names = state.presets?.presets ?? [];
  $<HTMLSelectElement>('preset_select').replaceChildren(
    ...[FOLLOW_SETTINGS, ...names].map((name) => new Option(presetLabel(name), name)),
  );
  renderPreset();
}

/**
 * 選択欄の選択・押せるか・補足と知らせを描く。
 * 選択肢は並べ直さない（開いている途中の選択欄を、結果の取得の描き直しで閉じないため）。
 */
function renderPreset(): void {
  const select = $<HTMLSelectElement>('preset_select');
  const recording = state.recording !== null;
  select.value = state.selectedPreset;
  select.disabled = recording;
  byId('preset-help').hidden = !recording;
  byId('preset-fetch-notice').hidden = !state.presetFetchFailed;
  const notFound = state.presetNotFound;
  byId('preset-not-found-error').hidden = notFound === null;
  if (notFound) byId('preset-not-found-body').textContent = presetNotFoundBody(notFound);

  // 押せない理由・取得失敗の知らせ・エラーを、選択欄の読み上げにも伝える
  const describedBy = [
    recording ? 'preset-help' : null,
    state.presetFetchFailed ? 'preset-fetch-notice' : null,
    notFound ? 'preset-not-found-error' : null,
  ].filter((id) => id !== null);
  if (describedBy.length === 0) {
    select.removeAttribute('aria-describedby');
  } else {
    select.setAttribute('aria-describedby', describedBy.join(' '));
  }
}

/** 録音中の経過時間・上限までのバー・残り時間を描く。 */
function renderRecording(): void {
  const recording = state.recording;
  if (!recording) return;
  const elapsed = recording.elapsedSec;
  const remaining = RECORDING_LIMIT_SEC - elapsed;
  const elapsedElement = $('recording_elapsed');
  elapsedElement.textContent = formatClock(elapsed);
  elapsedElement.setAttribute(
    'aria-label',
    `経過時間 ${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒`,
  );
  $<HTMLProgressElement>('recording_progress').value = elapsed;
  const remainingElement = $('recording_remaining');
  const low = remaining < LOW_REMAINING_SEC;
  remainingElement.classList.toggle('recorder__left--low', low);
  remainingElement.textContent = `残り ${formatDuration(remaining)}${low ? '（上限で自動送信）' : ''}`;
}

/** 選んだファイルの送信中の行を描く。 */
function renderFileSending(): void {
  const sending = state.fileSending;
  byId('file-sending').hidden = sending === null;
  if (!sending) return;
  $('file_sending_name').textContent = `${sending.name}・${formatBytes(sending.size)}`;
  $('file_sending_preset').textContent = `プリセット「${sending.presetLabel}」`;
  byId('file-sending-text').textContent = `送信中 ${sending.percent}%`;
  $<HTMLProgressElement>('file_sending_progress').value = sending.percent;
}

/** 端末内の音声の行（日時・長さ・形式・大きさ、状態、操作）を描く。 */
function renderKept(): void {
  const kept = state.kept;
  byId('kept').hidden = kept === null;
  if (!kept) return;
  // 送信中は、送信した時点の用語集のプリセットを添えて、次に送信する音声の選択と分ける
  const sendingPreset = kept.state === 'sending' ? `・プリセット「${state.keptPresetLabel}」` : '';
  $('kept_meta').textContent =
    `${formatDateTime(kept.recorded_at)} 録音・${formatDuration(kept.duration_sec)}・` +
    `${formatName(kept.mime_type)}・${formatBytes(kept.size_bytes)}${sendingPreset}`;

  const stateElement = $('kept_state');
  stateElement.replaceChildren();
  stateElement.className = 'kept__state';
  if (kept.state === 'sending') {
    stateElement.classList.add('kept__state--busy');
    stateElement.setAttribute('role', 'status');
    stateElement.append(spinnerElement(), `送信中 ${state.keptPercent}%`);
  } else if (kept.state === 'sent') {
    stateElement.classList.add('kept__state--ok');
    stateElement.removeAttribute('role');
    stateElement.append(iconElement('M5 12l5 5 9-10'), '送信済み');
  } else {
    stateElement.classList.add('kept__state--error');
    stateElement.removeAttribute('role');
    stateElement.append(iconElement('M12 8v5M12 16v.01', true), KEPT_ERROR_LABELS[kept.state]);
  }

  const progress = $<HTMLProgressElement>('kept_progress');
  progress.hidden = kept.state !== 'sending';
  progress.value = state.keptPercent;
  $<HTMLButtonElement>('resend_button').hidden = !keptNeedsResend();
}

/** 回るマーカーを作る。 */
function spinnerElement(): HTMLSpanElement {
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.setAttribute('aria-hidden', 'true');
  return spinner;
}

/** 線画のマーカー（svg）を作る。circle を付けると丸で囲む。 */
function iconElement(path: string, circled = false): SVGSVGElement {
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
function renderError(): void {
  const error = state.sendError;
  byId('send-error').hidden = error === null;
  if (!error) return;
  byId('send-error-title').textContent = error.title;
  byId('send-error-body').textContent = error.body;
}

/** 結果の件数と、結果の一覧を描く。 */
function renderResults(): void {
  const count = state.results.length;
  $('results_meta').textContent =
    count === 0 ? '最大 10 件・保存 7 日' : `${count} 件・最大 10 件・保存 7 日`;
  byId('results-empty').hidden = count > 0;
  const list = byId('results');
  list.hidden = count === 0;
  list.replaceChildren(...state.results.map(resultElement));
}

/** 結果 1 件の要素を雛形から作る。 */
function resultElement(entry: ResultEntry): HTMLElement {
  const template = byId<HTMLTemplateElement>('result-template');
  const item = present(template.content.firstElementChild, 'result-template').cloneNode(
    true,
  ) as HTMLElement;
  const field = <T extends HTMLElement = HTMLElement>(id: string): T =>
    present(item.querySelector<T>(`[data-element="${id}"]`), id);
  field('result_time').textContent = formatDateTime(entry.sentAt);
  field('result_source').textContent =
    entry.durationSec === null ? entry.source : `${entry.source}・${formatDuration(entry.durationSec)}`;

  const status = field('result_status');
  const statusText = present(status.querySelector<HTMLElement>('.result__status-text'), 'status-text');
  const percent = present(status.querySelector<HTMLElement>('.result__pct'), 'pct');
  const spinner = present(status.querySelector<HTMLElement>('.spinner'), 'spinner');
  const icon = present(status.querySelector<SVGElement>('.result__icon'), 'icon');
  const progress = field<HTMLProgressElement>('result_progress');
  const text = field('result_text');
  const detail = field('result_detail');
  const actions = present(item.querySelector<HTMLElement>('.result__actions'), 'actions');

  if (entry.state === 'queued') {
    status.hidden = false;
    spinner.hidden = false;
    statusText.textContent = '文字起こし待ち';
  } else if (entry.state === 'running') {
    status.hidden = false;
    spinner.hidden = false;
    statusText.textContent = '文字起こし中';
    // 進みを返すエンジンか: 返さないエンジンは % と進みのバーを出さず「文字起こし中」だけにする
    if (entry.reportsProgress) {
      percent.hidden = false;
      percent.textContent = `${entry.progress}%`;
      progress.hidden = false;
      progress.value = entry.progress;
    }
  } else if (entry.state === 'done') {
    text.hidden = false;
    text.textContent = entry.text === null || entry.text === '' ? '文字なし' : entry.text;
    actions.hidden = false;
    field<HTMLButtonElement>('copy_button').addEventListener('click', (event) => {
      void copyResult(entry, event.currentTarget as HTMLButtonElement);
    });
    field<HTMLButtonElement>('delete_button').addEventListener('click', () => {
      openDeleteDialog(entry);
    });
  } else {
    status.hidden = false;
    status.classList.add('result__status--error');
    icon.removeAttribute('hidden');
    detail.hidden = false;
    if (entry.state === 'failed') {
      statusText.textContent = '文字起こし失敗';
      detail.replaceChildren(
        'PC の voice-paste で文字起こしが停止。端末内の音声から再送信可',
        document.createElement('br'),
        '詳細: ',
        codeElement(entry.error ?? ''),
      );
    } else {
      statusText.textContent = '結果消失';
      detail.textContent = 'PC の voice-paste の再起動で結果が消失。端末内の音声から再送信可';
    }
  }
  return item;
}

/** 等幅の文字の要素を作る。 */
function codeElement(value: string): HTMLElement {
  const code = document.createElement('code');
  code.textContent = value;
  return code;
}

// ===== 操作 =====

/** 起こした文字をクリップボードへ入れ、押した直後の 2 秒だけ「コピー済み」にする。 */
async function copyResult(entry: ResultEntry, button: HTMLButtonElement): Promise<void> {
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
function openDeleteDialog(entry: ResultEntry): void {
  state.pendingDelete = entry;
  byId('delete-quote').textContent = entry.text ?? '';
  byId<HTMLDialogElement>('delete-dialog').showModal();
}

/** 確認のあとに、その結果を端末と一覧から削除する。 */
function confirmDelete(): void {
  const target = state.pendingDelete;
  state.pendingDelete = null;
  byId<HTMLDialogElement>('delete-dialog').close();
  state.results = state.results.filter((entry) => entry !== target);
  saveResults();
  render();
}

/** 文字起こし前の音声を置き換える確認を開く。 */
function openReplaceDialog(): void {
  const kept = present(state.kept, 'kept');
  byId('replace-body').textContent =
    `端末内の文字起こし前の音声（${formatDateTime(kept.recorded_at)}・${formatDuration(kept.duration_sec)}）` +
    'を削除して録音（復元不可）。保存する場合: キャンセル後にダウンロード';
  byId<HTMLDialogElement>('replace-dialog').showModal();
}

/** 録音開始ボタン。文字にできていない音声があれば置換の確認へ、無ければ録音を始める。 */
function onRecordClick(): void {
  if (keptNeedsResend()) {
    openReplaceDialog();
    return;
  }
  void startRecording();
}

/** 端末内の音声を、録った日時の名前で端末へ保存する。 */
function downloadKept(): void {
  const kept = present(state.kept, 'kept');
  const url = URL.createObjectURL(kept.blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = downloadName(kept);
  anchor.click();
  URL.revokeObjectURL(url);
}

/** 端末内の音声をもう一度送信する。失敗した前の件は一覧から外す。 */
async function resendKept(): Promise<void> {
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

/** 操作を受け付けてから、期限を過ぎた音声と結果を削除して読み込み、描く。 */
async function init(): Promise<void> {
  $('record_button').addEventListener('click', onRecordClick);
  $('stop_button').addEventListener('click', stopRecording);
  $<HTMLInputElement>('file_input').addEventListener('change', (event) => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) void sendFile(file);
  });
  $<HTMLSelectElement>('preset_select').addEventListener('change', (event) => {
    state.selectedPreset = (event.currentTarget as HTMLSelectElement).value;
    saveStoredPreset(state.selectedPreset);
  });
  state.keepScreenOn = loadStoredKeepScreen();
  $<HTMLInputElement>('keep_screen_check').addEventListener('change', (event) => {
    state.keepScreenOn = (event.currentTarget as HTMLInputElement).checked;
    saveStoredKeepScreen(state.keepScreenOn);
  });
  // 画面が隠れるとブラウザが Screen Wake Lock を解放するため、録音中に画面へ戻ったら取得し直す
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void acquireWakeLock();
  });
  $('download_button').addEventListener('click', downloadKept);
  $('resend_button').addEventListener('click', () => void resendKept());
  $('delete_cancel').addEventListener('click', () => byId<HTMLDialogElement>('delete-dialog').close());
  $('delete_confirm').addEventListener('click', confirmDelete);
  $('replace_cancel').addEventListener('click', () => byId<HTMLDialogElement>('replace-dialog').close());
  $('replace_confirm').addEventListener('click', () => {
    byId<HTMLDialogElement>('replace-dialog').close();
    void startRecording();
  });


  const kept = await loadKept();
  if (kept && isExpired(kept.recorded_at)) {
    await deleteKept();
  } else if (kept) {
    // 送信の途中で画面を閉じた音声は、送信できていないものとして扱う
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
      reportsProgress: false,
      error: null,
    }));
  saveResults();

  render();
  ensurePolling();

  // 用語集のプリセットの一覧を取りに行き、端末に覚えた選択を戻す（一覧を待つ間も録音とファイル送信は始められる）
  state.selectedPreset = loadStoredPreset();
  applyPresets(await fetchPresets());
  renderPresetOptions();
}

void init();
