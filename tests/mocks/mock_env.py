"""環境変数モックモジュール。テスト時に使用する設定値を定義する。"""

MOCK_ENV = {
    "WHISPER_MODEL": "tiny",
    "WHISPER_DEVICE": "cpu",
    "WHISPER_COMPUTE_TYPE": "int8",
    "WHISPER_CPU_THREADS": "1",
    "WHISPER_NUM_WORKERS": "1",
    "WHISPER_BEAM_SIZE": "1",
    "WHISPER_LANGUAGE": "ja",
    "WHISPER_VAD_FILTER": "false",
    "WHISPER_CONDITION_ON_PREVIOUS_TEXT": "false",
    "WHISPER_TEMPERATURE": "0.0",
    "WHISPER_NO_SPEECH_THRESHOLD": "0.6",
    "PROMPT_FILE": "resources/prompt.txt",
    "AUTO_PASTE": "false",
    "AUTO_ENTER": "false",
    "LOG_LEVEL": "DEBUG",
}
