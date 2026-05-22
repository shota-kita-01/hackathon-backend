import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types

# ==========================================
# ⚙️ 設定セクション（特権枠・超並列仕様）
# ==========================================
RUN_MODE = "all"        # ➔ "all" (2200件一撃) または "cycle" (220件)
CURRENT_BATCH_CYCLE = 0  
TEST_MODE = False        # 💡 通信確認できたので、満を持して False に！

# 🚀 【超並列パラメーター】特権キーなので15並列で一気に殴り込みます
MAX_WORKERS = 15  

# 💡 パス解決・環境変数ロード
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
env_path = os.path.join(PROJECT_ROOT, ".env")

if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("🚨 .env ファイルに GEMINI_API_KEY が見つかりません。")
    client = genai.Client()
except Exception as e:
    print(f"🚨 クライアント初期化エラー: {e}")
    raise e

print(f"📦 [UTTC特権インフラ × {MAX_WORKERS}スレッド並列] 限界突破パイプラインを起動します...")

# カタログデータのロード
items_json_path = os.path.join(PROJECT_ROOT, "data", "items_for_db.json")
with open(items_json_path, "r", encoding="utf-8") as f:
    all_items = json.load(f)

from collections import defaultdict
category_groups = defaultdict(list)
for item in all_items:
    category_groups[item["ai_category"]].append(item)

target_items = []
if RUN_MODE == "all":
    print("🚀 [MODE: ALL] 全2,200件 一括フルコンプリート並列モード")
    for cat, items in category_groups.items():
        target_items.extend(items)
else:
    print(f"⚖️ [MODE: CYCLE] Day {CURRENT_BATCH_CYCLE}/9 分割巡航並列モード")
    start_idx = CURRENT_BATCH_CYCLE * 10
    end_idx = start_idx + 10
    for cat, items in category_groups.items():
        target_items.extend(items[start_idx:end_idx])

if TEST_MODE:
    target_items = target_items[:3]

total_count = len(target_items)
print(f"🔥 計 {total_count} 件の超高速並列処理を開始します。")

# 🔒 スレッド間の進捗カウンタと画面出力の衝突を防ぐロック機構
progress_counter = 0
counter_lock = threading.Lock()
processed_items = []
items_lock = threading.Lock()

# 🧭 単一アイテムを処理するワーカー関数
def process_single_item(item):
    global progress_counter
    
    translation_prompt = f"""
    You are an expert translator for a fashion/lifestyle e-commerce app.
    Translate the following product title and description into natural, appealing Japanese suitable for shoppers.
    Output JSON format ONLY with keys "name_ja" and "description_ja". Do not markdown.

    Title: {item.get('name')}
    Description: {item.get('description')}
    """
    
    try:
        # ① 翻訳
        trans_res = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=translation_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3
            )
        )
        parsed_json = json.loads(trans_res.text)
        if isinstance(parsed_json, list) and len(parsed_json) > 0:
            parsed_json = parsed_json[0]
        
        # ② 埋め込み
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
        
        # 安全に結果スレッドへ追加
        with items_lock:
            processed_items.append(hybrid_item)
            
        # 安全に進捗を表示
        with counter_lock:
            progress_counter += 1
            print(f"⚡ [{progress_counter}/{total_count}] ASIN: {item['asin']} ➔ ✨ 処理完了！", flush=True)
            
    except Exception as e:
        with counter_lock:
            progress_counter += 1
            print(f"🛑 [{progress_counter}/{total_count}] ASIN: {item['asin']} ➔ ⚠️ エラー回避スキップ: {e}", flush=True)

# ⏱️ 総処理時間の計測開始
start_time = time.time()

# 🧵 スレッドプールによる弾幕並列実行
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    executor.map(process_single_item, target_items)

# ファイルの書き出し
if TEST_MODE:
    output_filename = "test_items_hybrid.json"
elif RUN_MODE == "all":
    output_filename = "items_with_embeddings_all_2200.json"
else:
    output_filename = f"items_with_embeddings_day_{CURRENT_BATCH_CYCLE}.json"

output_path = os.path.join(PROJECT_ROOT, "data", output_filename)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(processed_items, f, ensure_ascii=False, indent=2)

elapsed_time = time.time() - start_time
print("\n" + "="*50)
print("✨ 【超時空マルチスレッド・パイプライン完全走破】")
print(f"➔ 成功件数: {len(processed_items)} / {total_count} 件")
print(f"➔ 総所要時間: {elapsed_time:.1f} 秒 (並列化により圧倒的超速化！)")
print(f"➔ 成果物ファイル: {output_path}")
print("="*50)