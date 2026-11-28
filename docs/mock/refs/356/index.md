# #356 画面設計書を design-schemas/v12.0.0 で記載し直し、気づいた設計の漏れを実装とテストまで修正する

画面設計書を design-schemas/v12.0.0 で記載し直す途中で見つけた、見た目が変わる設計の修正のモック。
外の端末の文字起こしの画面の共有の CSS と JS は [assets/](./assets/) にあり、CSS は [refs/347](../347/assets/) までの assets に重ね、JS は [refs/347](../347/assets/app.js) のコピーで、コピーの表示だけを替えている。

| 画面 | 案リスト |
| --- | --- |
| 外の端末の文字起こしの画面 | [web-transcription / 356](../../pages/web-transcription/356/) |
| 設定画面 | [settings / 356](../../pages/settings/356/) |
