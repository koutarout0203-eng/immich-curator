# Immich Curator

Status: Active
Version: 0.1.0
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

## TrueNAS

`compose.example.yaml`はCustom App相当の雛形です。Curatorには写真DatasetやImmich DBをマウントしません。書き込み可能領域は結果保存用`/data`だけです。

初回は`curator probe`で両APIを確認し、その後`curator snapshot`を一度だけ実行します。v0.1は常駐スケジュールや自動更新を持ちません。

## Output contract

トップレベルに`generated_at`、`policy`、`counts`、`memories`を出力します。各MemoryにはEvent期間、Asset数、Favorite数、代表Asset IDと日時を含めます。token、API key、元画像、サムネイルは保存しません。

`snapshot`コマンドはPhotoPrism比較実験用として残しています。照合時はImmichの`/data/`とPhotoPrismの`/photoprism/originals/`を除去した完全な相対パスだけを使い、ファイル名だけの曖昧な一致は許可しません。
