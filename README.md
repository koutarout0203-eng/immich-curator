# Immich Curator

Status: Active
Version: 0.3.0
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
- Immich DBや写真Datasetをマウントせず、公式APIだけを使用
- 正式Trip Albumの一括作成、検証済み不足Assetのadditive補完、旧版Album候補の安全な抽出
- TrueNAS常駐`trip-worker`による週次再解析、72時間の確定待ち、多重起動防止、履歴保存

未実装: サジェスト用Webアプリ、採用・保留フィードバック、動画編集、LifeOS向け旅行Manifest連携。Archive、原本操作、自動削除は対象外です。

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

GPS付きTimeline写真から推定ホームより50km以上離れた位置アンカーを抽出し、36時間以内に連続するアンカーを旅行候補としてまとめます。旅行中に都市が変わっても分割せず、ホーム期間が切り替わる場合だけ分割します。単発のホームGPS写真は誤位置や日時ずれの可能性があるため帰宅判定に使いません。最初の遠方アンカー3時間前から最後の遠方アンカー3時間後だけを対象にし、出発前・帰宅後の自宅写真を抑えながらGPSなしカメラ写真も含めます。写真のEXIF・GPS・日時は変更しません。

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

確認した時期別ホーム候補を旅行判定へ入力します。撮影日時点で有効な生活拠点からの距離を使い、履歴にない期間は旅行候補を作りません。

```powershell
python -m curator trip-candidates `
  --output data/trips.json `
  --home-periods data/home-candidates-3m.json
```

互換用として単一ホームも指定できますが、引越しや長期滞在を含むライブラリでは時期別ホームを使用します。

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

既存候補Albumを変更せず修正版を比較する場合は、`--name`で別名を指定できます。

```powershell
python -m curator trip-album `
  --input data/trips.json `
  --trip-id TRIP_ID `
  --name "YYYY-MM-DD - Trip Candidate v2 - 場所" `
  --apply
```

作成時にはLive Timelineを再取得し、現在Timeline外のAssetを除外します。同名Albumが存在する場合は更新せずエラーにし、作成済み旅行AlbumをCuratorが自動変更しない規約とします。

旅行Album名は名前順でも日付順に並ぶよう、`YYYY-MM-DD - Trip Candidate - 場所`形式で生成します。確認後の確定名も`YYYY-MM-DD - Trip - 名前`形式を推奨します。

すべての候補を一括作成する場合も、最初はdry-runします。

```powershell
python -m curator trip-albums --input data/trips.json
```

確認後に`--apply`を付けます。一括作成では候補名の`Trip Candidate`を`Trip`へ変換し、`YYYY-MM-DD - Trip - 場所`の正式名で作成します。処理は再実行可能で、同名かつ同一内容のAlbumは`skipped_verified`、同名で内容が異なるAlbumは`conflict`として変更しません。各Albumを作成後に所属Assetを再取得して検証し、1件の失敗で残りを中断しません。

```powershell
python -m curator trip-albums `
  --input data/trips.json `
  --apply
```

新版で統合されたため不要になった旧版の正式Trip Albumは、まずdry-runで列挙します。旧Albumの全Assetが新版のちょうど1旅行に包含され、apply時の実Album所属が旧JSONと完全一致する場合だけAlbumコンテナを削除します。写真Assetは削除しません。

```powershell
python -m curator trip-albums-prune `
  --previous data/trips-v4.json `
  --current data/trips-v5.json

python -m curator trip-albums-prune `
  --previous data/trips-v4.json `
  --current data/trips-v5.json `
  --apply
```

既存の正式Albumが新しい候補の厳密な部分集合で、内容を新版へ補完すると明示的に判断した場合だけ、次のオプションで不足Assetを追加できます。既存Albumに新版外のAssetが1件でもある場合は`conflict`のまま変更せず、削除は行いません。

```powershell
python -m curator trip-albums `
  --input data/trips.json `
  --apply `
  --add-missing-to-conflicts
```

## Operational follow-ups

### 過去写真が後から追加された場合

