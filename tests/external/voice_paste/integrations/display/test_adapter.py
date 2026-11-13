"""integrations/display/adapter.py（inhibit_display・release_display）の契約テスト。

Windows の実機で電源要求の API を動かし、抑止を依頼したスレッドが終わった後も抑止が残り、解除で消えることを、
非昇格で読める CallNtPowerInformation(SystemExecutionState) の ES_DISPLAY_REQUIRED で確かめる（PoC #293 と同じ観測）。
実行中は画面が消灯しない。
"""

from __future__ import annotations

import sys
import threading

import pytest

if sys.platform != "win32":
    pytest.skip("電源要求の契約テストは Windows の実機でだけ実行する", allow_module_level=True)

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

SYSTEM_EXECUTION_STATE = 16
ES_DISPLAY_REQUIRED = 0x00000002


def _display_required() -> bool:
    """システム全体の実行状態が ES_DISPLAY_REQUIRED を含むか。"""
    value = wintypes.ULONG()
    status = ctypes.WinDLL("powrprof").CallNtPowerInformation(
        SYSTEM_EXECUTION_STATE, None, 0, ctypes.byref(value), ctypes.sizeof(value)
    )
    assert status == 0
    return bool(value.value & ES_DISPLAY_REQUIRED)


def test_ext_inhibit_display() -> None:
    """実機の Windows で、依頼したスレッドが終わった後も抑止が残り、解除で消える（契約テスト）。"""
    from voice_paste.integrations.display.adapter import inhibit_display, release_display

    # 準備: ほかのプロセスが画面の要求を持っていると観測できない
    if _display_required():
        pytest.skip("ほかのプロセスが ES_DISPLAY_REQUIRED を持っているため観測できない")

    # 実行: 別のスレッドで抑止し、そのスレッドを終える
    thread = threading.Thread(target=inhibit_display)
    thread.start()
    thread.join()
    try:
        # 検証
        assert _display_required()
    finally:
        release_display()
    assert not _display_required()
