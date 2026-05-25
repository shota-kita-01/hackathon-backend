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
        
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        embeddings_json_path = os.path.join(BASE_DIR, "data", "items_with_embeddings_all_2200.json")
        fallback_json_path = os.path.join(BASE_DIR, "data", "items_for_db.json")
        
        try:
            with open(embeddings_json_path, "r", encoding="utf-8") as f:
                self.static_products = json.load(f)
            print(f"   ➔ ✨ 2,200件の完全版多次元空間データを正常にメモリーへ展開しました。")
        except FileNotFoundError:
            print(f"⚠️ {embeddings_json_path} が見つからないため、ベースデータでシミュレートします。")
            with open(fallback_json_path, "r", encoding="utf-8") as f:
                self.static_products = json.load(f)
                for item in self.static_products:
                    item["embedding"] = np.random.uniform(-1, 1, 768).tolist()

        for idx, item in enumerate(self.static_products):
            if "id" not in item:
                item["id"] = idx + 1
            if "status" not in item:
                item["status"] = "on_sale"

        matrix_path = os.path.join(BASE_DIR, "data", "markov_transition_matrix.json")
        with open(matrix_path, "r", encoding="utf-8") as f:
            self.markov_matrix = json.load(f)
            
        print(f"   ➔ ロード完了: 公式商品数 {len(self.static_products)} 件 / マルコフ行列 22x22")

    def _get_all_items(self):
        """【新設】公式データの最新ステータスをDBから同期し、ユーザー出品データと結合して全アイテムプールを返す"""
        from db import get_db_connection
        
        # 1. データベース（MySQL）から公式商品の最新ステータス（on_sale / sold_out）を一括ハント
        connection = get_db_connection()
        product_status_map = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, status FROM products;")
                rows = cursor.fetchall()
                for row in rows:
                    product_status_map[row["id"]] = row["status"]
        except Exception as e:
            print(f"⚠️ 公式商品のリアルタイムステータス同期に失敗しました: {e}")
        finally:
            connection.close()

        # 2. メモリ上にある静的JSONデータのステータスを、DBの最新値で動的に上書き書き換え
        for item in self.static_products:
            pid = item.get("id")
            if pid in product_status_map:
                item["status"] = product_status_map[pid]

        # 3. 最新化した公式データと、リアルタイムなユーザー出品データをガッチャンコして返却
        return self.static_products + self._load_user_items()

    def _load_user_items(self):
        """MySQLからユーザー出品をロードする瞬間も、IDを一律 100000 加算。"""
        from db import get_db_connection
        connection = get_db_connection()
        user_items = []
        try:
            with connection.cursor() as cursor:
                sql = """
                    SELECT 
                        id + 100000 AS id, 
                        NULL AS asin,
                        name, 
                        price, 
                        tags, 
                        description, 
                        image_url, 
                        status,
                        item_condition, 
                        seller_nickname AS seller_name, 
                        shipping_days,
                        embedding
                    FROM items;
                """
                cursor.execute(sql)
                rows = cursor.fetchall()
                for row in rows:
                    if row.get("embedding"):
                        try:
                            row["embedding"] = json.loads(row["embedding"])
                            user_items.append(row)
                        except Exception as e:
                            print(f"⚠️ ユーザーベクトルのパースに失敗: {e}")
        except Exception as e:
            print(f"⚠️ ユーザー出品データのリアルタイム取得に失敗: {e}")
        finally:
            connection.close()
        return user_items

    def _transform_item(self, item, score=None):
        """公式データ（JSON）と一般ユーザーデータ（DB）の構造の差異を吸収し、フロントエンドに統一整形"""
        data = {
            "id": item["id"], 
            "asin": item.get("asin"), 
            "name": item.get("name") if item.get("name") else item.get("name_ja"), 
            "price": item.get("price"), 
            "tags": item.get("tags") if item.get("tags") else item.get("ai_category"),
            "description": item.get("description") if item.get("description") else item.get("description_ja"), 
            "image_url": item.get("image_url"),
            "status": item.get("status", "on_sale"), 
            "item_condition": item.get("item_condition", "新品・未使用"), 
            "seller_name": item.get("seller_name", "公式出品"),         
            "shipping_days": item.get("shipping_days", "1〜2日で発送")
        }
        if score is not None:
            data["score"] = score
        return data

    # ===================================================
    # 🧠 「Ask AI ✨」用の自由テキスト検索
    # ===================================================
    def get_products_by_mood(self, mood_text, top_n=500):
        from db import client 
        # 💡 リアルタイム動的同期メソッド経由に修正
        all_items = self._get_all_items()
        
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
            
            for item in all_items:
                base_score = 0.2 + (abs(hash(item.get("asin", "default")) % 100) / 1000.0)
                item_cat = item.get("ai_category") or item.get("tags") or ""
                name_str = (item.get("name") or "").lower()
                desc_str = (item.get("description") or "").lower()
                cat_str = str(item_cat).lower()
                
                if query_str in name_str: base_score += 0.5
                if query_str in cat_str: base_score += 0.4
                if query_str in desc_str: base_score += 0.1
                
                for word in query_words:
                    if word in name_str or word in desc_str:
                        base_score += 0.1
                
                final_score = min(float(base_score), 0.99)
                product_data = self._transform_item(item, score=final_score)
                scored_items.append(product_data)
            
            scored_items.sort(key=lambda x: x["score"], reverse=True)
            return scored_items[:top_n]
        
        scored_items = []
        for item in all_items:
            v_key = "embedding" if "embedding" in item else ("embeddings" if "embeddings" in item else "vector")
            sim = cos_sim(query_vector, item[v_key])
            product_data = self._transform_item(item, score=sim)
            scored_items.append(product_data)
            
        scored_items.sort(key=lambda x: x["score"], reverse=True)
        return scored_items[:top_n]

    # ===================================================
    # 🛰️ 詳細画面用：確率的時間遷移 ＆ 空間的類似
    # ===================================================
    def get_recommendations(self, target_asin, top_n=3):
        # 💡 リアルタイム動的同期メソッド経由に修正
        all_items = self._get_all_items()

        target_item = next((item for item in all_items if item.get("asin") == str(target_asin)), None)
        
        if not target_item:
            try:
                target_id = int(target_asin)
                target_item = next((item for item in all_items if item.get("id") == target_id and not item.get("asin")), None)
            except ValueError:
                pass

        if not target_item: 
            print(f"⚠️ ターゲット商品が見つかりません (引数: {target_asin})")
            return None, None
            
        current_cat = target_item.get("ai_category") or target_item.get("tags")
        if not current_cat:
            current_cat = "Books"

        target_vector = target_item.get("embedding") or target_item.get("embeddings") or target_item.get("vector")
        if not target_vector:
            print(f"🚨 [データ破損を検知] 商品 '{target_item.get('name')}' のベクトルが虚空です。緊急疑似座標を注入します。")
            target_vector = np.random.uniform(-0.02, 0.02, 768).tolist()

        space_candidates = []
        for item in all_items:
            item_cat = item.get("ai_category") or item.get("tags")
            v = item.get("embedding") or item.get("embeddings") or item.get("vector")
            
            is_self = (item.get("asin") and target_item.get("asin") and item["asin"] == target_item["asin"]) or \
                      (not item.get("asin") and not target_item.get("asin") and item["id"] == target_item["id"])
            
            if not is_self and item_cat == current_cat and v:
                sim = cos_sim(target_vector, v)
                space_candidates.append((sim, item))
                
        space_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_1 = [self._transform_item(item) for _, item in space_candidates[:top_n]]

        transitions = self.markov_matrix.get(current_cat)
        if not transitions:
            return carousel_1, []
            
        sorted_next_cats = sorted([(prob, cat) for cat, prob in transitions.items() if cat != current_cat], reverse=True)
        if not sorted_next_cats:
            return carousel_1, []
            
        best_prob, next_cat = sorted_next_cats[0]
        
        time_candidates = []
        for item in all_items:
            item_cat = item.get("ai_category") or item.get("tags")
            v = item.get("embedding") or item.get("embeddings") or item.get("vector")
            if item_cat == next_cat and v:
                sim = cos_sim(target_vector, v)
                time_candidates.append((sim, item))
                
        time_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_2 = [self._transform_item(item) for _, item in time_candidates[:top_n]]
        
        return carousel_1, carousel_2