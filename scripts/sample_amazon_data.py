import json
import pandas as pd
from datasets import load_dataset

# Amazon Reviews 2023 全33ジャンル
CATEGORIES = [
    "All_Beauty", "Amazon_Fashion", "Appliances", "Arts_Crafts_and_Sewing", "Automotive",
    "Baby_Products", "Beauty_and_Personal_Care", "Books", "CDs_and_Vinyl", "Cell_Phones_and_Accessories",
    "Clothing_Shoes_and_Jewelry", "Digital_Music", "Electronics", "Gift_Cards", "Grocery_and_Gourmet_Food",
    "Handmade_Products", "Health_and_Household", "Health_and_Personal_Care", "Home_and_Kitchen", "Industrial_and_Scientific",
    "Kindle_Store", "Magazine_Subscriptions", "Movies_and_TV", "Musical_Instruments", "Office_Products",
    "Patio_Lawn_and_Garden", "Pet_Supplies", "Software", "Sports_and_Outdoors", "Tools_and_Home_Improvement",
    "Toys_and_Games", "Video_Games", "Subscription_Boxes"
]

SAMPLE_SIZE_META = 100   
SAMPLE_SIZE_REVIEW = 200 

print(f"⏳ 【関心の分離】全 {len(CATEGORIES)} ジャンルから、DB用とリンク計算用に分けてサンプリングを開始します...")

# 📁 完全に分離する3つのデータコンテナ
db_items = []         # ① 明日Cloud SQLへ入れる、画面表示＆ベクトル化用のピュアな商品データ
network_links = []    # ② マルコフ連鎖の確率計算のためだけの、軽量なグラフ構造データ
sampled_reviews = []  # ③ トラフィックの熱量を測るための行動ログ（CSV用）

PRESET_IMAGES = [
    "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=600",
    "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600",
    "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600",
    "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=600",
    "https://images.unsplash.com/photo-1544816155-12df9643f363?w=600"
]

img_idx = 0

for cat in CATEGORIES:
    print(f"📦 [全33中] カテゴリ [{cat}] を処理中...")
    
    # ── 1. メタデータ（商品情報）のストリーミング ──
    try:
        meta_stream = load_dataset("McAuley-Lab/Amazon-Reviews-2023", f"raw_meta_{cat}", split="full", streaming=True, trust_remote_code=True)
        count = 0
        for item in meta_stream:
            if count >= SAMPLE_SIZE_META:
                break
            
            desc_list = item.get("description", [])
            desc_text = " ".join(desc_list) if isinstance(desc_list, list) else str(desc_list)
            
            p_asin = item.get("parent_asin")
            if not desc_text.strip() or not item.get("title") or not p_asin:
                continue
                
            # 💵 価格の日本円換算処理
            raw_price = item.get("price")
            try:
                price = int(float(raw_price) * 150) if raw_price is not None else 2500
                if price <= 0: price = 2500
            except:
                price = 2500
            
            # 🌟 【ファイル分離 ①】明日DBに突っ込む用のピュアなカタログデータ (bought_togetherは意図的に排除！)
            db_items.append({
                "asin": p_asin,
                "name": item.get("title"),
                "ai_category": cat,
                "price": price,
                "description": desc_text[:500],
                "image_url": PRESET_IMAGES[img_idx % len(PRESET_IMAGES)]
            })
            
            # 🌟 【ファイル分離 ②】マルコフの数理計算にしか使わない、軽量なリンク関係データ
            bought_together = item.get("bought_together")
            if bought_together and isinstance(bought_together, list):
                network_links.append({
                    "asin": p_asin,
                    "ai_category": cat,
                    "bought_together": bought_together
                })
                
            img_idx += 1
            count += 1
    except Exception as e:
        pass

    # ── 2. レビューログ（行動ログ）のストリーミング ──
    try:
        review_stream = load_dataset("McAuley-Lab/Amazon-Reviews-2023", f"raw_review_{cat}", split="full", streaming=True, trust_remote_code=True)
        count = 0
        for rev in review_stream:
            if count >= SAMPLE_SIZE_REVIEW:
                break
            p_asin = rev.get("parent_asin")
            if not p_asin:
                continue
            # 🌟 【ファイル分離 ③】行動の熱量を測る足跡データ
            sampled_reviews.append({
                "user_id": rev.get("user_id"),
                "asin": p_asin,
                "ai_category": cat,
                "timestamp": rev.get("timestamp")
            })
            count += 1
    except Exception as e:
        pass

# ── 3. それぞれ個別のファイルに永続化 ──

# ① DBインサート・Geminiベクトル化用（ノイズ一切なし！）
with open("items_for_db.json", "w", encoding="utf-8") as f:
    json.dump(db_items, f, ensure_ascii=False, indent=2)

# ② マルコフ遷移確率計算用（グラフ構造のみの軽量データ）
with open("item_links_only.json", "w", encoding="utf-8") as f:
    json.dump(network_links, f, ensure_ascii=False, indent=2)

# ③ 市場の行動ログ（重み付け用）
df_reviews = pd.DataFrame(sampled_reviews)
df_reviews.to_csv("amazon_review_samples.csv", index=False, encoding="utf-8")

print("\n" + "="*50)
print("✨ 【Step 1 データの完全分離に成功！】")
print(f"➔ ① DB・画面表示用データ : {len(db_items)} 件 (items_for_db.json)")
print(f"➔ ② 遷移計算用リンク辞書 : {len(network_links)} 件 (item_links_only.json)")
print(f"➔ ③ 市場行動ログ (CSV)   : {len(df_reviews)} 件 (amazon_review_samples.csv)")
print("="*50)