"""結合テストの共通フィクスチャ。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import voice_paste.server.app as app_module
from tests.integration.helpers import (
    OutputStack,
    Stack,
    build_output_stack,
    build_stack,
    stop_stack,
)
from voice_paste.features.web_transcription.service import (
    WEB_FINISHED_JOBS_KEPT,
    WEB_QUEUE_LIMIT,
)
from voice_paste.server.body_limit import BodyLimitMiddleware
from voice_paste.shared.settings import Settings


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    """本物の app を空きポートに立て、偽物のマイク・音量・エンジンと返送先の受信先を差した一式を返す。"""
    built = build_stack(tmp_path)
    yield built
    stop_stack(built)


@pytest.fixture
def linux_stack(tmp_path: Path) -> Iterator[Stack]:
    """外の端末のブラウザの機能を組み込まない app（Linux の常駐サービス）を空きポートに立てた一式を返す。ブラウザの音声のキューは始めない。"""
    built = build_stack(tmp_path, web_enabled=False)
    yield built
    stop_stack(built)


@pytest.fixture
def stack_with_settings(tmp_path: Path) -> Iterator[Callable[[Settings], Stack]]:
    """設定を受けて、その設定で本物の app を立てた一式を作る関数を返す。テストの後に立てた一式を止める。"""
    built: list[Stack] = []

    def _build(settings: Settings) -> Stack:
        """設定で一式を作り、後片付けの対象に覚える。"""
        stack = build_stack(tmp_path, settings=settings)
        built.append(stack)
        return stack

    yield _build
    for stack in built:
        stop_stack(stack)


@pytest.fixture
def output_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[Settings | None], OutputStack]]:
    """設定を受けて、配線した出力先へ届く一式を作る関数を返す。テストの後に残ったセッションの録音を捨てる。"""
    built: list[OutputStack] = []

    def _build(settings: Settings | None = None) -> OutputStack:
        """設定（無ければ既定）で一式を作り、後片付けの対象に覚える。"""
        stack = build_output_stack(tmp_path, monkeypatch, settings)
        built.append(stack)
        return stack

    yield _build
    for stack in built:
        stack.manager.close()


@pytest.fixture
def web_stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Stack]]:
    """ブラウザの音声のキューの設定を差し替えた一式を作る関数を返す。worker が偽ならワーカースレッドを立てず、body_limit があれば本文の上限を差し替える。"""
    built: list[Stack] = []

    def _build(
        *,
        worker: bool = True,
        max_pending: int = WEB_QUEUE_LIMIT,
        max_finished: int = WEB_FINISHED_JOBS_KEPT,
        reports_progress: bool = True,
        body_limit: int | None = None,
        settings: Settings | None = None,
    ) -> Stack:
        """設定を差し替えた一式を作り、後片付けの対象に覚える。"""
        if body_limit is not None:

            class _LimitedBodyMiddleware(BodyLimitMiddleware):
                """本文の上限をテストの値にした BodyLimitMiddleware。"""

                def __init__(self, app: object) -> None:
                    super().__init__(app, limit=body_limit)  # type: ignore[arg-type]

            monkeypatch.setattr(app_module, "BodyLimitMiddleware", _LimitedBodyMiddleware)
        stack = build_stack(
            tmp_path,
            web_worker=worker,
            web_max_pending=max_pending,
            web_max_finished=max_finished,
            web_reports_progress=reports_progress,
            settings=settings,
        )
        built.append(stack)
        return stack

    yield _build
    for stack in built:
        stop_stack(stack)
