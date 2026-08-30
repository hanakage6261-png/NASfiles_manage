# NAS_manage全体計画書

## STATUS

このファイルは `Original_Systems/NASfiles_manage` 全体の長期構造をCodexへ伝えるための上位仕様である。

各Phaseはこの計画の下位仕様として扱う。

`SITE_Source` は別システムとして `Original_Systems` 直下に存在する。

---

# 1. システム全体の分離

正式構造:

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
NASfiles_manage
= HDD/NAS上のローカルファイル管理

SITE_Source
= 外部サイトからのファイル取得 + サイト由来metadata管理
```

両者は同一システムにはしない。

ただし将来的に連携する可能性が高い兄弟システムとして設計する。

---

# 2. NASfiles_manageの目的

`NASfiles_manage` は、HDD/NAS上に存在する動画・画像・音楽を管理する。

実ファイルは通常のファイルとして保持し、

```text
Explorerで閲覧
再生
コピー
移動
改名
削除
```

できる状態を維持する。

専用アプリ内へ閉じ込めない。

---

# 3. 実ファイルの流入元

NAS/HDD上の管理対象ファイルは複数経路から入る。

例:

```text
手動コピー
ブラウザからの通常ダウンロード
カメラ/端末からの移動
既存ローカルファイル
SITE_Sourceによるダウンロード
その他将来の取得経路
```

したがって、SITE_Source由来かどうかに関係なく、最終的にHDD/NASへ保存された管理対象メディアは `NASfiles_manage` の管理対象になり得る。

---

# 4. NASfiles_manage ディレクトリ

```text
Original_Systems/
└─ NASfiles_manage/
   ├─ Program/
   │  ├─ local_data_collector.py
   │  ├─ duplicate_ejector.py
   │  └─ 将来の共通ローカル管理program
   ├─ LOCAL_database/
   │  └─ local_files.db
   └─ develop/
      ├─ tests/
      └─ 計画書/
```

---

# 5. SITE_Source

`SITE_Source` はNASfiles_manage配下には置かない。

正式位置:

```text
Original_Systems/
└─ SITE_Source/
```

各サイトごとに独立フォルダを持つ。

例:

```text
SITE_Source/
├─ @sample/
├─ YouTube/
├─ NicoNico/
├─ SiteA/
└─ ...
```

各サイトフォルダには:

```text
サイト専用ダウンロードprogram
metadata収集program
サイト専用DB
必要な設定/補助ファイル
```

を置く。

---

# 6. SITE_SourceのサイトDB

原則:

```text
1サイト
↓
1サイトフォルダ
↓
1サイト専用データベースファイル
↓
必要なだけ複数テーブル
```

1サイト1テーブルではない。

サイトDBには例えば:

```text
videos
accounts
tags
video_tags
account_videos
playlists
...
```

を持てる。

ここではサイトから取得した情報を管理する。

ローカル実ファイルの現在位置は管理しない。

---

# 7. SITE_Sourceの目的

SITE_Sourceは単なるダウンローダー集ではない。

各サイトについて:

```text
ファイルを取得
+
サイト由来metadataを収集
+
サイト専用DBへ保存
```

する。

このmetadataは将来:

```text
ローカルファイルへのタグ付け補助
元サイトの再訪
元投稿の確認
投稿者確認
元サイトタグ参照
```

などに利用できる。

---

# 8. ダウンロード後のファイル

SITE_Sourceが取得したメディア本体を、SITE_Sourceフォルダ内へ長期保存しない。

流れ:

```text
SITE_Source
↓
ファイル取得
↓
現在: 外付けHDD
将来: NAS
↓
NASfiles_manageの管理対象
```

最終保存フォルダはサイト別ではなく、内容による分類を基本とする。

---

# 9. 最終フォルダ整理軸

例:

```text
二次元イラスト/
└─ 版権キャラクター/
   └─ ゼルダの伝説/
      └─ ゼルダ/
