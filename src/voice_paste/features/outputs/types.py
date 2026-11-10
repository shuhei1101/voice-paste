"""出力先・プリセットの種類の関数型と定義、送信する内容。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Self

from pydantic import BaseModel

from voice_paste.integrations.http.types import PostJsonFn
from voice_paste.shared.settings import OutputSettingsBase, Preset, Settings
from voice_paste.shared.types import SendEnterFn, TranscriptionOutcome

type OutputFn = Callable[[TranscriptionOutcome, str | None], None]
"""結果と出力先に固有の宛先（コールバック先の URL。持たない出力先は None）を受け、1 つの出力先へ届ける。届けられなければ DeliveryError。"""

type PresetFn = Callable[[TranscriptionOutcome, Preset], None]
"""結果と確定の操作で選んだプリセット（確定したときの設定のコピー）を受け、1 つのプリセットへ届ける。届けられなければ DeliveryError。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputDeps:
    """main.py が組む、各出力先の InjectFn が handler に部分適用するものを選ぶ元。外部連携の関数と今の設定の束。"""

    copy: Callable[[str], None]
    """クリップボードへ書く（copy_to_clipboard。書けなければ DeliveryError）。"""

    paste: Callable[[], None]
    """貼り付けのキーを送信する（呼ぶたびに設定の keyboard.paste_key を読んで PlatformAdapters.send_paste を呼ぶ）。"""

    send_enter: SendEnterFn
    """渡した修飾キーを押したまま Enter を送信する（修飾キーを省くと Enter だけ）。"""

    sleep: Callable[[float], None]
    """間を置く（time.sleep）。"""

    jitter: Callable[[float], float]
    """0 以上この値以下の乱数を返す（random.uniform(0, x)）。"""

    post: PostJsonFn
    """JSON を POST してステータスを返す（外部連携の post_json）。"""

    get_settings: Callable[[], Settings]
    """今の設定を返す（SettingsStore.get。届けるたびに読み、保存した immediate の項目を次の回から効かせる）。"""

    notify_copied: Callable[[str], None]
    """コピーの完了を起こした文字と共に画面へ知らせる（ui の notify_copied に UiBridge を部分適用したもの）。"""


type InjectFn = Callable[[OutputDeps], Mapping[str, object]]
"""配線に渡すものから、1 つの出力先の handler に部分適用するキーワード引数（handler の injected の引数名 → 渡すもの）を選んで返す。"""


def _inject_nothing(deps: OutputDeps) -> Mapping[str, object]:
    """注入するものの無い出力先の InjectFn。空の dict を返す。"""
    return {}


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputSpec:
    """出力先の ID・表示名・届ける関数・設定のモデル・注入するものを選ぶ関数の組。"""

    id: str
    """出力先の ID。設定の出力先の一覧と確定の操作がこの ID で指す。"""

    title: str
    """画面に出す名前。"""

    handler: OutputFn
    """届ける関数。"""

    api_only: bool = False
    """API から始めた録音だけが使うか（呼び出し元へ返すだけが True）。"""

    settings_model: type[OutputSettingsBase] | None = None
    """出力先の設定のモデル（id の既定値が id と同じ）。オン・オフを持たず設定の outputs[] に置かない出力先（API 専用）は None。"""

    inject: InjectFn = field(default=_inject_nothing)
    """配線で handler に部分適用するものを OutputDeps から選ぶ（_wire_outputs が呼ぶ）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class PresetKindSpec:
    """カスタムプリセットの種類・表示名・届ける関数の組。"""

    kind: str
    """プリセットの種類。設定の presets[].kind がこの値で指す。"""

    title: str
    """種類の名前（ブラウザ添付・エンドポイントへ送信）。"""

    handler: PresetFn
    """届ける関数。"""


class ResultPayload(BaseModel):
    """呼び出し元へ返す・エンドポイントへ送信が送信する JSON。"""

    session_id: str
    """録音セッションの ID。"""

    result: Literal["transcribed", "failed", "truncated"]
    """結果の種類。"""

    text: str
    """起こした文字（空もある）。"""

    error: str | None
    """失敗の理由。"""

    @classmethod
    def from_outcome(cls, outcome: TranscriptionOutcome) -> Self:
        """結果の session_id・result・text・error をコピーした中身を作る。"""
        return cls(
            session_id=outcome.session_id,
            result=outcome.result,
            text=outcome.text,
            error=outcome.error,
        )


class CallbackPayload(ResultPayload):
    """呼び出し元へ返す JSON。ResultPayload に、連続録音の区間の通し番号と区間の数を追加する。

    設定のエンドポイントへ送信する内容（ResultPayload）は変えないため、呼び出し元へ返すときだけこの子を使う。
    """

    result: Literal["transcribed", "failed", "truncated", "completed"]  # type: ignore[assignment] 親より結果の種類が 1 つ多い（completed は連続録音だけ）
    """結果の種類。"""

    segment_number: int | None
    """連続録音の区間の通し番号。それ以外は None。"""

    segment_count: int | None
    """連続録音の終わり（completed・truncated・区切りの失敗の failed）の区間の数。それ以外は None。"""

    @classmethod
    def from_outcome(cls, outcome: TranscriptionOutcome) -> Self:
        """結果の session_id・result・text・error・segment_number・segment_count をコピーした中身を作る。"""
        return cls(
            session_id=outcome.session_id,
            result=outcome.result,
            text=outcome.text,
            error=outcome.error,
            segment_number=outcome.segment_number,
            segment_count=outcome.segment_count,
        )
