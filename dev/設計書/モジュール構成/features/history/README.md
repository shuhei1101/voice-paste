# history

history の設計書

## 目次

| ページ | 概要 |
| --- | --- |
| [service.py](./service.py.yaml) | 確定した録音と起こした文字を `%LOCALAPPDATA%\voice-paste\history\`（Linux は `~/.local/share/voice-paste/history/`）に残し、保持期間を過ぎたものを消す。文字起こしの成否より先に録音を残す。 |
