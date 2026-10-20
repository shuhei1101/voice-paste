"""連続録音の E2E が、返送先の受け口に届いた返送を確かめる補助。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

type Payload = dict[str, Any]
"""返送先の受け口に届いた JSON 1 件。"""

SEGMENT_GAP_SEC = 3.0
"""文と文の間に挟む無音の長さ。区切る無音の長さの既定（2 秒）より長くして、文ごとに区切らせる。"""

SHORT_GAP_SEC = 0.4
"""話し続ける読み上げで、文と文の間に挟む無音の長さ。区切る無音の長さの既定（2 秒）より短くして、無音では区切らせない。"""

TROUBLED_SEGMENT = 2
"""文字起こしの失敗・返送の失敗を起こさせる区間の通し番号。"""

THREE_SENTENCES: tuple[tuple[str, str], ...] = (
    ("これはテストです", "テスト"),
    ("今日はいい天気です", "天気"),
    ("ありがとうございました", "ありがとう"),
)
"""読み上げる 3 文と、それぞれを起こした文字に含まれるはずの言葉。"""


def sentences_of(pairs: Sequence[tuple[str, str]]) -> list[str]:
    """文と言葉の組から、読み上げる文だけを順に返す。"""
    return [sentence for sentence, _word in pairs]


def words_of(pairs: Sequence[tuple[str, str]]) -> list[str]:
    """文と言葉の組から、起こした文字に含まれるはずの言葉だけを順に返す。"""
    return [word for _sentence, word in pairs]


def segments_of(payloads: Sequence[Payload]) -> list[Payload]:
    """届いた返送のうち、区間の返送（通し番号がある）だけを届いた順に返す。"""
    return [payload for payload in payloads if payload["segment_number"] is not None]


def end_of(payloads: Sequence[Payload]) -> Payload:
    """届いた返送のうち、連続録音の終わりが 1 回だけ届いていることを確かめて、その返送を返す。"""
    ends = [payload for payload in payloads if payload["segment_number"] is None]
    assert len(ends) == 1
    return ends[0]


def assert_numbered_in_order(segments: Sequence[Payload], session_id: str) -> None:
    """区間の返送が、同じセッションの 1 から始まる通し番号の順に、起こせた文字として届いていることを確かめる。"""
    assert [segment["segment_number"] for segment in segments] == list(range(1, len(segments) + 1))
    for segment in segments:
        assert segment["session_id"] == session_id
        assert segment["result"] == "transcribed"
        assert segment["error"] is None
        assert segment["segment_count"] is None


def assert_each_word(segments: Sequence[Payload], words: Sequence[str]) -> None:
    """区間ごとに、起こした文字がその区間で読み上げた文の言葉を含むことを確かめる。"""
    assert len(segments) == len(words)
    for segment, word in zip(segments, words, strict=True):
        assert word in segment["text"]


def assert_all_words(segments: Sequence[Payload], words: Sequence[str]) -> None:
    """区間の文字を通し番号の順につないだものが、読み上げた文の言葉を全て含むことを確かめる。"""
    joined = "".join(segment["text"] for segment in segments)
    for word in words:
        assert word in joined


def assert_ended(
    payloads: Sequence[Payload], session_id: str, result: str, segment_count: int
) -> None:
    """連続録音の終わり（終わった理由と区間の数）が、最後に 1 回だけ届いていることを確かめる。"""
    end = end_of(payloads)
    assert end == {
        "session_id": session_id,
        "result": result,
        "text": "",
        "error": None,
        "segment_number": None,
        "segment_count": segment_count,
    }
    assert payloads[-1] == end


def assert_completed(payloads: Sequence[Payload], session_id: str, segment_count: int) -> None:
    """連続録音の終わり（completed と区間の数）が、最後に 1 回だけ届いていることを確かめる。"""
    assert_ended(payloads, session_id, "completed", segment_count)
