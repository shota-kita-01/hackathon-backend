import pandas as pd
import pymysql
# 💡 main.py にある接続関数をそのまま再利用して安全に Cloud SQL に繋ぎます
from main import get_db_connection

def import_data():
    print("⏳ real_merrec_sample.csv から商品データを抽出中...")
    
    # 1. 保存した実データを読み込む
    df = pd.read_parquet("https://huggingface.co/datasets/mercari-us/merrec/resolve/main/20230501/000000000000.parquet", engine="pyarrow")
    df_sampled = df.head(10000) # 最初の1万行
    
    # 2. 行動ログから「ユニークな商品（重複なし）」だけを抽出する（約数百〜数千件になります）
    # カラム名を現在のアプリのデータベース仕様に合わせます
    unique_items = df_sampled.drop_duplicates(subset=['item_id']).copy()
    
    print(f"🎯 重複を除去し、{len(unique_items)} 件のユニークな商品を特定しました。")
    print("⏳ Cloud SQL へのインポートを開始します...")
    
    connection = get_db_connection()
    inserted_count = 0
    
    try:
        with connection.cursor() as cursor:
            # 💡 データベースが爆発しないよう、まずはデモ用に先頭100件を流し込みます
            for _, row in unique_items.head(100).iterrows():
                # MerRecには商品説明文（description）がないので、カテゴリやブランドを合体させてリッチな説明文を自動生成！
                brand = row['brand_name'] if row['brand_name'] else "ノーブランド"
                c2 = row['c2_name'] if row['c2_name'] else ""
                description = f"【カテゴリ】{row['c0_name']} > {row['c1_name']} > {c2}\n【ブランド】{brand}\n【商品の状態】{row['item_condition_name']}"
                
                # 既存のテーブル構造にマッピング
                # seller_id はシステム初期データ用として、仮に「1」にしておきます
                sql = """
                    INSERT INTO items (name, description, price, image_url, seller_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                
                # 価格が0円の場合は、それっぽいダミー価格（1500円など）にする安全弁
                price = int(row['price']) if row['price'] and row['price'] > 0 else 1500
                
                cursor.execute(sql, (
                    row['name'],
                    description,
                    price,
                    "https://example.com/images/default.jpg", # 画像はダミー
                    1, # seller_id (1)
                    "on_sale" # status
                ))
                inserted_count += 1
                
            # 変更を確定
            connection.commit()
            print(f"🎉 【大成功】Cloud SQL へ本物のメルカリデータを {inserted_count} 件インポートしました！")
            
    except Exception as e:
        print(f"❌ インポート中にエラーが発生しました: {e}")
        connection.rollback()
    finally:
        connection.close()

if __name__ == "__main__":
    import_data()