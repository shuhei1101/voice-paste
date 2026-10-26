"""#183 の pyscan.py と同じ語のパターンを、src/・tests/ のコメント・docstring・ログの文言に当てて数える。

数える文字列: .py のコメント・docstring・式文だけの文字列・ログの呼び出しの引数の文字列リテラルと、
.ts / .js / .css / .html のコメント。
使い方: python3 -I commentscan.py {リポジトリの直下}
"""
import ast
import io
import json
import pathlib
import re
import sys
import tokenize

K = r'[一-鿿々]'
MULTI = ['送る', '送っ', '送れ', '送ら', '送り', '足す', '足し', '足さ', '足せ', '問い', '答え', '写し', '消す', '消し', '直す', '直し']
SINGLE = ['版', '節', '印', '口', '形', '段', '題']
PAT = re.compile('|'.join(MULTI) + '|' + '|'.join(f'(?<!{K}){c}(?!{K})' for c in SINGLE))
LOG_METHODS = {'debug', 'info', 'warning', 'error', 'exception', 'critical'}
WEB_COMMENT = re.compile(r'//[^\n]*|/\*.*?\*/|<!--.*?-->', re.S)

root = pathlib.Path(sys.argv[1])
per = {}
kinds = {'comment': 0, 'docstring': 0, 'log': 0, 'web_comment': 0}


def count(rel, kind, text):
    hits = len(PAT.findall(text))
    if hits:
        per[rel] = per.get(rel, 0) + hits
        kinds[kind] += hits


for path in sorted([*(root / 'src').rglob('*.py'), *(root / 'tests').rglob('*.py')]):
    rel = str(path.relative_to(root))
    source = path.read_text(encoding='utf-8')
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            count(rel, 'comment', token.string)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            count(rel, 'docstring', node.value.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS:
            for arg in node.args:
                for child in ast.walk(arg):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        count(rel, 'log', child.value)

for suffix in ('*.ts', '*.js', '*.css', '*.html'):
    for path in sorted((root / 'src').rglob(suffix)):
        if 'node_modules' in path.parts:
            continue
        rel = str(path.relative_to(root))
        for match in WEB_COMMENT.finditer(path.read_text(encoding='utf-8')):
            count(rel, 'web_comment', match.group())

print(json.dumps({'hits': sum(per.values()), 'files_with_hits': len(per), 'by_kind': kinds,
                  'src': sum(v for k, v in per.items() if k.startswith('src')),
                  'tests': sum(v for k, v in per.items() if k.startswith('tests')),
                  'top_files': sorted(per.items(), key=lambda x: -x[1])[:8]}, ensure_ascii=False))
