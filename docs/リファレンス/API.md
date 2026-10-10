# API

ほかのプロセスが録音を始めて確定し、起こした文字を受け取る API の一覧

常駐サービスが起動している間、同じ端末の `127.0.0.1` だけで待ち受ける。
ポートは設定の `api.port`（既定 47823）。

どの要求にも次を付ける。

- `Authorization: Bearer {トークン}`。トークンは起動のたびに作り直し、`%LOCALAPPDATA%\voice-paste\api_token` に JSON（`port`・`token`）で書かれる。呼び出し元はこのファイルを読む
- `Host` は `127.0.0.1` か `localhost`
- `Origin` は付けない（ブラウザのページからの要求は断る）

録音と文字起こしは、ホットキー・トレイ・API をまたいで同時に 1 つだけ動く。
API から始めた録音は録音の画面を出さず、起こした文字は応答ではなく、開始で指定した返送先へ届く。

エラーは `application/problem+json`（`type`・`title`・`status`・`detail`）で返る。

## 一覧

| 名前 | エンドポイント | 説明 |
| --- | --- | --- |
| [録音を開始する](#録音を開始する) | `POST /sessions` | 画面を出さない録音を始めてセッションの ID を返す |
| [録音を停止する](#録音を停止する) | `POST /sessions/{session_id}/stop` | 録音を止め、完了を待つ状態にする |
| [録音を完了する](#録音を完了する) | `POST /sessions/{session_id}/complete` | 録音を確定し、文字起こしを始める |
| [結果を返送する](#結果を返送する) | `POST {callback_url}` | 起こした文字・失敗・打ち切りを返送先へ送る |

## 録音を開始する

画面を出さない録音を始めてセッションの ID を返す。
設定で録音中の音量を下げるようにしていれば、システム音量を下げる。

`continuous` を `true` にすると、完了を呼ぶまで録音を止めない連続録音になる。
話し声の後で無音が設定の `api.continuous.min_silence_sec`（既定 2 秒）以上続いたところで区切り、区切った単位（区間）ごとに起こした文字を、区切った順に返送先へ送る。
話し声を含まない無音だけの間は区間にせず、返送もしない。
無音が来ないまま区間が 20 秒に達したときは、直近の短い無音の中か、その位置で区切る。
背景にノイズがあると、区切りの無音をわずかに超える間では区切れず、区間が長くなることがある。
背景に人の声（ゲームの台詞など）があると話し声と見分けられず、区切れない。
連続録音のセッションの上限は、開始から設定の `api.continuous.session_limit_sec`（既定 14400 秒 = 4 時間）。

### リクエスト

```json
{ "callback_url": "http://127.0.0.1:9000/voice-paste/result", "continuous": false }
```

| フィールド | 必須 / 任意 | 説明 |
| --- | --- | --- |
| `callback_url` | 必須 | 結果を返すエンドポイントの URI。ホストは loopback（`127.0.0.0/8`・`::1`・`localhost`）か、設定の `api.allowed_callback_hosts` に書いたホスト |
| `continuous` | 任意 | 連続録音にするか。`true` なら完了まで録音を止めず、区間ごとに返送先へ送る。`false` なら 1 回の録音を確定してから 1 回だけ送る。省略時は `false` |

次の例は、トークンのファイルを読んで開始を呼ぶ。

```python
import json, os, urllib.request

info = json.load(open(os.path.expandvars(r"%LOCALAPPDATA%\voice-paste\api_token")))
request = urllib.request.Request(
    f"http://127.0.0.1:{info['port']}/sessions",
    data=json.dumps({"callback_url": "http://127.0.0.1:9000/voice-paste/result"}).encode(),
    headers={"Authorization": f"Bearer {info['token']}", "Content-Type": "application/json"},
    method="POST",
)
print(json.load(urllib.request.urlopen(request)))
```

### レスポンス

```json
{ "session_id": "3f1c2a9e-8d4b-4c4e-9a0b-2f7d1e6c5b10" }
```

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `session_id` | str | 始めた録音のセッションの ID。停止・完了と返送で使う |

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `400` | `callback_url` が無い・URI でない・loopback でも許可したホストでもない |
| `401` | トークンが無いか、今回の起動のものと合わない |
| `403` | `Origin` が付いているか、`Host` が `127.0.0.1` でも `localhost` でもない |
| `409` | ほかの録音・文字起こしが処理中 |
| `503` | マイクを開けず、録音を始められない |

成功は `202`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E9%8C%B2%E9%9F%B3%E3%82%92%E9%96%8B%E5%A7%8B%E3%81%99%E3%82%8B.py.yaml)

## 録音を停止する

録音を止め、完了を待つ状態にする。
止めた後の音は貯めず、システム音量は録音前に戻る。
止めたセッションへもう一度呼んでも `200` を返し、状態は変わらない。
連続録音のセッションは止めずに `409` で断る。連続録音は[録音を完了する](#録音を完了する)で終える。

### リクエスト

パスの `session_id` に、開始で受け取ったセッションの ID を入れる。
本文は無い。

### レスポンス

本文は無い。

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `401` | トークンが無いか、今回の起動のものと合わない |
| `403` | `Origin` が付いているか、`Host` が `127.0.0.1` でも `localhost` でもない |
| `404` | そのセッションが録音中でも停止中でもない（知らない ID・完了済み・上限で打ち切り済み） |
| `409` | そのセッションが連続録音（`continuous` を `true` にして始めた）。録音は止まらず、区切りを続ける |

成功は `200`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E9%8C%B2%E9%9F%B3%E3%82%92%E5%81%9C%E6%AD%A2%E3%81%99%E3%82%8B.py.yaml)

## 録音を完了する

録音を確定して履歴に残し、文字起こしを始める。
停止せずに呼ぶと、録音を止めてから確定する。
`202` は文字起こしを受け付けたことだけを表し、結果は[結果を返送する](#結果を返送する)で届く。
同じセッションへの 2 度目の完了は `404`。
連続録音のセッションでは、録音を止め、区間に切り出していない話し声があれば最後の区間として区切って文字に起こす。
残りの区間の文字と終わり（`completed`）は、全て返送先へ届くまで処理中として、ほかの開始を断る。

### リクエスト

パスの `session_id` に、開始で受け取ったセッションの ID を入れる。
本文は無い。

### レスポンス

本文は無い。

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `401` | トークンが無いか、今回の起動のものと合わない |
| `403` | `Origin` が付いているか、`Host` が `127.0.0.1` でも `localhost` でもない |
| `404` | そのセッションが録音中でも停止中でもない（知らない ID・完了済み・上限で打ち切り済み） |

成功は `202`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E9%8C%B2%E9%9F%B3%E3%82%92%E5%AE%8C%E4%BA%86%E3%81%99%E3%82%8B.py.yaml)

## 結果を返送する

API から始めた録音の結果を、開始で指定した `callback_url` へ送る。
連続録音でない録音では、1 セッションにつき 1 つの中身だけを送る。
完了が来ないままセッションの上限（開始から 600 秒。停止中も数える）に達したときは、録音を履歴に残して `truncated` を送り、文字起こしはしない。
連続録音では、区間の文字起こしが終わるたびに区間の返送を区切った順に送り、全ての区間を送り終えた後に終わりの返送を 1 回送る。
連続録音が完了せずに上限（`api.continuous.session_limit_sec`）に達したときは、そこまでの話し声を最後の区間として送った後に、終わりとして `truncated` を送る。

### リクエスト

常駐サービスが `callback_url` へ `application/json` で `POST` する。

```json
{
  "session_id": "3f1c2a9e-8d4b-4c4e-9a0b-2f7d1e6c5b10",
  "result": "transcribed",
  "text": "今日の会議は 15 時からです。",
  "error": null,
  "segment_number": null,
  "segment_count": null
}
```

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `session_id` | str | 開始で返したセッションの ID |
| `result` | str | `transcribed`（起こした文字を得た。結果が空の場合を含む）・`failed`（文字起こしに失敗した）・`truncated`（完了が来ないまま上限で打ち切った）・`completed`（連続録音を完了し、全ての区間を送り終えた。連続録音だけ） |
| `text` | str | 用語集で補正した文字。`transcribed` で結果が空のときと、`failed`・`truncated`・`completed` のときは空文字 |
| `error` | str または null | `failed` のときの理由。それ以外は `null` |
| `segment_number` | int または null | 連続録音の区間の通し番号（1 から 1 ずつ増える）。連続録音の `transcribed` と、区間の `failed` のときだけ入る。それ以外は `null` |
| `segment_count` | int または null | 連続録音で区切った区間の数（届かなかった区間も含む。区間が無ければ 0）。連続録音の終わり（`completed`・`truncated`、区切りの失敗で止まったときの `failed`）だけに入る。それ以外は `null` |

`continuous` を指定しない開始では、`segment_number` と `segment_count` は常に `null` で、それ以外の中身は変わらない。

連続録音では、区間の返送と終わりの返送を、次のように見分ける。

| 返送 | `result` | `segment_number` | `segment_count` |
| --- | --- | --- | --- |
| 区間の文字 | `transcribed` | 通し番号 | `null` |
| 区間の文字起こしの失敗。次の区間へ進む | `failed` | 通し番号 | `null` |
| 完了による終わり | `completed` | `null` | 区間の数 |
| 上限での終わり | `truncated` | `null` | 区間の数 |
| 区切りの失敗で録音が止まった終わり | `failed` | `null` | 区間の数 |

区間の返送と終わりの返送の例。

```json
{
  "session_id": "3f1c2a9e-8d4b-4c4e-9a0b-2f7d1e6c5b10",
  "result": "transcribed",
  "text": "今日の会議は 15 時からです。",
  "error": null,
  "segment_number": 1,
  "segment_count": null
}
```

```json
{
  "session_id": "3f1c2a9e-8d4b-4c4e-9a0b-2f7d1e6c5b10",
  "result": "completed",
  "text": "",
  "error": null,
  "segment_number": null,
  "segment_count": 3
}
```

区切ってから区間の返送が届くまでは、3 秒以内にする。

### レスポンス

受け口は、受け取ったら 1 秒以内に `2xx` を返す。
重い処理は `2xx` を返した後で行う。

リダイレクトは追わない。

### エラー

届かなかったときは、タイムアウト（1.5 秒）・再送（最大 3 回）の後、ログに届かなかったことと `session_id` を書いて終える。
履歴は残り、常駐サービスは待機中に戻る。

受け口が `2xx` を返す前にタイムアウトすると、同じ中身が同じ `session_id` で再送される。
受け口は `session_id` で重複を見分ける。
連続録音の区間は `session_id` と `segment_number`、終わりは `session_id` と `result` で見分ける。

連続録音の区間が再送しても届かなかったときは、ログに届かなかったことと `session_id`・`segment_number` を書き、その区間の通し番号を飛ばして次の区間へ進む。
受け口は、通し番号の欠けと終わりの `segment_count` で、届かなかった区間に気づく。
前の区間を再送している間は、後の区間と終わりがその分だけ待つ。

常駐サービスを終えたときに捨てた録音（録音中・停止中のセッション）は返送しない。
呼び出し元は、返送が来ないことで気づく。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E5%91%BC%E3%81%B3%E5%87%BA%E3%81%97%E5%85%83%E3%81%B8%E8%BF%94%E3%81%99.py.yaml)
