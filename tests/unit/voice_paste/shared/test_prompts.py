"""shared/prompts.py（render_prompt）の単体テスト。

一時のプロンプトファイルを使うテストは、PROMPTS_DIR を一時フォルダに差し替える。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

SKIPPED_PART_PROMPT = """\
id: skipped
name: when で外す部品を持つプロンプト
kind: llm
lang: ja
description: when が偽の部品を外す
vars:
  flag:
    type: boolean
    required: true
    description: 2 つ目の部品を使うか
    example: true
parts:
  - id: always
    role: user
    texts:
      - lang: ja
        text: いつも入る本文
  - id: optional
    role: user
    when: "{{ flag }}"
    texts:
      - lang: ja
        text: flag が真のときだけ入る本文
"""
"""2 つ目の部品が when: "{{ flag }}" を持つプロンプトファイル。"""

EN_ONLY_JA_PROMPT = """\
id: en-only-ja
name: 注入する言語の本文が無いプロンプト
kind: llm
lang: en
description: lang が en で、部品が ja の本文だけを持つ
parts:
  - id: body
    role: user
    texts:
      - lang: ja
        text: 日本語の本文だけ
"""
"""トップレベルの lang が en で、部品が ja の本文だけを持つプロンプトファイル。"""


@pytest.fixture
def prompts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PROMPTS_DIR を一時フォルダに差し替えて、そのフォルダを返す。"""
    from voice_paste.shared import prompts

    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    return tmp_path


def test_render_prompt() -> None:
    """変数を入れた本文を返却する（正常系）。"""
    from voice_paste.shared.prompts import render_prompt

    # 実行
    text = render_prompt("openai-transcribe", {"hint": "voice-paste、Whisper"})

    # 検証
    assert text == "voice-paste、Whisper"


def test_render_prompt_when_part_skipped(prompts_dir: Path) -> None:
    """when が偽の部品を使用しない（正常系）。"""
    from voice_paste.shared.prompts import render_prompt

    # 準備
    (prompts_dir / "skipped.yaml").write_text(SKIPPED_PART_PROMPT, encoding="utf-8")

    # 実行
    text = render_prompt("skipped", {"flag": False})

    # 検証
    assert text == "いつも入る本文"


def test_render_prompt_when_missing(prompts_dir: Path) -> None:
    """ファイルが無ければ PromptError（異常系）。"""
    from voice_paste.shared.errors import PromptError
    from voice_paste.shared.prompts import render_prompt

    # 実行・検証
    with pytest.raises(PromptError, match="missing"):
        render_prompt("missing", {})


def test_render_prompt_when_undefined_var() -> None:
    """足りない変数は PromptError（異常系）。"""
    from voice_paste.shared.errors import PromptError
    from voice_paste.shared.prompts import render_prompt

    # 実行・検証: メッセージにプロンプトの ID と部品の ID を含む
    with pytest.raises(PromptError, match=r"openai-transcribe.*hint"):
        render_prompt("openai-transcribe", {})


def test_render_prompt_when_lang_missing(prompts_dir: Path) -> None:
    """注入する言語の本文が無い部品は PromptError（異常系）。"""
    from voice_paste.shared.errors import PromptError
    from voice_paste.shared.prompts import render_prompt

    # 準備
    (prompts_dir / "en-only-ja.yaml").write_text(EN_ONLY_JA_PROMPT, encoding="utf-8")

    # 実行・検証
    with pytest.raises(PromptError, match=r"en-only-ja.*body"):
        render_prompt("en-only-ja", {})
