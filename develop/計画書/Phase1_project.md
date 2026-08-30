# Phase1_project

## STATUS

このファイルは `NASfiles_manage` の Phase 1 をCodexに実装させるための正式仕様である。

Phase 1より後の機能を先回りして実装しないこと。

---

# 1. システム境界

`NASfiles_manage` と `SITE_Source` は別システムとして分離する。

正式配置:

```text
Original_Systems/
├─ NASfiles_manage/
│  ├─ Program/
│  ├─ LOCAL_database/
│  └─ develop/
│     ├─ tests/
│     └─ 計画書/
│
└─ SITE_Source/
   ├─ @sample/
   ├─ <site_A>/
   ├─ <site_B>/
   └─ ...
```

役割:

```text
SITE_Source
= 外部サイトからファイルとサイト由来メタデータを取得するシステム

NASfiles_manage
= HDD/NAS上に存在するローカルファイルを管理するシステム
```

ただし両者は完全に無関係ではない。

将来:

```text
SITE_Source
↓
ファイルをダウンロード
↓
HDD/NASへ保存
↓
NASfiles_manageが管理対象として登録
```

さらに将来、ローカルファイルから:

```text
元URL
元サイト
サイト側アイテムID
SITE_Source側DB
```

へ辿れる連携を追加する可能性がある。

Phase 1ではこの連携を実装しない。

---

# 2. 現在の前提

将来はNASとミニPCを使用する予定だが、**Phase 1実装時点ではNASも本番用外付けHDDも接続・利用できる状態でなくてよい。**

Phase 1は、本番ストレージが存在しない状態でも作成・テストを進める。

Codexは以下の方法で実装・テストすること。

```text
Codex
↓
一時テストフォルダを作成
↓
小さな画像・動画・音声のテストファイルを使用
↓
DB作成・収集・再走査・重複検出をテスト
```

本番の外付けHDDまたは将来NASが接続された後、ユーザーが管理対象ルートを設定し、Codexとは独立して本番収集プログラムを実行する。

Codexは本番メディア全件を読み込む必要はない。

---

# 3. 現在と将来の役割

現在:

```text
ノートPC
└─ Original_Systems/
   ├─ NASfiles_manage/
   │  ├─ Program/
   │  ├─ LOCAL_database/
   │  └─ develop/
   │     ├─ tests/
   │     └─ 計画書/
   │
   └─ SITE_Source/
      └─ 別システム

本番ストレージ
└─ 現時点では未接続でもよい
```

将来:

```text
ミニPC
└─ Original_Systems/
   ├─ NASfiles_manage/
   │  ├─ Program/
   │  └─ LOCAL_database/
   │
   └─ SITE_Source/

NAS
└─ 実際の動画・画像・音楽コレクション
```

実ファイルは通常のファイルとしてExplorer等から直接閲覧・操作できる状態を維持する。

---

# 4. NASfiles_manage 正式ディレクトリ構造

```text
Original_Systems/
└─ NASfiles_manage/
   ├─ Program/
   │  ├─ local_data_collector.py
   │  ├─ duplicate_ejector.py
   │  └─ excluded_folder_loader.py
   ├─ LOCAL_database/
   │  └─ local_files.db
   └─ develop/
      ├─ tests/
      │  └─ test_phase1.py
      └─ 計画書/
```

Phase 1のプログラムは必ず次へ置く。

```text
Original_Systems/NASfiles_manage/Program/
```

DBは必ず次へ置く。

```text
Original_Systems/NASfiles_manage/LOCAL_database/
```

実メディア保存用HDD/NASへ、プログラムやDBを置かない。

---

# 5. Phase 1の目的

Phase 1の目的は次の3点。

```text
1. ローカルメディアファイルの台帳DBを作る
2. 現在存在する完全重複ファイルの初期整理を可能にする
3. 個別管理したくないフォルダを、内部ファイルではなくフォルダ1個の管理単位として扱えるようにする
```

Phase 1では以下を扱わない。

```text
SITE_Sourceとの接続
サイト由来メタデータ
元URL
ローカルタグ
評価
お気に入り
サムネイル管理
検索GUI
タグ編集GUI
完成版GUI
```

---

# 6. 管理対象

通常の個別ファイル管理対象:

```text
画像
動画
音楽・音声
```

通常の個別管理対象外:

```text
プログラム
文書
アーカイブ
その他一般ファイル
```

