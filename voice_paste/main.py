"""エントリーポイント。起動フローを制御する高レベルモジュール。"""

from pathlib import Path

from voice_paste import config
from voice_paste.logger import setup_logger, get_logger
from voice_paste.audio.recorder import AudioRecorder
from voice_paste.transcription.whisper_transcriber import WhisperTranscriber
from voice_paste.input.keyboard_sender import copy_to_clipboard, send_paste, send_enter
from voice_paste.gui import RecordingModal
from voice_paste.utils import load_prompt
from voice_paste.constants import DEFAULT_AUDIO_TMP

logger = get_logger(__name__)


def run() -> None:
    """メイン処理フローを実行する。"""
    setup_logger(config.LOG_LEVEL)
    logger.info("voice-paste started.")

    recorder = AudioRecorder()
    transcriber = WhisperTranscriber()
    prompt = load_prompt(config.PROMPT_FILE)

    confirmed = False

    def on_confirm() -> None:
        nonlocal confirmed
        confirmed = True

    def on_cancel() -> None:
        logger.info("Cancelled by user.")

    # 録音開始 → モーダル表示（recorder を渡して波形アニメーションに使用）
    recorder.start()
    modal = RecordingModal(on_confirm=on_confirm, on_cancel=on_cancel, recorder=recorder)
    modal.show()

    if not confirmed:
        recorder.cancel()
        logger.info("voice-paste exited without output.")
        return

    # 録音停止・WAV保存
    audio_file: Path = recorder.stop_and_save(DEFAULT_AUDIO_TMP)

    # 文字起こし
    text = transcriber.transcribe(audio_file, prompt=prompt)
    logger.info("Transcribed text: %s", text)

    if not text:
        logger.warning("Transcription result is empty.")
        return

    # クリップボードにコピー
    copy_to_clipboard(text)

    # 自動貼り付け
    if config.AUTO_PASTE:
        send_paste()

    # 自動Enter送信
    if config.AUTO_ENTER:
        send_enter()

    logger.info("voice-paste completed successfully.")
