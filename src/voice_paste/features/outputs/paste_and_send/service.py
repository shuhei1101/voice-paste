"""貼り付けて送信。クリップボードへ書き、貼り付けのキーと、設定の間を置いて設定の修飾キーを押したまま Enter を送信する。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
from voice_paste.features.outputs.types import OutputDeps
from voice_paste.shared.settings import Settings
from voice_paste.shared.types import EnterModifier, SendEnterFn, TranscriptionOutcome


def paste_and_send(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    copy: Callable[[str], None],
    paste: Callable[[], None],
    send_enter: SendEnterFn,
    sleep: Callable[[float], None],
    get_enter_delay_sec: Callable[[], float],
    get_enter_modifiers: Callable[[], tuple[EnterModifier, ...]],
) -> None:
    """起こした文字をクリップボードへ書いて貼り付け、設定の間を置いて設定の修飾キーを押したまま Enter を送信する。"""
    # 1. クリップボードへ書く（書けなければ DeliveryError のまま伝え、キーは送信しない）
    copy(outcome.text)

    # 2. 貼り付けのキーを送信する
    paste()

    # 3. 設定の間だけ待ち、設定の修飾キーを押したまま Enter を送信する
    sleep(get_enter_delay_sec())
    send_enter(get_enter_modifiers())


def read_enter_delay_sec(settings: Settings) -> float:
    """設定の outputs[] の貼り付けて送信の、貼り付けてから Enter を送信するまでの秒数を返す（一覧に無ければ既定値）。"""
    output = next(
        (o for o in settings.outputs if isinstance(o, PasteAndSendSettings)),
        PasteAndSendSettings(),
    )
    return output.enter_delay_sec


def read_enter_modifiers(settings: Settings) -> tuple[EnterModifier, ...]:
    """設定の outputs[] の貼り付けて送信の、Enter と一緒に押す修飾キーを返す（一覧に無ければ空）。"""
    output = next(
        (o for o in settings.outputs if isinstance(o, PasteAndSendSettings)),
        PasteAndSendSettings(),
    )
    return tuple(output.enter_modifiers)


def inject_paste_and_send(deps: OutputDeps) -> Mapping[str, object]:
    """paste_and_send に部分適用する copy・paste・send_enter・sleep・get_enter_delay_sec・get_enter_modifiers を返す。"""

    def get_enter_delay_sec() -> float:
        """呼ぶたびに今の設定の貼り付けて送信の秒数を返す。"""
        return read_enter_delay_sec(deps.get_settings())

    def get_enter_modifiers() -> tuple[EnterModifier, ...]:
        """呼ぶたびに今の設定の貼り付けて送信の修飾キーを返す。"""
        return read_enter_modifiers(deps.get_settings())

    return {
        "copy": deps.copy,
        "paste": deps.paste,
        "send_enter": deps.send_enter,
        "sleep": deps.sleep,
        "get_enter_delay_sec": get_enter_delay_sec,
        "get_enter_modifiers": get_enter_modifiers,
    }
