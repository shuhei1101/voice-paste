"""セッションの API のリクエスト・レスポンス。"""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel


class StartSessionRequest(BaseModel):
    """POST /sessions の body。"""

    callback_url: AnyHttpUrl
    """返送先。ホストが許されるかは route が出力先の is_callback_allowed で確かめる。"""

    continuous: bool = False
    """連続録音にするか。true なら完了まで録音を止めず、区間ごとに返送先へ送信する。省略時は 1 回の録音。"""

    glossary_preset: str | None = None
    """補正に使う用語集のプリセットの名前（省略時は設定で選んでいるプリセット）。一覧にあるかは route が glossary_preset_exists で確かめる。"""


class StartSessionResponse(BaseModel):
    """POST /sessions の 202 の body。"""

    session_id: str
    """始めたセッションの ID。"""
