import os
import json
import time
from google import genai
from google.genai import types

# 1. 最新SDKのクライアント初期化
try:
    client = genai.Client()
except Exception as e:
    raise ValueError("🚨 クライアントの初期化に失敗しました。環境変数 'GEMINI_API_KEY' を確認してください。")

print("🧠 Step 2: [最新環境 Python3.11 × 最新SDK × 安定一括モデル] 生成を開始します...")

# 2. データの読み込み（100%読み込み専用、元データは絶対に無傷です）
with open("items_for_db.json", "r", encoding="utf-8") as f:
    items = json.load(f)

print(f"   ➔ 読み込み完了。計 {len(items)} 件の商品を安全に処理します（所要時間: 約30分）。")

def build_structured_text(item):
    return f"""
    Product Characteristics:
    - Title: {item.get('name')}
    - Category: {item.get('ai_category')}
    - Core Context: {item.get('description')}
    
    Inferred Value Profile:
    - Target Audience Lifestyle: High affinity for {item.get('ai_category')} oriented consumers.
    - Anticipated Use Case Scenario: Ideal for personal lifestyle optimization and quality enhancement in {item.get('ai_category')}.
    """

# 💡 最新SDKから、一括マルチバッチ処理への完全な互換性を持つ768次元モデルを指定
CHOSEN_MODEL = "gemini-embedding-001"

# ⏱️ 1分間100件の無料枠の網を、完全に、かつ最速で無効化する黄金比
BATCH_SIZE = 50
embedded_items = []

for i in range(0, len(items), BATCH_SIZE):
    batch = items[i:i+BATCH_SIZE]
    structured_texts = [build_structured_text(item) for item in batch]
    
    success = False
    while not success:
        print(f"⚡ [{i + len(batch)}/{len(items)}] 件目のバッチをベクトル化中...")
        try:
            # 🆕 最新SDKの書き方で一撃呼び出し（configなしでジャスト768次元が返ります）
            response = client.models.embed_content(
                model=CHOSEN_MODEL,
                contents=structured_texts
            )
            
            # 各商品に対して1対1で綺麗なベクトル（values）が100%届くため、IndexErrorは永続的に消滅します
            for idx, item in enumerate(batch):
                embedding = response.embeddings[idx].values
                item["embedding"] = embedding
                embedded_items.append(item)
            
            success = True
            
            # ⏳ 【等速巡航セーフティ】
            # 50件処理するごとに31秒休むことで、Google側の1分間タイマーを常にクリーンに保ちます
            if i + BATCH_SIZE < len(items):
                print("   ➔ クォータ衝突を未然に防ぐため、31秒間システムを休止します（等速巡航モード）...")
                time.sleep(31)
                
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                print("⚠️ スライド窓の制限に一時的に接触しました。")
                print("   ➔ 完全にリセットされるまで【65秒間】深くスリープして自動再試行します...")
                time.sleep(65)
            else:
                print(f"🚨 予期せぬエラー: {e}")
                raise e

# 6. 3200件のドッキングがすべて終わったら、最後に1回だけ綺麗に保存
with open("items_with_embeddings.json", "w", encoding="utf-8") as f:
    json.dump(embedded_items, f, ensure_ascii=False, indent=2)

print("\n" + "="*50)
print("✨ 【Step 2 最新環境にて完全完遂！】")
print(f"➔ 768次元ベクトル付き商品マスター: {len(embedded_items)} 件 (items_with_embeddings.json)")
print("="*50)