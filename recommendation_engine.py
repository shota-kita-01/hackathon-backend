import os
import json
import numpy as np
from fastapi import HTTPException
from google.genai import types

def cos_sim(v1, v2):
    """768次元ベクトルのコサイン類似度を計算"""
    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))

class RecommendationEngine:
    def __init__(self):
        print("🧠 レコメンドエンジンを初期化中...")
        
        # パスを確実にルートの data/ フォルダへ誘導
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        
        embeddings_json_path = os.path.join(BASE_DIR, "data", "items_with_embeddings_all_2200.json")
        fallback_json_path = os.path.join(BASE_DIR, "data", "items_for_db.json")
        
        try:
            with open(embeddings_json_path, "r", encoding="utf-8") as f:
                self.items = json.load(f)
            print(f"   ➔ ✨ 2,200件の完全版多次元空間データを正常にメモリーへ展開しました。")
        except FileNotFoundError:
            print(f"⚠️ {embeddings_json_path} が見つからないため、ベースデータでシミュレートします。")
            with open(fallback_json_path, "r", encoding="utf-8") as f:
                self.items = json.load(f)
                for item in self.items:
                    item["embedding"] = np.random.uniform(-1, 1, 768).tolist()

        for idx, item in enumerate(self.items):
            if "id" not in item:
                item["id"] = idx + 1
            if "status" not in item:
                item["status"] = "on_sale"

        matrix_path = os.path.join(BASE_DIR, "data", "markov_transition_matrix.json")
        with open(matrix_path, "r", encoding="utf-8") as f:
            self.markov_matrix = json.load(f)
            
        print(f"   ➔ ロード完了: 商品数 {len(self.items)} 件 / マルコフ行列 22x22")

    def _transform_item(self, item, score=None):
        """
        💡 【新設】JSONの公式カタログデータを、フロントエンドの統一フリマスキーマへ
        安全かつ美しくマッピングする数理変換ヘルパー
        """
        data = {
            "id": item["id"], 
            "asin": item.get("asin"), 
            "name": item.get("name"),
            "price": item.get("price"), 
            "tags": item.get("ai_category"),
            "description": item.get("description"), 
            "image_url": item.get("image_url"),
            "status": item["status"], 
            "item_condition": "新品・未使用", # 💡 公式カタログ品に一律「新品」のメタデータを付与
            "seller_name": "公式出品",         # 💡 表記揺れ（Amazon公式など）を防ぐために「公式出品」に統一
            "shipping_days": "1〜2日で発送"
        }
        if score is not None:
            data["score"] = score
        return data

    # ===================================================
    # 🧠 「Ask AI ✨」用の自由テキスト検索
    # ===================================================
    def get_products_by_mood(self, mood_text, top_n=500):
        from db import client 
        
        query_vector = None
        try:
            response = client.models.embed_content(
                model="gemini-embedding-2",
                contents=mood_text,
                config=types.EmbedContentConfig(output_dimensionality=768)
            )
            query_vector = response.embeddings[0].values
            print("💪 gemini-embedding-2 での特権ベクトル化に成功しました！")
            
        except Exception as e:
            print(f"⚠️ APIエラー({e}): 緊急テキストマッチエンジンを起動します。")
            
            scored_items = []
            query_str = mood_text.lower().strip()
            query_words = [w for w in query_str.split() if w]
            
            for item in self.items:
                base_score = 0.2 + (abs(hash(item.get("asin", "default")) % 100) / 1000.0)
                name_str = (item.get("name") or "").lower()
                desc_str = (item.get("description") or "").lower()
                cat_str = (item.get("ai_category") or "").lower()
                
                if query_str in name_str: base_score += 0.5
                if query_str in cat_str: base_score += 0.4
                if query_str in desc_str: base_score += 0.1
                
                for word in query_words:
                    if word in name_str or word in desc_str:
                        base_score += 0.1
                
                final_score = min(float(base_score), 0.99)
                
                # 💡 変換ヘルパーを介してパッキング
                product_data = self._transform_item(item, score=final_score)
                scored_items.append(product_data)
            
            scored_items.sort(key=lambda x: x["score"], reverse=True)
            return scored_items[:top_n]
        
        # ─── 🤖 通常ルート：コサイン類似度計算 ───
        scored_items = []
        for item in self.items:
            v_key = "embedding" if "embedding" in item else ("embeddings" if "embeddings" in item else "vector")
            sim = cos_sim(query_vector, item[v_key])
            
            # 💡 変換ヘルパーを介してパッキング
            product_data = self._transform_item(item, score=sim)
            scored_items.append(product_data)
            
        scored_items.sort(key=lambda x: x["score"], reverse=True)
        return scored_items[:top_n]

    # ===================================================
    # 🛰️ 詳細画面用：確率的時間遷移 ＆ 空間的類似
    # ===================================================
    def get_recommendations(self, target_asin, top_n=3):
        target_item = next((item for item in self.items if item["asin"] == target_asin), None)
        if not target_item: return None, None
            
        current_cat = target_item["ai_category"]
        target_vector = target_item.get("embedding") or target_item.get("embeddings") or target_item.get("vector")
        if not target_vector: return None, None

        space_candidates = []
        for item in self.items:
            v = item.get("embedding") or item.get("embeddings") or item.get("vector")
            if item["asin"] != target_asin and item["ai_category"] == current_cat and v:
                sim = cos_sim(target_vector, v)
                space_candidates.append((sim, item))
                
        space_candidates.sort(key=lambda x: x[0], reverse=True)
        # 💡 1段目のカルーセル候補にスキーマを完全注入！
        carousel_1 = [self._transform_item(item) for _, item in space_candidates[:top_n]]

        transitions = self.markov_matrix[current_cat]
        sorted_next_cats = sorted([(prob, cat) for cat, prob in transitions.items() if cat != current_cat], reverse=True)
        best_prob, next_cat = sorted_next_cats[0]
        
        time_candidates = []
        for item in self.items:
            v = item.get("embedding") or item.get("embeddings") or item.get("vector")
            if item["ai_category"] == next_cat and v:
                sim = cos_sim(target_vector, v)
                time_candidates.append((sim, item))
                
        time_candidates.sort(key=lambda x: x[0], reverse=True)
        # 💡 2段目のカルーセル候補にもスキーマを完全注入！
        carousel_2 = [self._transform_item(item) for _, item in time_candidates[:top_n]]
        
        return carousel_1, carousel_2