```

YouTube由来、ニコニコ由来等は最終保存場所の主要分類軸にしない。

元サイト情報はSITE_Source側DBおよび将来の接続情報で保持する。

---

# 10. LOCAL_database

`LOCAL_database` はローカル実ファイルの台帳。

現在:

```text
LOCAL_database/
└─ local_files.db
```

担当:

```text
ローカルfile_id
SHA-256
拡張子
現在位置
サイズ
更新日時
present/missing
将来のローカルタグ
将来の評価
将来のsource link
```

サイト固有metadataを直接混ぜない。

---

# 11. SITE_SourceとNASfiles_manageの将来連携

将来的には、NASfiles_manage側に `file_sources` のような接続情報を持つ可能性がある。

概念:

```text
LOCAL_database.files
↓
file_sources
├─ file_id
├─ source_system
├─ source_url
├─ site_name
└─ site_item_id
↓
Original_Systems/SITE_Source/<site>/ のDB
```

これにより:

```text
ローカル動画
↓
取得元URL
↓
元サイト
↓
元投稿
↓
投稿者 / タグ / 投稿日 / description
```

などへ辿れるようにする。

SITE_SourceとLOCAL_databaseを1つのDBへ統合する必要はない。

---

# 12. SITE_Source由来metadataの将来利用

将来的にはサイト側metadataをローカル整理の補助に利用できる。

例:

```text
サイト上のタグ
↓
ローカルタグ候補

投稿者情報
↓
作者/投稿者候補

元URL
↓
GUIの「元サイトを開く」
```

ただし、元サイトmetadataとユーザー独自ローカルタグは別データとして扱う。

---

# 13. ローカルタグ

将来LOCAL_database側へ、サイトから独立したユーザー用タグを持つ。

例:

```text
ゼルダ
二次創作
幻想的
青系
公式設定資料
お気に入り
```

既存フォルダ階層から初期タグを作る予定。

---

# 14. 横断検索

将来GUIから:

```text
評価 = 5
AND
タグ = アニメーション
```

等で検索し、取得元サイトに関係なくNAS/HDD上のローカルファイルを表示できるようにする。

---

# 15. GUI

最終的には:

```text
サムネイル
ローカルタグ編集
一括タグ編集
星評価
検索
元URL表示
元サイトを開く
SITE_Source metadata表示
重複確認
```

等を持つ可能性がある。

Phase 1では作り込まない。

---

# 16. フェーズ開発

仕様書名:

```text
Phase1_project
Phase2_project
Phase3_project
...
```

数字だけ変更する。

Phase 1:

```text
LOCAL_database基礎
ローカルファイル一括収集
完全重複初期整理
```

Phase 2以降は未決定。

---

# 17. SITE_Sourceとの境界原則

```text
SITE_Source
= 取得元について詳しい

NASfiles_manage
= 保存済みローカルファイルについて詳しい
```

接続は後から明示的に作る。

互いの内部DBを無秩序に直接書き換えない。

---

# 18. 設計原則

```text
- SITE_SourceとNASfiles_manageは別システム
- ただし取得結果はNASfiles_manageの管理対象になり得る
- 将来source linkで接続可能にする
- 実ファイルを専用システムに閉じ込めない
- 取得元サイトと最終ファイル配置を分離する
- LOCAL DBとサイトDBを分離する
- サイト固有コードはサイト単位で分離する
- NASメーカーに強く依存しない
- 小さなPhase単位で実装する
- 未決定事項を勝手に確定しない
```

---

# 19. 未決定

```text
Phase 2以降
ローカルタグ体系
評価体系
GUI技術
SITE_SourceからNAS/HDDへの正式受け入れフォルダ
file_sources具体スキーマ
site_item_id接続方式
元URL保存方式
SITE_Source完了通知方式
NAS導入後の正式パス
リアルタイム監視
バックアップ方式
```