- 既存Albumが新版の厳密な部分集合なら、`trip-worker`が不足Assetだけを追加する。
- 既存Albumに新版外のAssetがある場合は変更せず`conflict`として履歴へ残す。
- 30日より古く同名Albumがない候補は、自動作成せず`historical_review`として人の確認を待つ。
- GPSなし写真ではカメラ時刻ずれもあり得るため、日時だけで既存旅行へ自動追加しない。
- 実装時はAsset ID単位の差分、追加理由、位置推定信頼度を記録し、削除は行わない。

### Album生成の自動実行タイミング

- 既定は毎週日曜06:00 JST、旅行終了後72時間待機とする。
- API失敗は記録して次回再試行し、lockで多重実行を防止する。
- TrueNAS実機への配置、一回実行、再起動復帰、翌週実行の運用検証は未完了。

## Remaining roadmap

### 1. Deploy automatic Trip Albums on TrueNAS

- `v0.3.0`イメージをbuild・publishし、TrueNAS Custom Appへ配置する。
- 確認済みhome periodsを`/data/home-periods.json`として永続化する。
- `trip-worker --once`で既存109 Albumがskip検証され、削除0・conflict 0となることを確認する。
- 常駐後に次回実行時刻、再起動復帰、`/data/history/`を確認する。

### 2. Suggestion review app

- Curatorが生成したMemory候補を、JSONではなく写真中心のカードで比較・採用・保留できるTailnet限定Web UIにする。
- 主要操作は候補を開く、代表写真を比較する、Immich Review Albumを作る、保留する、の4つに絞る。
- 即時フィードバック、予測可能な戻る動線、ライト／ダーク、文字サイズ、reduced motion／transparency／contrastを設計条件にする。
- 初期版では写真・metadata・visibilityを変更せず、Album所属だけを明示操作で追加する。

### 3. LifeOS trip integration

- CuratorはImmichに近いTrueNAS側で解析を継続し、LifeOSへ写真原本やAPI keyを渡さない。
- LifeOSへ渡すのは、Trip ID、期間、代表地点、Immich Album ID、枚数、代表Asset参照を含むバージョン付き旅行Manifestとする。
- LifeOS側はManifestを読み取り、既存Travel PWAへ「写真Albumを開く」導線を提供する。編集の正本はImmich、旅行計画の正本はTravel APIとして分離する。
- Tailnet内通信、認証、再同期、削除伝播なし、バックアップ／復元を設計してからActiveにする。

## Trip worker

`v0.3.0`ではTrueNAS常駐用の`trip-worker`を利用できます。既定では毎週日曜06:00（指定タイムゾーン）にTimelineを再解析し、最後の遠方GPSアンカーから72時間以上経過した旅行だけを確定します。

- 新規の正式Trip Albumを作成します。
- 既存Albumが新版候補の厳密な部分集合の場合だけ、不足Assetを追加します。
- 既存Albumに新版外のAssetがある場合や結合・分割が変わった場合は`conflict`として記録します。
- Album、写真Asset、メタデータを自動削除しません。
- 30日より古く、同名の既存Albumもない候補は、過去写真追加による旅行名変更や結合の可能性があるため自動作成せず`historical_review`として記録します。日数は`--historical-review-days`で変更できます。
- `/data/trips-current.json`と`/data/trip-sync-latest.json`を原子的に更新し、各実行結果を`/data/history/`へ保存します。
- 同じ週次実行で`/data/visual-memories.json`とLifeOS向け`/data/trip-manifest.json`も更新します。preview画像は保存しません。
- `/data/trip-worker.lock`で多重実行を防止します。異常終了後12時間を超えたlockだけを次回起動時に回収します。

確認済みの`home-candidates-3m.json`を、TrueNASの永続化先へ`home-periods.json`として配置してください。秘密情報は含みません。

初回は常駐化せず、一回実行で検証します。

```powershell
python -m curator trip-worker `
  --home-periods data/home-candidates-3m.json `
  --data-dir data/trip-worker-test `
  --settle-hours 72 `
  --once
```

TrueNASでは`compose.example.yaml`のように`/data/home-periods.json`を使用します。スケジュールは`--weekday`（月曜=0、日曜=6）と`--time HH:MM`、タイムゾーンは`TZ`または`--timezone`で変更できます。

