#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。git の作業ツリーと、HEAD の .gitattributes へ読み取りだけでつながるかを確かめる
set -uo pipefail

if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  echo "git の作業ツリー: ok"
else
  echo "git の作業ツリー: failed"
  exit 1
fi

if git cat-file -e HEAD:.gitattributes 2> /dev/null; then
  echo "HEAD の .gitattributes: ok"
else
  echo "HEAD の .gitattributes: failed"
  exit 1
fi