通常ファイルの管理対象判定は拡張子によって行う。

ただし、ユーザーが `excluded_folder_loader.py` に登録したフォルダは特別扱いする。

この「対象外フォルダ」は完全に無視するという意味ではない。

```text
通常の個別メディア走査から除外する
+
そのフォルダ自体を1つの管理単位としてDBへ登録する
```

例:

```text
E:\ゲーム\GameA\
├─ game.exe
├─ readme.md
├─ BGM\
│  ├─ battle.ogg
│  └─ title.mp3
├─ movies\
│  └─ intro.mp4
└─ assets\
   └─ logo.png
```

`E:\ゲーム\GameA\` を対象外フォルダへ登録した場合:

```text
内部の .ogg / .mp3 / .mp4 / .png 等
→ filesへ個別登録しない

E:\ゲーム\GameA\
→ folder_unitsへ1件だけ登録
```

用途例:

```text
ゲーム
アプリケーション一式
素材集
内部に大量のメディアを持つが、中身を個別管理したくないフォルダ
```

---

# 7. 本番管理対象ルート

本番の初期運用では、外付けHDD全体を対象とする予定。

```text
E:\
```

ただし、Phase 1実装時にEドライブが存在しなくてもよい。

ルートパスは設定可能にし、コード内部へ強く固定しない。

将来はNAS共有パスへ変更できるようにする。

---

# 8. 走査除外

以下はシステム固定除外であり、完全に走査対象外とする。

```text
$RECYCLE.BIN
System Volume Information
```

これらは `folder_units` にも登録しない。

別枠で、ユーザーが `excluded_folder_loader.py` に登録した「対象外フォルダ」は:

```text
内部へ再帰しない
内部ファイルをfilesへ登録しない
フォルダ自体をfolder_unitsへ登録する
```

さらに:

```text
- シンボリックリンクを無制限に再帰しない
- ジャンクション/再解析ポイントを無制限に再帰しない
- ディレクトリループを作らない
- アクセス不能ディレクトリはログに残してスキップ
- 1件のエラーで全スキャンを停止しない
```

Hidden属性だけを理由に通常ユーザーデータを一律除外しない。

---

# 9. ファイル識別

個別メディアファイルと、対象外フォルダの管理IDは分ける。

## 9.1 file_id

各ローカル個別ファイルレコードにUUID v4を発行する。

```text
file_id = UUID v4
```

パス・ファイル名から生成しない。

## 9.2 SHA-256

個別ファイルは、ファイル内容全体からSHA-256を計算する。

用途:

```text
名前変更後の再識別
移動後の再識別
完全重複検出
```

SHA-256は小文字16進文字列として保存する。

SHA-256へUNIQUE制約を付けない。

## 9.3 path

パスは現在地であってIDではない。

## 9.4 folder_id

対象外フォルダにはUUID v4の `folder_id` を発行する。

```text
folder_id = UUID v4
```

Phase 1では、対象外フォルダ内部の全ファイルをハッシュしてフォルダfingerprintを作らない。

理由:

```text
個別走査を避ける目的に反する
ゲーム等の巨大フォルダで処理が重くなる
```

同一パスで再検出された場合は同じ `folder_id` を維持する。

Phase 1では、対象外フォルダのrename/moveを個別ファイルと同精度で追跡することは要求しない。

移動・改名された対象外フォルダは、旧レコードをmissing、新しいパスを新規folder unitとして扱ってよい。

---

# 10. ファイルを書き換えない

Phase 1の通常収集処理では次を禁止する。

```text
メディアファイル内部へのID書き込み
各ファイル横への.json/.id等のsidecar生成
自動リネーム
自動移動
自動削除
対象外フォルダ内部への管理用ファイル生成
```

例外は `duplicate_ejector.py` による明示的な重複排出のみ。

---

# 11. DB

DB:

```text
Original_Systems/NASfiles_manage/LOCAL_database/local_files.db
```

方式:

```text
SQLite
```

Phase 1テーブル:

```text
files
folder_units
file_types
storage_roots
scan_runs
```

---

# 12. files

```sql
CREATE TABLE files (
    file_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    extension TEXT NOT NULL,
    storage_root_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_at TEXT,
    status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
```

ルール:

```text
- media_type列を作らない
- filename列をPhase 1では作らない
- extensionには .jpg / .png / .mp4 等を保存
- extensionは小文字へ正規化
- relative_pathにはファイル名まで含む
- sha256はUNIQUEにしない
```

---

# 12.1 folder_units

ユーザーが対象外登録したフォルダを、内部ファイルではなく1個の管理単位として保存する。

```sql
CREATE TABLE folder_units (
    folder_id TEXT PRIMARY KEY,
    storage_root_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    modified_at TEXT,
    status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
```

ルール:

```text
1対象外フォルダ = 1レコード
内部ファイルをfilesへ個別登録しない
内部ファイル数を必須で数えない
内部総容量を必須で計算しない
内部ファイルSHA-256を計算しない
relative_pathはstorage rootからの相対パス
statusはpresent / missing
```

`folder_units` は「管理対象ストレージ内に存在する、ひとまとまりのフォルダ型管理単位」を表す。

---

# 13. file_types

```sql
CREATE TABLE file_types (
    extension TEXT PRIMARY KEY,
    file_type TEXT NOT NULL
);
```

`files` には拡張子だけを保存する。

広い分類が必要なときだけ `file_types` を参照する。

例:

```text
.png  -> image
.jpg  -> image
.mp4  -> video
.mkv  -> video
.mp3  -> audio
.flac -> audio
```

初期データは一般的な画像・動画・音声拡張子を広めに登録すること。

拡張子追加のたびにプログラム本体を書き換えなくてよい構造にする。

---

# 14. storage_roots

```sql
CREATE TABLE storage_roots (
    storage_root_id INTEGER PRIMARY KEY,
    name TEXT,
    root_path TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL
);
```

本番初期値の予定:

```text
name      = external_hdd
root_path = E:\
active    = 1
```

テスト時には一時ディレクトリを使用してよい。

---

# 15. scan_runs

```sql
CREATE TABLE scan_runs (
    scan_id INTEGER PRIMARY KEY,
    storage_root_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    files_seen INTEGER,
    new_files INTEGER,
    missing_files INTEGER,
    duplicate_files INTEGER,
    folder_units_seen INTEGER,
    new_folder_units INTEGER,
    missing_folder_units INTEGER,
    error_count INTEGER
);
```

status候補:

```text
running
success
failed
interrupted
```

---

# 16. local_data_collector.py

配置:

```text
Original_Systems/NASfiles_manage/Program/local_data_collector.py
```

役割:

```text
管理対象ルートを再帰走査
↓
固定システム除外を確認
↓
excluded_folder_loader.py の登録内容を確認
↓
対象外フォルダならfolder_unitsへ登録して内部へ入らない
↓
通常フォルダならfile_typesにある拡張子だけ対象
↓
SHA-256
↓
UUID
↓
local_files.dbへ登録/更新
```

対象外フォルダを検出した時点で、そのディレクトリ内部への再帰を停止する。

対象外フォルダ内部については:

```text
ファイル列挙しない
SHA-256計算しない
filesへ登録しない
重複検出しない
```

1個別ファイルまたは1folder unitごとにDBへ確定する。

巨大動画をメモリへ丸ごと読み込まない。

SHA-256は分割読み込みで計算する。

---

# 16.1 excluded_folder_loader.py

配置:

```text
Original_Systems/NASfiles_manage/Program/excluded_folder_loader.py
```

これは対象外フォルダ設定を読み込む専用Pythonプログラム/モジュールとする。

ユーザーは、このファイル内の明示された設定領域へ対象外フォルダパスを書く。

概念例:

```python
EXCLUDED_FOLDERS = [
    r"E:\ゲーム\GameA",
    r"E:\ゲーム\GameB",
]
```

設定領域と処理領域を明確に分けること。

`local_data_collector.py` はこのプログラムから対象外フォルダ一覧を取得する。

単独実行した場合は、登録パスの確認・検証結果を表示できるようにしてよい。

最低限の検証:

```text
空パスを拒否/警告
同一パス重複を整理
対象storage root配下か確認
存在しないパスを警告
親と子の両方が登録された場合は警告
```

親フォルダが対象外なら、その配下の子フォルダはすでに個別走査されない。

---

# 17. 初回収集

```text
1. 対象ルートへアクセス可能か確認
2. excluded_folder_loader.pyから対象外フォルダ一覧を取得・検証
3. scan_runs開始
4. ディレクトリ走査
5. 固定システム除外をスキップ
6. 対象外登録フォルダならfolder_unitsへ登録し、内部へ入らない
7. 通常領域では対象拡張子だけ処理
8. SHA-256計算
9. UUID v4発行
10. filesへ登録
11. 1管理単位ごとにcommit
12. エラーはログに記録し可能な限り続行
13. scan_runs完了
```

---

# 18. 再走査

通常個別ファイルについて、変更がないファイルを毎回全件再ハッシュしない。

まず:

```text
既存パス
サイズ
更新日時
```

等で比較する。

必要な場合のみSHA-256を再計算する。

対象:

```text
新規
移動候補
改名候補
変更候補
曖昧ケース
```

対象外フォルダについて:

```text
同一relative_pathを再検出
→ 同じfolder_idを維持
→ status = present
→ last_seen_at更新

登録済み対象外フォルダが見つからない
→ status = missing

新しい対象外フォルダ
→ 新しいfolder_idを発行
```

対象外フォルダ内部は再走査しない。

---

# 19. 移動・改名

旧パスが消え、新しい未知パスが現れた場合:

```text
新ファイルのSHA-256計算
↓
同一SHA-256のmissingレコード確認
↓
安全に一意と判断可能
↓
同じfile_idを維持
↓
relative_path更新
↓
status = present
```

同一SHA-256候補が複数あり判断不能なら勝手に推測しない。

---

# 20. missing

通常の再走査で見つからない場合:

```text
files.status = missing
```

対象外フォルダが見つからない場合:

```text
folder_units.status = missing
```

どちらも即DELETEしない。

ただし管理対象ルートそのものへアクセスできない場合は、全件missingへ変更しない。

スキャン失敗として扱う。

---

# 21. 完全重複

完全重複:

```text
files.sha256 が同一
```

必要に応じてsize_bytesも確認する。

同名だけでは重複ではない。

`folder_units` はPhase 1の重複検出対象外。

対象外フォルダ内部のファイルも重複検出対象外。

---

# 22. duplicate_ejector.py

配置:

```text
Original_Systems/NASfiles_manage/Program/duplicate_ejector.py
```

役割:

```text
local_files.db
↓
filesテーブル内で同じSHA-256が2件以上あるpresentファイルを検出
↓
その重複グループの実ファイルを全部排出
```

`folder_units` は処理しない。

対象外フォルダ内部のファイルも処理しない。

どちらを残すかプログラムは決めない。

---

# 23. 重複排出先

Windowsの現在ユーザーのDownloadsを解決し、

```text
Downloads/
└─ 重複ダウンロード/
```

へ排出する。

Windowsユーザー名を固定しない。

---

# 24. 重複排出安全処理

HDD -> Downloadsは別ドライブになる可能性がある。

必須手順:

```text
コピー
↓
コピー先サイズ検証
↓
コピー先SHA-256再計算
↓
元SHA-256と一致確認
↓
初めて元ファイル削除
```

検証失敗時は元ファイルを削除しない。

---

# 25. 名前衝突

排出先で上書き禁止。

例:

```text
DUP000001_01__a.jpg
DUP000001_02__a.jpg
```

---

# 26. 重複レポート

```text
Downloads/重複ダウンロード/duplicate_report_YYYYMMDD_HHMMSS.csv
```

列:

```text
duplicate_group
file_id
sha256
original_path
ejected_path
size_bytes
result
```

---

# 27. 重複排出後DB

次の全条件を満たした場合のみ、初期整理専用例外としてfiles行を削除してよい。

```text
コピー成功
サイズ一致
SHA-256一致
元ファイル削除成功
```

通常のmissing処理ではDB行を削除しない。

ユーザーが重複を手動整理し、残す1ファイルを本番ストレージへ戻した後、`local_data_collector.py` を再実行する。

戻したファイルには新しいUUIDを発行する。

---

# 28. SITE_Sourceとの将来連携

`SITE_Source` は `NASfiles_manage` の内部フォルダではない。

正式位置:

```text
Original_Systems/SITE_Source/
```

ただし `SITE_Source` がダウンロードしたファイルは、HDD/NASへ保存された時点で `NASfiles_manage` の管理対象になり得る。

将来的には、例えば:

```text
LOCAL_database.files
↓
file_sources
↓
source_url
source_system
site_item_id
↓
Original_Systems/SITE_Source/<site>/ のDB
```

という接続を持たせる可能性がある。

目的:

```text
ローカルファイル
↓
どこから取得したか
↓
元URL
↓
元サイトの投稿
↓
サイト側metadata
```

を辿れるようにすること。

Phase 1では未実装。

`files` テーブルへsource URLを直接追加しない。

---

# 29. GUI

Phase 1では本格GUI不要。

CLIでよい。

将来GUIから呼び出し可能にしやすいよう、可能なら処理本体とCLI入口を分離する。

---

# 30. Codex実行範囲

Codexが行う:

```text
DB初期化実装
local_data_collector.py実装
duplicate_ejector.py実装
excluded_folder_loader.py実装
自動テスト
一時テストフォルダによる検証
```

Codexが行わない:

```text
本番HDD/NAS全件走査
本番コレクション全件SHA-256
本番重複排出
SITE_Sourceの実装変更
```

**本番ストレージが今存在・接続していなくてもPhase 1実装を完了できること。**

必須テスト:

```text
1. 通常領域の.jpg/.mp4/.mp3 → filesへ個別登録
2. 通常領域の.exe/.md → filesへ登録しない
3. 対象外GameA内の.png/.ogg/.mp4等 → filesへ0件
4. GameA自体 → folder_unitsへ1件
5. 対象外フォルダ再走査 → folder_id維持
6. 対象外フォルダ不在 → folder_units.status = missing
7. 対象外親フォルダ配下へ再帰しない
8. 存在しない対象外設定 → 警告
9. 通常ファイル重複 → duplicate_ejector対象
10. folder_units → duplicate_ejector対象外
```

---

# 31. Phase 1完了条件

```text
[ ] 本番HDD/NASなしでテスト可能
[ ] SQLite DBを作成可能
[ ] files作成
[ ] folder_units作成
[ ] file_types作成
[ ] storage_roots作成
[ ] scan_runs作成
[ ] excluded_folder_loader.py作成
[ ] ユーザーがPython設定領域へ対象外フォルダパスを書ける
[ ] collectorが対象外フォルダ一覧を読み込める
[ ] 対象外フォルダ内部へ再帰しない
[ ] 対象外フォルダ内部のメディアをfilesへ登録しない
[ ] 対象外フォルダ自体をfolder_unitsへ1件登録
[ ] folder_unitsのpresent/missing管理
[ ] テストルートを設定可能
[ ] 将来E:\を設定可能
[ ] 将来NASパスへ変更可能
[ ] System Volume Information除外
[ ] $RECYCLE.BIN除外
[ ] 再解析ポイントループ防止
[ ] 通常領域では対象メディアのみ登録
[ ] extensionをfilesへ保存
[ ] media_typeをfilesへ保存しない
[ ] UUID v4
[ ] SHA-256分割読み込み
[ ] 1管理単位ずつDB確定
[ ] 再走査可能
[ ] 個別ファイル改名/移動再認識
[ ] missing保持
[ ] rootアクセス不能を全件missingと誤認しない
[ ] 重複検出
[ ] 重複全件をDownloads/重複ダウンロードへ排出可能
[ ] folder_unitsは重複排出しない
[ ] 排出前後検証
[ ] CSVレポート
[ ] SITE_Sourceへアクセスしない
[ ] source連携未実装
[ ] タグ未実装
[ ] 評価未実装
[ ] 本格GUI未実装
```

---

# 32. 禁止事項

```text
- 本番ストレージがないことを理由に実装を停止しない
- プログラムをHDD/NASへ置かない
- DBをHDD/NASへ置かない
- pathを個別ファイル主キーにしない
- filenameを主キーにしない
- sha256をUNIQUEにしない
- filesへmedia_typeを追加しない
- filesへsource_urlを追加しない
- sidecarを大量生成しない
- メディア内部へIDを書かない
- 対象外フォルダ内部へ管理用ファイルを書かない
- 対象外フォルダ内部のメディアをfilesへ登録しない
- 対象外フォルダを完全無視してDBに何も残さない
- folder_unitsをduplicate_ejectorで排出しない
- SITE_SourceをNASfiles_manage内部へ戻さない
- SITE_Sourceのコード/DBへPhase 1からアクセスしない
- Phase 2以降を実装しない
- 重複のkeeperを自動決定しない
- コピー検証前に元を削除しない
```

Phase 1完了後、一度停止して次の指示を待つこと。

---
