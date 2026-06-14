import json
import random
import pandas as pd
from datasets import load_dataset

# Hugging Face内部のバグった型キャスト処理を完全にバイパス！
import datasets.table
import datasets.iterable_dataset
bypass_lambda = lambda table, features: table
datasets.table.cast_table_to_features = bypass_lambda
datasets.iterable_dataset.cast_table_to_features = bypass_lambda

# Amazon Reviews からフリマ向きの商品を厳選（22カテゴリー）
CATEGORIES = [
    "All_Beauty", "Amazon_Fashion", "Appliances", "Automotive", "Beauty_and_Personal_Care",
    "Books", "CDs_and_Vinyl", "Cell_Phones_and_Accessories", "Clothing_Shoes_and_Jewelry", "Electronics",
    "Grocery_and_Gourmet_Food", "Handmade_Products", "Home_and_Kitchen", "Movies_and_TV", "Musical_Instruments",
    "Office_Products", "Patio_Lawn_and_Garden", "Pet_Supplies", "Sports_and_Outdoors", "Tools_and_Home_Improvement",
    "Toys_and_Games", "Video_Games"
]

SAMPLE_SIZE_META = 100
SAMPLE_SIZE_REVIEW = 500 

# 22カテゴリー別・高品質画像URLプール（各3枚ずつ厳選）
CATEGORY_IMAGE_POOLS = {
    "All_Beauty": [
        "https://images.unsplash.com/photo-1596462502278-27bfdc403348?w=600",
        "https://images.unsplash.com/photo-1612817288484-6f916006741a?w=600",
        "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=600"
    ],
    "Amazon_Fashion": [
        "https://images.unsplash.com/photo-1483985988355-763728e1935b?w=600",
        "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=600",
        "https://images.unsplash.com/photo-1479064555552-3ef4979f8908?w=600"
    ],
    "Appliances": [
        "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=600",
        "https://images.unsplash.com/photo-1574269909862-7e1d70bb8078?w=600",
        "https://images.unsplash.com/photo-1527018601619-a508a2be00cd?w=600"
    ],
    "Automotive": [
        "https://images.unsplash.com/photo-1486006920555-c77dce18193b?w=600",
        "https://images.unsplash.com/photo-1619642751034-765dfdf7c58e?w=600",
        "https://images.unsplash.com/photo-1563720223185-11003d516935?w=600"
    ],
    "Beauty_and_Personal_Care": [
        "https://images.unsplash.com/photo-1608248597481-496100c80836?w=600",
        "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=600",
        "https://images.unsplash.com/photo-1601049541289-9b1b7bbbfe19?w=600"
    ],
    "Books": [
        "https://images.unsplash.com/photo-1495446815901-a7297e633e8d?w=600",
        "https://images.unsplash.com/photo-1544947950-fa07a98d237f?w=600",
        "https://images.unsplash.com/photo-1512820790803-83ca734da794?w=600"
    ],
    "CDs_and_Vinyl": [
        "https://images.unsplash.com/photo-1539628399213-d6aa19c93074?w=600",
        "https://images.unsplash.com/photo-1603048588665-791ca8aea617?w=600",
        "https://images.unsplash.com/photo-1542208998-f6dbbb27a72f?w=600"
    ],
    "Cell_Phones_and_Accessories": [
        "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=600",
        "https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=600",
        "https://images.unsplash.com/photo-1580910051074-3eb694886505?w=600"
    ],
    "Clothing_Shoes_and_Jewelry": [
        "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600",
        "https://images.unsplash.com/photo-1539109136881-3be0616acf4b?w=600",
        "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=600"
    ],
    "Electronics": [
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600",
        "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=600",
        "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600"
    ],
    "Grocery_and_Gourmet_Food": [
        "https://images.unsplash.com/photo-1506084868230-bb9d95c24759?w=600",
        "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=600",
        "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?w=600"
    ],
    "Handmade_Products": [
        "https://images.unsplash.com/photo-1513519245088-0e12902e5a38?w=600",
        "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?w=600",
        "https://images.unsplash.com/photo-1561715276-a2d087060f1d?w=600"
    ],
    "Home_and_Kitchen": [
        "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?w=600",
        "https://images.unsplash.com/photo-1581428982868-e410dd047a90?w=600",
        "https://images.unsplash.com/photo-1534349762230-e0cadf78f5db?w=600"
    ],
    "Movies_and_TV": [
        "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=600",
        "https://images.unsplash.com/photo-1536440136628-849c177e76a1?w=600",
        "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?w=600"
    ],
    "Musical_Instruments": [
        "https://images.unsplash.com/photo-1511192336575-5a79af67a629?w=600",
        "https://images.unsplash.com/photo-1510915361894-db8b60106cb1?w=600",
        "https://images.unsplash.com/photo-1520523839897-bd0b52f945a0?w=600"
    ],
    "Office_Products": [
        "https://images.unsplash.com/photo-1586075010923-2dd4570fb338?w=600",
        "https://images.unsplash.com/photo-1562654501-a0ccc0fc3fb1?w=600",
        "https://images.unsplash.com/photo-1513151233558-d860c5398176?w=600"
    ],
    "Patio_Lawn_and_Garden": [
        "https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=600",
        "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=600",
        "https://images.unsplash.com/photo-1466692476868-aef1dfb1e735?w=600"
    ],
    "Pet_Supplies": [
        "https://images.unsplash.com/photo-1516734212186-a967f81ad0d7?w=600",
        "https://images.unsplash.com/photo-1541599540903-216a46cc1ad6?w=600",
        "https://images.unsplash.com/photo-1583511655857-d19b40a7a54e?w=600"
    ],
    "Sports_and_Outdoors": [
        "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=600",
        "https://images.unsplash.com/photo-1502904585520-fa4514c950bf?w=600",
        "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=600"
    ],
    "Tools_and_Home_Improvement": [
        "https://images.unsplash.com/photo-1504148455328-c376907d081c?w=600",
        "https://images.unsplash.com/photo-1534224039826-c7a0dea0e66a?w=600",
        "https://images.unsplash.com/photo-1581244277943-fe4a9c777189?w=600"
    ],
    "Toys_and_Games": [
        "https://images.unsplash.com/photo-1531651008558-ed1740375b39?w=600",
        "https://images.unsplash.com/photo-1558060370-d644479cb6f7?w=600",
        "https://images.unsplash.com/photo-1596461404969-9ae70f2830c1?w=600"
    ],
    "Video_Games": [
        "https://images.unsplash.com/photo-1605901309584-818e25960a8f?w=600",
        "https://images.unsplash.com/photo-1552820728-8b83bb6b773f?w=600",
        "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?w=600"
    ]
}

