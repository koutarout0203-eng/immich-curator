# Immich Curator

Status: Active
Version: 0.2.0
Started: 2026-08-15

## Purpose

ImmichのTimelineに残っているAssetを日時でEvent化し、Apple PhotosのMemoriesに近い「思い出候補」を生成する独立サービスです。v0.1は候補JSONを生成するだけで、写真、Immich Asset、Albumを変更しません。

```text
Immich API (visibility=timeline)
              |
              v
      Event grouping / selection
              |
              v
       /data/memories.json
```

標準フローはImmichだけを使います。PhotoPrism連携は検証用の任意コマンドとして残しますが、導入・実行に必須ではありません。

## Current scope

- Immich `/api/search/metadata`から`visibility=timeline`だけをページング取得
- 6時間以上の間隔をEvent境界として日時順にグループ化
- 3枚以上のEventから最大12枚の代表Assetを選択
- Favoriteを必ず優先し、残りをEvent全体から時間的に分散して選択
- Event期間、枚数、場所、Favorite数、代表Assetを上位50 MemoryまでJSON出力
- APIはGET/検索POSTだけを使用し、DBや写真Datasetをマウントしない

未実装: 画像内容に基づくBest Shot、類似判定、人物・ペットの重み付け、フィードバック学習、動画編集、Album作成、Archive、原本操作。

## Authentication

標準フローはImmichのCurator専用read-only API keyだけを使用します。PhotoPrism比較機能を使う場合に限り、`photos read` scopeのaccess tokenを追加します。

```sh
photoprism show scopes
photoprism auth add -n Curator -s "photos read"
```

表示されたtokenはTrueNASの環境変数へ直接設定し、ファイルやGitへ保存しません。

## Run locally

```powershell
$env:IMMICH_BASE_URL = 'http://immich.local:2283'
$env:IMMICH_API_KEY = 'secret'
python -m curator memories --output data/memories.json
```

接続確認だけを行う場合:

```powershell
python -m curator probe
```

## Review in Immich

Memory候補はJSONを直接読むのではなく、ImmichのレビューAlbumで写真として確認します。最初は必ずdry-runで、上位5 Eventから重複を除いた最大60 Assetを確認します。

```powershell
python -m curator review-album --input data/memories.json
```

計画の`asset_count`とAsset IDを確認後、明示的に適用します。

```powershell
python -m curator review-album --input data/memories.json --apply
```

作成または再利用する所有Album名は`Curator Memory Review`です。`--apply`直前にImmich Live APIから`visibility=timeline`を全件再取得し、過去snapshotに含まれていても現在Archive・TrashにあるAssetは除外します。適用後は全対象Assetの所属を再取得して検証します。この操作はAlbum所属だけを追加し、Asset visibility、Favorite、metadata、原本を変更しません。必要なImmich API key権限は`asset.read`、`album.read`、`album.create`、`albumAsset.create`です。

## Visual representative experiment

Event内の類似写真と明らかな技術的失敗を減らすため、Live Timelineの上位5 EventについてImmichのStable thumbnail endpointから`preview`だけを取得して解析します。

```powershell
python -m curator visual-memories --output data/visual-memories.json
```

解析内容:

- 64-bit differential hashと、全体・中央75%・中央50%のperceptual hashによるズーム耐性のある近似画像クラスタ
- 15秒以内の短時間撮影を内容にかかわらず1つのburstとして統合
- 2分以内に撮影された写真には緩めのpHash閾値を適用し、構図違いの連写を統合
- クラスタ内の全画像と比較し、画角が徐々に変化する連続撮影も連鎖的に統合
- エッジ分散による相対的な鮮明度
- 輝度、暗部率、明部率による露出ペナルティ
- 類似クラスタ内ではFavoriteを最優先し、その次にtechnical scoreを使用
- Immichの既存顔認識結果から各Eventで人物写真を最大2枚優先
- 4×4の色・明暗構成を比較し、人物・景色・食事など異なる場面が混ざるよう多様性を優先
- Favoriteは弱い補助点とし、各Eventから最大8枚を選択

元画像は取得せず、previewはメモリ上だけで処理して保存しません。これは美的評価ではなく、ぼけ・極端な露出・近似画像を減らすための実験的な技術スコアです。生成後は、別名のReview Albumとして比較します。

```powershell
python -m curator review-album `
  --input data/visual-memories.json `
  --name "Curator Visual Review" `
  --apply
```

## Immutable trip candidate albums

GPS付きTimeline写真から推定ホームより50km以上離れた位置アンカーを抽出し、36時間以内に連続するアンカーを旅行候補としてまとめます。同じ旅行日内のGPSなしカメラ写真も含めますが、写真のEXIF・GPS・日時は変更しません。

旅行判定の前に、半年ごとのホーム候補を生成します。

```powershell
python -m curator home-candidates --output data/home-candidates.json
```

各約10kmセルを、写真枚数ではなく異なる撮影日数、登場月数、夜間・早朝の撮影日数で順位付けします。半年ごとの上位候補と代替候補を残し、25km以内で連続する首位候補を時期別の居住地候補へ統合します。旅行先で同日に大量撮影しても1撮影日として数えます。各セル内のImmich既存`city / state / country`最頻値を住所ラベルとして表示します。結果は旅行判定へ自動適用されないため、引越し時期と場所を人が確認します。

4月など四半期境界の引越しを詳しく確認する場合は3か月窓で生成します。

```powershell
python -m curator home-candidates `
  --output data/home-candidates-3m.json `
  --window-months 3
```

```powershell
python -m curator trip-candidates --output data/trips.json
```

ホームは最頻出の約10km GPSセルから推定します。推定が誤っている場合だけ、正しい座標を明示して再生成します。

```powershell
python -m curator trip-candidates `
  --output data/trips.json `
  --home-lat 35.0000 `
  --home-lon 139.0000
```

GPSなし写真には、最寄りGPS写真まで30分以内を`high`、6時間以内を`medium`、それ以外の旅行日内を`low`として記録します。JSON内の`trip_id`を確認して、まずdry-runします。

```powershell
python -m curator trip-album `
  --input data/trips.json `
  --trip-id TRIP_ID
```

確認後だけAlbumを作成します。

```powershell
python -m curator trip-album `
  --input data/trips.json `
  --trip-id TRIP_ID `
  --apply
```

作成時にはLive Timelineを再取得し、現在Timeline外のAssetを除外します。同名Albumが存在する場合は更新せずエラーにし、作成済み旅行AlbumをCuratorが自動変更しない規約とします。

Thumbnail取得にはImmich API keyの`asset.view`権限も必要です。

## TrueNAS

`compose.example.yaml`はCustom App相当の雛形です。Curatorには写真DatasetやImmich DBをマウントしません。書き込み可能領域は結果保存用`/data`だけです。

初回は`curator probe`で両APIを確認し、その後`curator snapshot`を一度だけ実行します。v0.1は常駐スケジュールや自動更新を持ちません。

## Output contract

トップレベルに`generated_at`、`policy`、`counts`、`memories`を出力します。各MemoryにはEvent期間、Asset数、Favorite数、代表Asset IDと日時を含めます。token、API key、元画像、サムネイルは保存しません。

`snapshot`コマンドはPhotoPrism比較実験用として残しています。照合時はImmichの`/data/`とPhotoPrismの`/photoprism/originals/`を除去した完全な相対パスだけを使い、ファイル名だけの曖昧な一致は許可しません。
