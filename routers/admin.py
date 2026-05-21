from fastapi import APIRouter
import pandas as pd
from db import get_db_connection

router = APIRouter()

@router.get("/api/admin/import-merrec")
def import_merrec_to_cloud_sql():
    print("⏳ クラウド上で1000件のデータを検証中...")
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM items")
            row_count = cursor.fetchone()
            if row_count and row_count["cnt"] >= 1000:
                connection.close()
                return {"status": "success", "message": "💡 すでにデータが存在するためインポートをスキップしました。"}

        preset_images = [
            "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1544816155-12df9643f363?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=600&auto=format&fit=crop"
        ]

        url = "https://huggingface.co/datasets/mercari-us/merrec/resolve/main/20230501/000000000000.parquet"
        df = pd.read_parquet(url, engine="pyarrow")
        
        df_cleaned = df.dropna(subset=['name', 'c0_name', 'c1_name']).copy()
        text_for_filter = (df_cleaned['name'] + " " + df_cleaned['c0_name'] + " " + df_cleaned['c1_name']).str.lower()
        demo_keywords = ["men", "sneakers", "shoes", "bag", "jewelry", "necklace", "gold", "watch"]
        filter_mask = text_for_filter.apply(lambda x: any(kw in x for kw in demo_keywords))
        
        df_prioritized = pd.concat([df_cleaned[filter_mask], df_cleaned[~filter_mask]])
        unique_items = df_prioritized.drop_duplicates(subset=['item_id']).copy()

        inserted_count = 0
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("DELETE FROM purchases;")
            cursor.execute("DELETE FROM items WHERE seller_id = 1;")

            img_idx = 0
            for _, row in unique_items.head(1000).iterrows():
                raw_brand = str(row['brand_name']).strip() if pd.notna(row['brand_name']) else ""
                brand = raw_brand if raw_brand and raw_brand.lower() != "nan" else "ノーブランド"
                c0 = str(row['c0_name'])
                c1 = str(row['c1_name'])
                c2 = str(row['c2_name']) if pd.notna(row['c2_name']) else ""
                
                description = f"【カテゴリ】{c0} > {c1} > {c2}\n【ブランド】{brand}\n【商品の状態】{row['item_condition_name']}"
                
                # 💡 🆕 新設された tags, seller_nickname, shipping_days も一緒に初期データとして流し込みます！
                sql = """
                    INSERT INTO items (name, description, price, image_url, seller_id, status, tags, seller_nickname, shipping_days)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                raw_price = row['price'] if pd.notna(row['price']) else 10
                price = int(raw_price * 150) if raw_price > 0 else 1500
                image_url = preset_images[img_idx % len(preset_images)]
                img_idx += 1
                
                # メルカリのカテゴリ(c0)をタグとして流用
                cursor.execute(sql, (
                    row['name'], 
                    description, 
                    price, 
                    image_url, 
                    1, 
                    "on_sale",
                    c0,            # tags
                    "メルカリ公式", # seller_nickname
                    "2〜3日で発送"  # shipping_days
                ))
                inserted_count += 1
                
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            connection.commit()
            
        connection.close()
        return {"status": "success", "message": f"🎉 デモ最適化データ格納完了しました！"}
    except Exception as e:
        return {"status": "error", "message": str(e)}