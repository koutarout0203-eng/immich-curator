# Immich Curator

Status: Active
Version: 0.1.0
Started: 2026-08-15

## Purpose

ImmichのTimelineに残っているAssetと、PhotoPrismの解析結果を読み取り専用APIで照合する独立サービスです。v0.1は候補データのJSON snapshotを生成するだけで、写真、Immich Asset、Album、PhotoPrism Indexを変更しません。

```text
Immich API (visibility=timeline) ─┐
                                  ├─ Curator ─> /data/candidates.json
PhotoPrism API (photos:read) ─────┘
```

照合キーは双方のoriginal relative pathです。Immichの`/data/`とPhotoPrismの`/photoprism/originals/`を除去して比較し、ファイル名だけの曖昧な照合はしません。

## Current scope

- Immich `/api/search/metadata`から`visibility=timeline`だけをページング取得
- PhotoPrism `/api/v1/photos`を`merged=true`でページング取得
- 厳密な相対パス一致による照合
- matched / Immich unmatched / PhotoPrism unmatched件数と候補metadataをJSON出力
- APIはGET/検索POSTだけを使用し、DBや写真Datasetをマウントしない

未実装: Best Shot score、類似判定、顔クラスタ評価、動画解析、Album作成、Archive、原本操作。

## Authentication

ImmichではCurator専用のread-only API keyを使用します。PhotoPrismでは`photos read` scopeのaccess tokenを発行します。

```sh
photoprism show scopes
photoprism auth add -n Curator -s "photos read"
```

表示されたtokenはTrueNASの環境変数へ直接設定し、ファイルやGitへ保存しません。

## Run locally

```powershell
$env:IMMICH_BASE_URL = 'http://immich.local:2283'
$env:IMMICH_API_KEY = 'secret'
$env:PHOTOPRISM_BASE_URL = 'http://192.168.14.37:20800'
$env:PHOTOPRISM_TOKEN = 'secret'
python -m curator snapshot --output data/candidates.json
```

接続確認だけを行う場合:

```powershell
python -m curator probe
```

## TrueNAS

`compose.example.yaml`はCustom App相当の雛形です。Curatorには写真Dataset、Immich DB、PhotoPrism DBをマウントしません。書き込み可能領域は結果保存用`/data`だけです。

初回は`curator probe`で両APIを確認し、その後`curator snapshot`を一度だけ実行します。v0.1は常駐スケジュールや自動更新を持ちません。

## Output contract

トップレベルに`generated_at`、`counts`、`candidates`を出力します。各候補にはImmich Asset ID、正規化済み相対パス、Immich metadata、PhotoPrism UIDと公開検索APIが返した解析metadataを含めます。token、API key、元画像、サムネイルは保存しません。

PhotoPrism REST APIには正式なdeprecation policyがないため、固定build `260728`を前提にclient contract testを維持します。