コンテナのrestart policyは`unless-stopped`とし、TrueNAS再起動後にもスケジューラを復帰させます。API失敗は実行結果へ記録して常駐ループを継続し、次週に再試行します。

## Suggestion review app

`suggestions-app`は`visual-memories.json`を写真中心のカードとして表示します。候補ごとに「Immichで確認」で専用Review Albumを作成するか、「あとで見る」として保留できます。判断結果は`/data/suggestion-feedback.json`へ原子的に保存します。

```powershell
$env:CURATOR_UI_USERNAME = 'curator'
$env:CURATOR_UI_PASSWORD = 'set-a-long-password'
$env:IMMICH_PUBLIC_URL = 'http://192.168.14.37:2283'
python -m curator suggestions-app `
  --input data/visual-memories.json `
  --feedback data/suggestion-feedback.json `
  --host 0.0.0.0 `
  --port 20810
```

非loopbackへbindする場合はBasic認証が必須です。TrueNASでは`compose.example.yaml`のworkerとwebを同じ永続`/data`へ接続します。一般インターネットへ公開せず、LANまたはTailnet内だけで使用してください。

## LifeOS Trip Manifest

週次workerは`/data/trip-manifest.json`を生成します。schema version、Trip ID、期間、代表地点、枚数、cover Asset ID、Immich Album ID・URLだけを含み、API keyや写真binaryは含みません。

```powershell
python -m curator trip-manifest `
  --input data/trips-v5.json `
  --output data/trip-manifest.json `
  --immich-url http://192.168.14.37:2283
```

LifeOSはこのManifestを読み取り専用で同期し、Travel PWAからImmich Albumを開く導線に利用します。Immich Albumと旅行計画を相互上書きせず、削除も伝播しません。

Thumbnail取得にはImmich API keyの`asset.view`権限も必要です。

## TrueNAS

`compose.example.yaml`はCustom App相当の雛形です。Curatorには写真DatasetやImmich DBをマウントしません。書き込み可能領域は結果保存用`/data`だけです。

GitHubへpush後、`v0.3.0`タグまたはActionsの手動実行で、同梱workflowが`ghcr.io/koutarout0203-eng/immich-curator:v0.3.0`と`latest`をbuild・publishします。手動実行では`image_tag`を`v0.3.0`にします。TrueNASでは再現性のため`latest`ではなくversioned tagを固定して使用します。

実機では専用Dataset `/mnt/tanico-nas/apps/immich-curator` を作り、コンテナUID/GID `10001:10001`が読み書きできるようにします。写真Dataset、Immich DB、Docker socketはマウントしません。確認済みの`data/home-candidates-3m.json`をDataset直下の`home-periods.json`として配置します。

`.env.example`を実機だけで`.env`へコピーし、Immich API keyとUI passwordを入力します。入力済み`.env`はGitへ追加しません。初回検証は常駐起動前に次の順で行います。

```bash
docker compose --env-file .env -f compose.example.yaml pull
docker compose --env-file .env -f compose.example.yaml run --rm curator-worker probe
docker compose --env-file .env -f compose.example.yaml run --rm curator-worker trip-worker \
  --home-periods /data/home-periods.json \
  --data-dir /data \
  --settle-hours 72 \
  --historical-review-days 30 \
  --once
```

`trip-sync-latest.json`で`failed=0`、既存Albumが`skipped_verified`、削除処理がないことを確認してから、`docker compose up -d`でworkerとWeb UIを常駐させます。Web UIは`http://192.168.14.37:20810`で、LANまたはTailnet内だけから使用します。

初回は上記の`probe`と`trip-worker --once`だけを実行し、結果確認後に常駐化します。PhotoPrism比較用の`snapshot`はTrueNAS常駐運用には不要です。

## Output contract

トップレベルに`generated_at`、`policy`、`counts`、`memories`を出力します。各MemoryにはEvent期間、Asset数、Favorite数、代表Asset IDと日時を含めます。token、API key、元画像、サムネイルは保存しません。

`snapshot`コマンドはPhotoPrism比較実験用として残しています。照合時はImmichの`/data/`とPhotoPrismの`/photoprism/originals/`を除去した完全な相対パスだけを使い、ファイル名だけの曖昧な一致は許可しません。
