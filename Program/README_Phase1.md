# NASfiles_manage Phase 1 実行方法

Phase 1は、管理対象ファイルを書き換えずにSQLite台帳を作ります。実HDD/NASが未接続でも、任意のテストフォルダを`--root`へ指定して実行できます。

## 1. 対象外フォルダの設定

`excluded_folder_loader.py`冒頭の`USER SETTINGS`内だけを編集します。

```python
EXCLUDED_FOLDERS = [
    r"E:\Games\GameA",
]
```

設定確認:

```powershell
python Program\excluded_folder_loader.py --root "E:\"
```

対象外フォルダは内部を走査せず、フォルダ自体だけを`folder_units`へ登録します。

## 2. 収集

テストフォルダ:

```powershell
python Program\local_data_collector.py --root "C:\path\to\test_media" --name test
```

将来の外付けHDD:

```powershell
python Program\local_data_collector.py --root "E:\" --name external_hdd
```

DBは既定で`LOCAL_database/local_files.db`、ログは`Program/logs/local_data_collector.log`へ作成されます。アクセスできないルートを指定した場合、そのルートの既存レコードを一括で`missing`にはしません。

## 3. 重複排出

まず削除なしで対象を確認できます。

```powershell
python Program\duplicate_ejector.py --dry-run
```

実行時は、同一SHA-256グループのファイルを1件残すのではなく、グループ内の全ファイルを現在ユーザーの`Downloads/重複ダウンロード`へ排出します。

```powershell
python Program\duplicate_ejector.py
```

各ファイルはコピー先のサイズとSHA-256、および削除直前の元ファイルSHA-256を検証してから元を削除します。成功した行だけDBから削除し、結果を`duplicate_report_YYYYMMDD_HHMMSS.csv`へ記録します。排出後、手動整理して残す1ファイルをストレージへ戻し、収集を再実行してください。

## 4. 自動テスト

```powershell
python -m unittest discover -s develop\tests -v
```
