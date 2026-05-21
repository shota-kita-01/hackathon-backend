import os
import json
import time
from google import genai
from google.genai import types

# ==========================================
# ⚙️ 設定セクション
# ==========================================
# 💡 毎日ここを 0, 1, 2... と書き換えて実行するだけで、データが10%ずつ完成します！
CURRENT_BATCH_CYCLE = 0  

# 🔬 最初はTrueで3件テストし、成功したらFalseにして本番320件を一気に焼き切りましょう！
TEST_MODE = False

# 💡 フォルダ直下の `.env` から特権キー（GEMINI_API_KEY）を自動ロード
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")

if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# ==========================================
# 🔑 クライアント初期化（引数なしで環境変数を自動検知）
# ==========================================
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("🚨 .env ファイルに GEMINI_API_KEY が見つかりません。")
        
    # 複雑な引数は一切不要！AQ.キーがあればこれだけで特権アクセスになります
    client = genai.Client()
except Exception as e:
    print(f"🚨 クライアント初期化エラー: {e}")
    raise e

print(f"📦 [Day {CURRENT_BATCH_CYCLE}/9] サークルGCP特権・等速巡航パイプラインを起動します...")

# 2. カタログデータのロード
items_json_path = os.path.join(BASE_DIR, "data", "items_for_db.json")
with open(items_json_path, "r", encoding="utf-8") as f:
    all_items = json.load(f)

# 3. 🧮 カテゴリごとにデータをきれいに分類
from collections import defaultdict
category_groups = defaultdict(list)
for item in all_items:
    category_groups[item["ai_category"]].append(item)

target_items = []
start_idx = CURRENT_BATCH_CYCLE * 10
end_idx = start_idx + 10

for cat, items in category_groups.items():
    slice_batch = items[start_idx:end_idx]
    target_items.append(slice_batch)

target_items = [item for sublist in target_items for item in sublist]

if TEST_MODE:
    print("\n🔬 [TEST_MODE] 最初の3件だけをテストします...")
    target_items = target_items[:3]

print(f"🚀 計 {len(target_items)} 件のデータ処理（日本語翻訳 ＆ 768次元ベクトル化）を開始します。")

processed_items = []

idx = 0
while idx < len(target_items):
    item = target_items[idx]
    print(f"🔄 [{idx+1}/{len(target_items)}] ASIN: {item['asin']} を処理中...", end="", flush=True)
    
    translation_prompt = f"""
    You are an expert translator for a fashion/lifestyle e-commerce app.
    Translate the following product title and description into natural, appealing Japanese suitable for shoppers.
    Output JSON format ONLY with keys "name_ja" and "description_ja". Do not markdown.

    Title: {item.get('name')}
    Description: {item.get('description')}
    """
    
    try:
        # ① ピュアな最速翻訳モデルに修正（gemini-2.5-flash）
        trans_res = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=translation_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3
            )
        )
        parsed_json = json.loads(trans_res.text)
        
        # 💡 【型セーフティ】配列で返ってきた場合の保険
        if isinstance(parsed_json, list) and len(parsed_json) > 0:
            parsed_json = parsed_json[0]
        
        # ② 最新の高性能埋め込みモデルに修正（gemini-embedding-2）
        structured_text = f"""
        Product Characteristics:
        - Title: {item.get('name')}
        - Category: {item.get('ai_category')}
        - Core Context: {item.get('description')}
        """
        
        embed_res = client.models.embed_content(
            model="gemini-embedding-2",
            contents=structured_text,
            config=types.EmbedContentConfig(output_dimensionality=768)
        )
        
        # ③ 日本語カタログデータと特徴ベクトルのドッキング
        hybrid_item = {
            "asin": item["asin"],
            "name_en": item["name"],
            "name": parsed_json.get("name_ja") if hasattr(parsed_json, 'get') else None,
            "ai_category": item["ai_category"],
            "price": item["price"],
            "description_en": item["description"],
            "description": parsed_json.get("description_ja") if hasattr(parsed_json, 'get') else None,
            "image_url": item["image_url"],
            "embedding": embed_res.embeddings[0].values
        }
        
        processed_items.append(hybrid_item)
        print(" ➔ ✨ 特権通信成功！")
        
        idx += 1
        
        # ⏳ 安全インターバル（特権枠の圧倒的な広さなら、3秒間隔で超高速に回せます）
        time.sleep(3)
        
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "503" in error_msg:
            print("\n🛑 [安全弁発動] 瞬間的なレート制限または混雑を検知しました。")
            print("   ➔ 30秒間お昼寝して自動再試行します。そのままお待ちください...")
            time.sleep(30)
        else:
            print(f"\n⚠️ データ起因エラー（パース失敗等）のためこの商品をスキップします: {e}")
            idx += 1
            time.sleep(3)

# 5. 💾 成果物の永続化
if TEST_MODE:
    output_filename = "test_items_hybrid.json"
else:
    output_filename = f"items_with_embeddings_day_{CURRENT_BATCH_CYCLE}.json"

output_path = os.path.join(BASE_DIR, output_filename)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(processed_items, f, ensure_ascii=False, indent=2)

print("\n" + "="*50)
print(f"✨ 【Day {CURRENT_BATCH_CYCLE} 特権インフラにて完全完遂！】")
print(f"➔ 成果物ファイル: {output_path}")
print("="*50)