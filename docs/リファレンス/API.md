# API

ほかのプロセスが録音を始めて確定し、起こした文字を受け取る API の一覧

常駐サービスが起動している間、同じ端末の `127.0.0.1` だけで待ち受ける。
ポートは設定の `api.port`（既定 47823）。

`/sessions` の要求には次を付ける。

- `Authorization: Bearer {トークン}`。トークンは起動のたびに再生成し、`%LOCALAPPDATA%\voice-paste\api_token`（Linux は `~/.local/share/voice-paste/api_token`）に JSON（`port`・`token`）で書かれる。呼び出し元はこのファイルを読む
- `Host` は `127.0.0.1` か `localhost`
- `Origin` は付けない（ブラウザのページからの要求は断る）

録音と文字起こしは、ホットキー・トレイ・API をまたいで同時に 1 つだけ動く。
API から始めた録音は録音の画面を出さず、起こした文字は応答ではなく、開始で指定した返送先へ届く。

`/web/` の下の要求（外の端末のブラウザ向け）は、トークンを求めず、`Host` と `Origin` で通す。
`/web/` の下の API は、常駐サービスが Windows で動いているときだけ使える。
Linux では `Origin` によらず 404 を返す。

- `Host` は `127.0.0.1:{ポート}` か `localhost:{ポート}`。ゲートウェイ（shuhdev-gateway）を通した要求は `localhost:{ポート}` で届く
- `Origin` が無いか、設定の `api.allowed_web_origins`（[起動と設定](../使い方/起動と設定.md#外の端末のブラウザに許す-origin)）の一覧にあれば通す（同じ端末のほかのプロセスは `Origin` を付けずに送信できる）
- 外からの認証は、ゲートウェイの Cloudflare Access が持つ

`/web/` の下の音声の受け付けは `/sessions` と排他せず、録音・文字起こしの処理中も受け付ける。

エラーは `application/problem+json`（`type`・`title`・`status`・`detail`）で返る。

## 一覧

<!-- table: data -->

| 名前 | エンドポイント | 説明 |
| --- | --- | --- |
| [録音を開始する](#録音を開始する) | `POST /sessions` | 画面を出さない録音を始めてセッションの ID を返す |
| [録音を停止する](#録音を停止する) | `POST /sessions/{session_id}/stop` | 録音を止め、完了を待つ状態にする |
| [録音を完了する](#録音を完了する) | `POST /sessions/{session_id}/complete` | 録音を確定し、文字起こしを始める |
| [結果を返送する](#結果を返送する) | `POST {callback_url}` | 起こした文字・失敗・打ち切りを返送先へ送信する |
| [画面を開く](#画面を開く) | `GET /web/` | 外の端末のブラウザで開く文字起こしの画面を返す |
| [用語集のプリセットの一覧を取得する](#用語集のプリセットの一覧を取得する) | `GET /web/glossary-presets` | 用語集のプリセットの名前の一覧と、設定で補正に使うプリセットを返す |
| [音声を送信する](#音声を送信する) | `POST /web/transcriptions` | ブラウザから音声を受け付け、ジョブの ID を返す |
| [文字起こしの結果を取得する](#文字起こしの結果を取得する) | `GET /web/transcriptions/{job_id}` | ジョブの状態・進み具合と、起こした文字か失敗の理由を返す |

<!-- /table -->

## 録音を開始する

画面を出さない録音を始めてセッションの ID を返す。
設定で録音中の音量を下げるようにしていれば、システム音量を下げる。

`continuous` を `true` にすると、完了を呼ぶまで録音を止めない連続録音になる。
話し声の後で無音が設定の `api.continuous.min_silence_sec`（既定 2 秒）以上続いたところで区切り、区切った単位（区間）ごとに起こした文字を、区切った順に返送先へ送信する。
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
| `continuous` | 任意 | 連続録音にするか。`true` なら完了まで録音を止めず、区間ごとに返送先へ送信する。`false` なら 1 回の録音を確定してから 1 回だけ送信する。省略時は `false` |
| `glossary_preset` | 任意 | このセッションの補正に使う用語集のプリセットの名前（設定画面の「用語集のプリセット」の一覧にある名前。大文字と小文字は区別する）。省略時は、設定で補正に使うプリセットを使う。開始の後に設定でプリセットを切り替えても、このセッションは指定したプリセットで補正する |

次の例は、トークンのファイルを読んで開始を呼ぶ。

```python
import json, os, sys, urllib.request
from pathlib import Path

if sys.platform == "win32":
    token_path = Path(os.environ["LOCALAPPDATA"]) / "voice-paste" / "api_token"
else:
    token_path = Path.home() / ".local" / "share" / "voice-paste" / "api_token"
info = json.loads(token_path.read_text(encoding="utf-8"))
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
| `400` | `callback_url` が無い・URI でない・loopback でも許可したホストでもない。または `glossary_preset` が用語集のプリセットの一覧に無い |
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

API から始めた録音の結果を、開始で指定した `callback_url` へ送信する。
連続録音でない録音では、1 セッションにつき 1 つの中身だけを送信する。
完了が来ないままセッションの上限（開始から 600 秒。停止中も数える）に達したときは、録音を履歴に残して `truncated` を送信し、文字起こしはしない。
連続録音では、区間の文字起こしが終わるたびに区間の返送を区切った順に送信し、全ての区間を送信し終えた後に終わりの返送を 1 回送信する。
連続録音が完了せずに上限（`api.continuous.session_limit_sec`）に達したときは、そこまでの話し声を最後の区間として送信した後に、終わりとして `truncated` を送信する。

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

<!-- table: data -->

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `session_id` | str | 開始で返したセッションの ID |
| `result` | str | `transcribed`（起こした文字を得た。結果が空の場合を含む）・`failed`（文字起こしに失敗した）・`truncated`（完了が来ないまま上限で打ち切った）・`completed`（連続録音を完了し、全ての区間を送信し終えた。連続録音だけ） |
| `text` | str | 文頭・文末の文言を削除した後に、用語集で補正した文字。`transcribed` で結果が空のときと、`failed`・`truncated`・`completed` のときは空文字 |
| `error` | str または null | `failed` のときの理由。それ以外は `null` |
| `segment_number` | int または null | 連続録音の区間の通し番号（1 から 1 ずつ増える）。連続録音の `transcribed` と、区間の `failed` のときだけ入る。それ以外は `null` |
| `segment_count` | int または null | 連続録音で区切った区間の数（届かなかった区間も含む。区間が無ければ 0）。連続録音の終わり（`completed`・`truncated`、区切りの失敗で止まったときの `failed`）だけに入る。それ以外は `null` |

<!-- /table -->

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

区切ってから区間の返送が届くまでは、4 秒以内にする。

### レスポンス

エンドポイントは、受け取ったら 1 秒以内に `2xx` を返す。
重い処理は `2xx` を返した後で行う。

リダイレクトは追わない。

### エラー

届かなかったときは、タイムアウト（1.5 秒）・再送（最大 3 回）の後、ログに届かなかったことと `session_id` を書いて終える。
履歴は残り、常駐サービスは待機中に戻る。

エンドポイントが `2xx` を返す前にタイムアウトすると、同じ中身が同じ `session_id` で再送される。
エンドポイントは `session_id` で重複を見分ける。
連続録音の区間は `session_id` と `segment_number`、終わりは `session_id` と `result` で見分ける。

連続録音の区間が再送しても届かなかったときは、ログに届かなかったことと `session_id`・`segment_number` を書き、その区間の通し番号を飛ばして次の区間へ進む。
エンドポイントは、通し番号の欠けと終わりの `segment_count` で、届かなかった区間に気づく。
前の区間を再送している間は、後の区間と終わりがその分だけ待つ。

常駐サービスを終えたときに捨てた録音（録音中・停止中のセッション）は返送しない。
呼び出し元は、返送が来ないことで気づく。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E5%91%BC%E3%81%B3%E5%87%BA%E3%81%97%E5%85%83%E3%81%B8%E8%BF%94%E3%81%99.py.yaml)

## 画面を開く

外の端末のブラウザで開く文字起こしの画面（HTML）を返す。
画面が読む JS・CSS などの素材は `GET /web/assets/{ファイル}` で返す。
画面は常駐サービスのバージョンごとに変わるため、HTML はキャッシュさせない。
`/web`（末尾の `/` が無い）は `/web/` へ移す（`307`）。

### リクエスト

パラメータも本文も無い。
ゲートウェイを通した画面の要求は `Origin` が付かない。

### レスポンス

`/web/` は画面の HTML（`text/html; charset=utf-8`）。
`/web/assets/` の下は、拡張子に合う `Content-Type` で素材を返す。

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `403` | `Host` が待ち受けのホストでない。`Origin` が付いていて、許す `Origin` の一覧に無い |
| `404` | 同梱していない素材のパス |

成功は `200`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E7%94%BB%E9%9D%A2%E3%82%92%E9%85%8D%E4%BF%A1%E3%81%99%E3%82%8B.py.yaml)

## 用語集のプリセットの一覧を取得する

用語集のプリセットの名前の一覧と、設定で補正に使うプリセットの名前を返す。
返すのは名前だけで、プリセットが使う用語集やその中身は返さない。
呼ぶたびに今の設定を読むため、設定画面でプリセットを追加・削除・切り替えると、次の取得から変わった内容を返す。

### リクエスト

パラメータも本文も無い。

### レスポンス

```json
{
  "presets": ["既定", "会議"],
  "active": "既定"
}
```

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `presets` | list[str] | 用語集のプリセットの名前の一覧（設定の並びのまま）。プリセットを設定していないときは「既定」の 1 件 |
| `active` | str | 設定で補正に使うプリセットの名前。`glossary_preset` を省略して送信した音声は、このプリセットで補正する |

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `403` | `Host` が待ち受けのホストでない。`Origin` が付いていて、許す `Origin` の一覧に無い |

成功は `200`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E7%94%A8%E8%AA%9E%E9%9B%86%E3%81%AE%E3%83%97%E3%83%AA%E3%82%BB%E3%83%83%E3%83%88%E3%81%AE%E4%B8%80%E8%A6%A7%E3%82%92%E8%BF%94%E3%81%99.py.yaml)

## 音声を送信する

外の端末のブラウザから音声を受け付け、文字起こしのジョブを積んでジョブの ID を返す。
文字起こしの完了は待たずに返す。結果は[文字起こしの結果を取得する](#文字起こしの結果を取得する)で取りに行く。
起こした文字は、`glossary_preset` で指定した用語集のプリセット（省略時は、設定で補正に使うプリセット）で補正し、PC の履歴にも残す。
同じ音声を 2 回送信すると、別のジョブが 2 つ積まれる。
音声は録れた形式（webm・ogg・mp4 など）のまま文字起こしに渡し、WAV へは変換しない。
PC の[文字起こしのエンジン](../使い方/起動と設定.md#文字起こしのエンジン)が OpenAI API のときは、ogg の音声と 26,209,484 バイトを超える音声を受け付けても起こせず、ジョブは失敗になる。

### リクエスト

`multipart/form-data` で、音声を `audio` の項目に、用語集のプリセットの名前を `glossary_preset` の項目に入れる。

```http
POST /web/transcriptions HTTP/1.1
Host: localhost:47823
Origin: https://voice.example.com
Content-Type: multipart/form-data; boundary=----b

------b
Content-Disposition: form-data; name="audio"; filename="recording.webm"
Content-Type: audio/webm;codecs=opus

{音声のバイト列}
------b
Content-Disposition: form-data; name="glossary_preset"

会議
------b--
```

| フィールド | 必須 / 任意 | 説明 |
| --- | --- | --- |
| `audio` | 必須 | 送信する音声。webm・ogg・mp4・MP3・WAV など、音声のストリームを読める形式。形式は `Content-Type` やファイル名ではなく、中身で判定する。文字起こしのエンジンが OpenAI API のときは ogg を起こせない |
| `glossary_preset` | 任意 | この音声の補正に使う用語集のプリセットの名前（[用語集のプリセットの一覧を取得する](#用語集のプリセットの一覧を取得する)の `presets` にある名前。大文字と小文字は区別する）。省略時・空文字のときは、文字起こしを終えた時点で設定で補正に使うプリセットを使う。送信の後に設定でプリセットを切り替えても、この音声は指定したプリセットで補正する |

本文は 100,000,000 バイト未満にする（multipart の境界とヘッダーを含めて数える）。
各要求は、ゲートウェイの応答待ちの上限（83 秒）に余裕を持たせた 66 秒以内に返す。端末から本文を送信し終えるまでの時間も含む。

### レスポンス

```json
{ "job_id": "q3Vb8sXk2mJf0tLw9eRzAg" }
```

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `job_id` | str | 積んだジョブの ID。結果の取得で使う |

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `400` | `multipart/form-data` でない・`audio` の項目が無い。または `glossary_preset` が用語集のプリセットの一覧に無い |
| `403` | `Host` が待ち受けのホストでない。`Origin` が付いていて、許す `Origin` の一覧に無い |
| `413` | 本文が 100,000,000 バイト以上 |
| `415` | `audio` を開けない・音声のストリームが無い |
| `503` | 終わっていないジョブ（文字起こし待ちと文字起こし中）が 10 件に達している |

成功は `202`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E9%9F%B3%E5%A3%B0%E3%82%92%E5%8F%97%E3%81%91%E4%BB%98%E3%81%91%E3%82%8B.py.yaml)

## 文字起こしの結果を取得する

積んだジョブの状態・進み具合と、終わっていれば起こした文字か失敗の理由を返す。
取りに行ってもジョブは消えない。終わったジョブは、何度取りに行っても同じ内容を返す。
終わったジョブは直近 100 件までを常駐サービスのメモリに持ち、超えると古く終わった順に捨てる。
常駐サービスを再起動すると、それまでのジョブは全て `404` になる（起こした文字は PC の履歴に残る）。

### リクエスト

パスの `job_id` に、[音声を送信する](#音声を送信する)で受け取ったジョブの ID を入れる。
本文は無い。

### レスポンス

```json
{
  "job_id": "q3Vb8sXk2mJf0tLw9eRzAg",
  "state": "running",
  "progress": 0.42,
  "reports_progress": true,
  "text": null,
  "error": null
}
```

<!-- table: data -->

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `job_id` | str | 要求の `job_id` |
| `state` | str | `queued`（文字起こし待ち）・`running`（文字起こし中）・`done`（完了）・`failed`（失敗） |
| `progress` | float | 進み具合（0.0〜1.0）。`queued` は 0.0、`running` は起こし終えた区間の終わりの時刻 ÷ 音声の秒数、`done` は 1.0、`failed` は失敗した時点の値。`reports_progress` が `false` のときは `running` の間も 0.0 |
| `reports_progress` | bool | 設定の文字起こしのエンジンが途中の進みを返すか。`local_whisper` は `true`、`openai`・`haas` は `false` |
| `text` | str または null | `done` のときだけ文字列。文頭・文末の文言を削除した後に、用語集で補正した文字（話し声が無ければ空文字）。それ以外は `null` |
| `error` | str または null | `failed` のときだけ文字列。失敗の理由。それ以外は `null` |

<!-- /table -->

### エラー

| ステータスコード | 発生条件 |
| --- | --- |
| `403` | `Host` が待ち受けのホストでない。`Origin` が付いていて、許す `Origin` の一覧に無い |
| `404` | そのジョブが無い（受け付けていない・常駐サービスを再起動した・件数を超えて捨てた） |

成功は `200`。

[インターフェース定義](https://github.com/shuhei1101/voice-paste/blob/develop/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/%E5%B8%B8%E9%A7%90%E3%82%A2%E3%83%97%E3%83%AA/%E6%96%87%E5%AD%97%E8%B5%B7%E3%81%93%E3%81%97%E3%81%AE%E7%B5%90%E6%9E%9C%E3%82%92%E8%BF%94%E3%81%99.py.yaml)
