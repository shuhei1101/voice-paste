"""セッションの API のリクエスト・レスポンス。"""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel


class StartSessionRequest(BaseModel):
    """POST /sessions の body。"""

    callback_url: AnyHttpUrl
    """返送先。ホストが許されるかは route が出力先の is_callback_allowed で確かめる。"""


class StartSessionResponse(BaseModel):
    """POST /sessions の 202 の body。"""

    session_id: str
    """始めたセッションの ID。"""
