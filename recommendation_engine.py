import os
import json
import numpy as np
from fastapi import HTTPException

def cos_sim(v1, v2):
    """768次元ベクトルのコサイン類似度を計算"""
    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))

class RecommendationEngine:
    def __init__(self):
        print("🧠 レコメンドエンジンを初期化中...")
        
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        embeddings_json_path = os.path.join(BASE_DIR, "data", "items_with_embeddings_day_0.json")
        fallback_json_path = os.path.join(BASE_DIR, "data", "items_for_db.json")
        
        try:
            with open(embeddings_json_path, "r", encoding="utf-8") as f:
                self.items = json.load(f)
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
            
        print(f"   ➔ ロード完了: 商品数 {len(self.items)} 件 / マルコフ行列 33x33")

    # ===================================================
    # 🧠 「Ask AI ✨」用の自由テキスト・ベクトル検索（二段構え完全版）
    # ===================================================
    def get_products_by_mood(self, mood_text, top_n=20):
        from db import client 
        
        query_vector = None
        try:
            # 1. 【第一候補】text-embedding-004 でベクトル化を試みる
            response = client.models.embed_content(
                model="text-embedding-004",
                contents=mood_text
            )
            query_vector = response.embeddings[0].values
            print("💪 text-embedding-004 でのベクトル化に成功しました。")
            
        except Exception as e1:
            # 💡 もしGoogle側から404などで拒絶されたら、ここを通過して自動リトライ！
            print(f"⚠️ text-embedding-004 が拒絶されました({e1})。安定版 embedding-001 でリトライします...")
            try:
                # 【第二候補】広く安定稼働している同じ768次元の embedding-001 で再試行
                response = client.models.embed_content(
                    model="embedding-001",
                    contents=mood_text
                )
                query_vector = response.embeddings[0].values
                print("🔥 embedding-001 でのフォールバック注入に成功しました！")
            except Exception as e2:
                # 両方全滅した場合のみエラーを吐く
                error_msg = f"Gemini Embedding API All Failed. e1: {str(e1)}, e2: {str(e2)}"
                print(f"❌ {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)
        
        # 2. 全320件の商品と総当たりでコサイン類似度を計算
        try:
            scored_items = []
            for item in self.items:
                vector_key = None
                for key in ["embedding", "embeddings", "vector"]:
                    if key in item:
                        vector_key = key
                        break
                
                if vector_key is None:
                    raise KeyError("商品データ内にベクトルキー(embedding等)が見つかりません。")
                
                sim = cos_sim(query_vector, item[vector_key])
                
                product_data = {
                    "id": item["id"],
                    "asin": item.get("asin"),
                    "name": item.get("name"),
                    "price": item.get("price"),
                    "tags": item.get("ai_category"),
                    "description": item.get("description"),
                    "image_url": item.get("image_url"),
                    "status": item["status"],
                    "seller_name": "Amazon公式",
                    "shipping_days": "1〜2日で発送",
                    "score": sim
                }
                scored_items.append(product_data)
                
            scored_items.sort(key=lambda x: x["score"], reverse=True)
            return scored_items[:top_n]
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Calculation Error: {str(e)}")

    def get_recommendations(self, target_asin, top_n=3):
        target_item = next((item for item in self.items if item["asin"] == target_asin), None)
        if not target_item:
            return None, None
            
        current_cat = target_item["ai_category"]
        target_vector = target_item.get("embedding") or target_item.get("embeddings") or target_item.get("vector")
        
        if not target_vector:
            return None, None

        space_candidates = []
        for item in self.items:
            v = item.get("embedding") or item.get("embeddings") or item.get("vector")
            if item["asin"] != target_asin and item["ai_category"] == current_cat and v:
                sim = cos_sim(target_vector, v)
                space_candidates.append((sim, item))
                
        space_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_1 = [item for _, item in space_candidates[:top_n]]

        transitions = self.markov_matrix[current_cat]
        sorted_next_cats = sorted(
            [(prob, cat) for cat, prob in transitions.items() if cat != current_cat],
            reverse=True
        )
        best_prob, next_cat = sorted_next_cats[0]
        
        time_candidates = []
        for item in self.items:
            v = item.get("embedding") or item.get("embeddings") or item.get("vector")
            if item["ai_category"] == next_cat and v:
                sim = cos_sim(target_vector, v)
                time_candidates.append((sim, item))
                
        time_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_2 = [item for _, item in time_candidates[:top_n]]
        
        return carousel_1, carousel_2