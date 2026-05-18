import os
import pandas as pd
from huggingface_hub import list_repo_files, hf_hub_url

def download_real_merrec():
    print("⏳ Hugging FaceからMerRecデータセットのファイル構成を調査中...")
    repo_id = "mercari-us/merrec"
    
    try:
        # 1. リポジトリ内のファイル一覧を動的に取得
        all_files = list_repo_files(repo_id=repo_id, repo_type="dataset")
        
        # 2. Parquetファイルを検索（20230501/xxxx.parquet のようなファイル）
        parquet_files = [f for f in all_files if f.endswith('.parquet')]
        
        if not parquet_files:
            print("❌ リポジトリ内にParquetファイルが見つかりませんでした。")
            return
            
        # 一番最初のParquetファイルをターゲットにする
        target_file = parquet_files[0]
        print(f"🎯 本物のデータファイルを発見しました: {target_file}")
        
        # 3. 正しいダウンロードURLを生成
        url = hf_hub_url(repo_id=repo_id, filename=target_file, repo_type="dataset")
        print(f"🔗 ダウンロードURL: {url}")
        
        print("⏳ 実データから最初の10,000行をサンプリング中（少し時間がかかる場合があります）...")
        
        # 4. データを読み込む
        # ※ 実データはユーザーの「行動シーケンス（ログ）」がメインの tabular 形式です
        df = pd.read_parquet(url, engine="pyarrow")
        df_sampled = df.head(10000)
        
        print("\n🎉 【大成功】本物のMerRecデータのサンプリングに成功しました！")
        print("-" * 50)
        print("📊 データのカラム構造（これがメルカリ本物のデータです！）:")
        print(df_sampled.info())
        print("-" * 50)
        
        print("\n💡 データの先頭3件を表示します：")
        print(df_sampled.head(3))
        
        # 📂 ローカルに保存
        output_path = "real_merrec_sample.csv"
        df_sampled.to_csv(output_path, index=False)
        print(f"\n💾 軽量化した本物データを '{output_path}' に保存しました！")
        
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        print("Hugging Faceへの接続状況や、ライブラリのバージョンを確認してください。")

if __name__ == "__main__":
    download_real_merrec()