"""文字起こしのエンジンを使わない SessionManager の組み立て（GPU を使わない非機能要件テストの補助）。

録音の入力は WAV を流すもの、システム音量は何もしないものに差し替えた録音機（実機のマイクを開かない）で、
話し声の判定（Silero VAD）は本物、返送は返送先の受け口へ届ける出力先だけを使う。
文字起こしは、渡された関数（既定はエンジンが無いので呼ばれたら失敗させるもの）で起こす。
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from tests.support.inprocess import WavInput, ignore_lower_volume, ignore_restore_volume
from voice_paste.features.history import append_text, discard_temporary, save_recording
from voice_paste.features.outputs import OUTPUTS, deliver
from voice_paste.features.outputs.callback.service import (
    CALLBACK_RETRY_BASE_SEC,
    CALLBACK_RETRY_COUNT,
    CALLBACK_TIMEOUT_SEC,
)
from voice_paste.features.outputs.registry import CALLBACK_OUTPUT_ID
from voice_paste.features.recording import Recorder
from voice_paste.features.session import Session, SessionDeps, SessionManager
from voice_paste.features.session.types import TranscribeFn
from voice_paste.features.transcription.service import transcribe
from voice_paste.integrations.http.client import post_json
from voice_paste.integrations.vad.adapter import StreamingVad, load_vad_session
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.constants import resolve_app_paths
from voice_paste.shared.errors import EngineError
from voice_paste.shared.types import TranscriptionOutcome


def _no_engine(*_args: object, **_kwargs: object) -> list[str]:
    """文字起こしを呼ばない場面で、呼ばれたら失敗させる文字起こしのエンジン。"""
    raise EngineError("この場面では文字起こしを呼ばない")


def _local_now() -> datetime:
    """今の時刻を、この端末のタイムゾーンつきで返す。"""
    return datetime.now(UTC).astimezone()


def build_light_manager(
    tmp_path: Path,
    wav_input: WavInput,
    *,
    session_limit_sec: float,
    continuous_session_limit_sec: float | None = None,
    transcribe_fn: TranscribeFn | None = None,
) -> SessionManager:
    """録音の入力に wav_input を流し、上限時間を短くした SessionManager を作る（履歴は tmp_path に残す）。

    連続録音のセッションの上限時間は、渡さなければ設定の既定の値にする。文字起こしは、渡さなければ呼ばれたら失敗させる。
    """
    # 1. 録音機に、WAV を流す入力と何もしない音量と本物の話し声の判定を渡す
    paths = resolve_app_paths(tmp_path)
    settings = SETTINGS_MODEL()
    vad_session = load_vad_session()
    recorder = Recorder(
        lower_volume=ignore_lower_volume,
        restore_volume=ignore_restore_volume,
        open_input=wav_input,
        get_settings=lambda: settings.recording,
        create_speech_detector=partial(StreamingVad, vad_session),
    )

    # 2. 出力先は返送先へ届けるものだけにし、Session を入口・出力先・返送先に分けて渡す
    callback_spec = next(spec for spec in OUTPUTS if spec.id == CALLBACK_OUTPUT_ID)
    callback_handler = partial(
        callback_spec.handler,
        post=partial(post_json, timeout_sec=CALLBACK_TIMEOUT_SEC),
        allowed_hosts=frozenset(),
        retry_count=CALLBACK_RETRY_COUNT,
        retry_base_sec=CALLBACK_RETRY_BASE_SEC,
        sleep=time.sleep,
        jitter=lambda upper: upper,
    )
    outputs = (replace(callback_spec, handler=callback_handler),)

    def deliver_session(session: Session, outcome: TranscriptionOutcome) -> None:
        """Session を入口・出力先・返送先に分けて出力先の deliver へ渡す。"""
        deliver(
            session.entry,
            session.output_id,
            session.output_preset,
            session.callback_url,
            outcome,
            enabled_ids=frozenset(),
            outputs=outputs,
            preset_kinds=(),
        )

    # 3. SessionDeps を組み、上限時間を短くした SessionManager を作る
    deps = SessionDeps(
        start_recording=recorder.start,
        pause_recording=recorder.pause,
        resume_recording=recorder.resume,
        stop_recording=recorder.stop,
        discard_recording=recorder.discard,
        save_recording=partial(
            save_recording, history_enabled=True, paths=paths, now=_local_now
        ),
        transcribe=transcribe_fn or partial(transcribe, engine=_no_engine, get_hint=lambda: None),
        correct=lambda text: text,
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=lambda event, detail=None: None,
        now=_local_now,
        discard_temporary=partial(discard_temporary, paths=paths),
        report_progress=lambda position_sec, duration_sec: None,
        start_continuous_recording=partial(
            recorder.start_continuous, min_silence_sec=settings.api.continuous.min_silence_sec
        ),
        stop_continuous_recording=recorder.stop_continuous,
    )
    continuous_limit_sec = (
        settings.api.continuous.session_limit_sec
        if continuous_session_limit_sec is None
        else continuous_session_limit_sec
    )
    return SessionManager(
        deps, timedelta(seconds=session_limit_sec), timedelta(seconds=continuous_limit_sec)
    )
