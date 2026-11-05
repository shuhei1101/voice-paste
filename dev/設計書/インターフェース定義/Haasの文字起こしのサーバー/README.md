# Haasの文字起こしのサーバー

WSL の中で Haas-ja-v1.0 を持つ文字起こしのサーバーの API

## 目次

| ページ | 概要 |
| --- | --- |
| [音声を文字に起こす.py](./音声を文字に起こす.py.yaml) | POST /transcriptions。受けた音声を Haas-ja-v1.0 で文字に起こして返す |
| [準備できたかを返す.py](./準備できたかを返す.py.yaml) | GET /health。モデルを読み込み終えたことを返す |
| [停止する.py](./停止する.py.yaml) | POST /shutdown。常駐アプリが起動したサーバーを止める |
