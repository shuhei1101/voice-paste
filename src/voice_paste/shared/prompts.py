"""content/prompts/ のプロンプトファイルを読み、変数を入れて注入する本文を描く。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jinja2

from voice_paste.shared.constants import REPO_ROOT
from voice_paste.shared.errors import PromptError, SettingsError
from voice_paste.shared.yaml_document import read_yaml_mapping

PROMPTS_DIR: Path = REPO_ROOT / "content" / "prompts"
"""プロンプトファイルを置くリポジトリの直下の content/prompts/。"""

_FALSE_WHEN_RESULTS: frozenset[str] = frozenset({"", "False"})
"""when の式を描いた結果のうち、部品を使わない値。"""


def render_prompt(prompt_id: str, values: Mapping[str, object]) -> str:
    """プロンプトファイルを ID で読み、使う部品の注入する言語の本文に変数を入れて、改行でつないで返す。"""
    # 1. ファイルがあるかを確かめる
    path = PROMPTS_DIR / f"{prompt_id}.yaml"
    if not path.is_file():
        raise PromptError(f"プロンプトファイルが無い（{prompt_id}）")

    # 2. 素の dict として読む（読めないものは PromptError に変える）
    try:
        prompt: dict[str, Any] = read_yaml_mapping(path)
    except (SettingsError, OSError) as error:
        raise PromptError(f"プロンプトファイルを読めない（{prompt_id}）") from error

    # 3. 未定義の変数を例外にする環境を作る
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    lang = prompt.get("lang")
    texts: list[str] = []
    for part in prompt.get("parts", []):
        part_id = part.get("id")
        try:
            # 4. when があれば、描いた結果が空・False でない部品だけを使う
            when = part.get("when")
            if when is not None and env.from_string(when).render(values).strip() in _FALSE_WHEN_RESULTS:
                continue

            # 5. 注入する言語の本文を選んで描く
            body = next(
                (text["text"] for text in part.get("texts", []) if text.get("lang") == lang),
                None,
            )
            if body is None:
                # 注入する言語の本文が無い: 描けない
                raise PromptError(f"注入する言語の本文が無い（{prompt_id}・{part_id}・{lang}）")
            texts.append(env.from_string(body).render(values))
        except jinja2.TemplateError as error:
            raise PromptError(f"プロンプトを描けない（{prompt_id}・{part_id}: {error}）") from error

    # 6. 描いた本文を改行でつなぐ
    return "\n".join(texts)
