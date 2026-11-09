"""reposcan.py と同じ語のパターンを、.py の文字列リテラルに当てて数える。

docstring・式文だけの文字列（属性の説明）と、ログの呼び出しの引数は数えない。
使い方: python3 -I pyscan.py {リポジトリの直下}
"""
import ast
import json
import pathlib
import re
import sys

K = r'[一-鿿々]'
MULTI = ['送る', '送っ', '送れ', '送ら', '送り', '足す', '足し', '足さ', '足せ', '問い', '答え', '写し', '消す', '消し', '直す', '直し']
SINGLE = ['版', '節', '印', '口', '形', '段', '題']
PAT = re.compile('|'.join(MULTI) + '|' + '|'.join(f'(?<!{K}){c}(?!{K})' for c in SINGLE))
TARGETS = ['src/voice_paste/ui', 'src/voice_paste/shared/settings.py', 'src/voice_paste/features/outputs', 'tests']
LOG_METHODS = {'debug', 'info', 'warning', 'error', 'exception', 'critical'}


def skipped_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            ids.update(id(n) for n in ast.walk(node))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS:
            for arg in node.args:
                ids.update(id(n) for n in ast.walk(arg))
    return ids


root = pathlib.Path(sys.argv[1])
per = {}
for target in TARGETS:
    base = root / target
    files = [base] if base.is_file() else sorted(base.rglob('*.py'))
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        skip = skipped_ids(tree)
        hits = sum(len(PAT.findall(n.value)) for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip)
        if hits:
            per[str(path.relative_to(root))] = hits
total = sum(per.values())
print(json.dumps({'hits': total, 'files_with_hits': len(per),
                  'by_target': {t: sum(v for k, v in per.items() if k.startswith(t)) for t in TARGETS},
                  'top_files': sorted(per.items(), key=lambda x: -x[1])[:8]}, ensure_ascii=False))