DEFAULT_IMAGES = [
    "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600"
]

print(f"全 {len(CATEGORIES)} ジャンルから、DB用と行動ログ用に分けてサンプリングを開始...")

db_items = []         
sampled_reviews = []  

for i, cat in enumerate(CATEGORIES):
    print(f"[{i+1}/{len(CATEGORIES)}] カテゴリ [{cat}] を処理中...")
    
    # 1. 商品情報のストリーミング
    try:
        meta_stream = load_dataset(
            "McAuley-Lab/Amazon-Reviews-2023", 
            f"raw_meta_{cat}", 
            split="full", 
            streaming=True,
            trust_remote_code=True
        )
        count = 0
        for item in meta_stream:
            if count >= SAMPLE_SIZE_META:
                break
            
            desc_list = item.get("description", [])
            desc_text = " ".join(desc_list) if isinstance(desc_list, list) else str(desc_list)
            
            p_asin = item.get("parent_asin")
            if not desc_text.strip() or not item.get("title") or not p_asin:
                continue
                
            raw_price = item.get("price")
            try:
                price = int(float(raw_price) * 150) if raw_price is not None else 2500
                if price <= 0: price = 2500
            except:
                price = 2500
            
            img_pool = CATEGORY_IMAGE_POOLS.get(cat, DEFAULT_IMAGES)
            chosen_image_url = random.choice(img_pool)
            
            db_items.append({
                "asin": p_asin,
                "name": item.get("title"),
                "ai_category": cat,
                "price": price,
                "description": desc_text[:500],
                "image_url": chosen_image_url
            })
                
            count += 1
    except Exception as e:
        print(f"   データ取得エラー [{cat}]: {e}")

    # 2. 行動ログのストリーミング ──
    try:
        review_stream = load_dataset(
            "McAuley-Lab/Amazon-Reviews-2023", 
            f"raw_review_{cat}", 
            split="full", 
            streaming=True,
            trust_remote_code=True
        )
        count = 0
        for rev in review_stream:
            if count >= SAMPLE_SIZE_REVIEW:
                break
            p_asin = rev.get("parent_asin")
            if not p_asin:
                continue
            sampled_reviews.append({
                "user_id": rev.get("user_id"),
                "asin": p_asin,
                "ai_category": cat,
                "timestamp": rev.get("timestamp")
            })
            count += 1
    except Exception as e:
        print(f"   レビューログ取得エラー [{cat}]: {e}")

# 3. それぞれのファイルに永続化
with open("items_for_db.json", "w", encoding="utf-8") as f:
    json.dump(db_items, f, ensure_ascii=False, indent=2)

df_reviews = pd.DataFrame(sampled_reviews)
df_reviews.to_csv("amazon_review_samples.csv", index=False, encoding="utf-8")

print("\n" + "="*50)
print(f"➔ DB・画面表示用データ : {len(db_items)} 件 (items_for_db.json)")
print(f"➔ 市場行動ログ (CSV)   : {len(df_reviews)} 件 (amazon_review_samples.csv)")
print("="*50)