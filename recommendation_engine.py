import os
import json
import numpy as np

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

        # 💡 フロントの履歴機能や詳細モーダルと整合性を保つため、
        # JSON内のデータに MySQL（Cloud SQL）と同じ 1〜320 の連番通し番号 id を安全に付与します
        for idx, item in enumerate(self.items):
            if "id" not in item:
                item["id"] = idx + 1
            if "status" not in item:
                item["status"] = "on_sale"

        # 2. マルコフ遷移確率行列の読み込み 
        matrix_path = os.path.join(BASE_DIR, "data", "markov_transition_matrix.json")
        with open(matrix_path, "r", encoding="utf-8") as f:
            self.markov_matrix = json.load(f)
            
        print(f"   ➔ ロード完了: 商品数 {len(self.items)} 件 / マルコフ行列 33x33")


    # ===================================================
    # 🧠 【🆕 新設】「Ask AI ✨」用の自由テキスト・ベクトル検索
    # ===================================================
    def get_products_by_mood(self, mood_text, top_n=20):
        """
        ユーザーの自由な入力（例：爽やかな春服）を Gemini で768次元ベクトル化し、
        全320件のAmazonカタログデータと総当たりでコサイン類似度検索を行う
        """
        # 💡 循環インポートを美しく防ぐために、メソッド内で安全に db から client をインポート
        from db import client 
        
        try:
            # 1. ユーザーの入力テキストを、Geminiの高性能埋め込みモデル（768次元）でベクトル変換！
            response = client.models.embed_content(
                model="text-embedding-004",
                contents=mood_text
            )
            query_vector = response.embeddings[0].values
            
            # 2. 全320件の商品と総当たりでコサイン類似度を計算
            scored_items = []
            for item in self.items:
                sim = cos_sim(query_vector, item["embedding"])
                
                # フロントの SearchTab や ItemCard が100%バグらずに解釈できる綺麗なデータ構造へ翻訳
                product_data = {
                    "id": item["id"],
                    "asin": item.get("asin"),
                    "name": item.get("name"),
                    "price": item.get("price"),
                    "tags": item.get("ai_category"),    # ai_category をフロントの tags に変換
                    "description": item.get("description"),
                    "image_url": item.get("image_url"),
                    "status": item["status"],
                    "seller_name": "Amazon公式",
                    "shipping_days": "1〜2日で発送",
                    "score": sim                        # 🤖 ここで計算した類似度スコアを注入！
                }
                scored_items.append(product_data)
                
            # 3. 類似度スコアが高い順にソートして上位を切り出してリターン
            scored_items.sort(key=lambda x: x["score"], reverse=True)
            return scored_items[:top_n]
            
        except Exception as e:
            print(f"❌ エンジン内でのベクトル変換または類似度計算に失敗: {e}")
            raise e


    # ===================================================
    # 🛰️ 既存機能：詳細画面用のハイブリッド推薦（完全維持）
    # ===================================================
    def get_recommendations(self, target_asin, top_n=3):
        target_item = next((item for item in self.items if item["asin"] == target_asin), None)
        if not target_item:
            print(f"❌ ASIN: {target_asin} が見つかりませんでした。")
            return None, None
            
        current_cat = target_item["ai_category"]
        target_vector = target_item["embedding"]
        
        # カルーセル①: 【空間的類似】同じカテゴリ内でのコサイン類似度検索
        space_candidates = []
        for item in self.items:
            if item["asin"] != target_asin and item["ai_category"] == current_cat:
                sim = cos_sim(target_vector, item["embedding"])
                space_candidates.append((sim, item))
                
        space_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_1 = [item for _, item in space_candidates[:top_n]]

        # カルーセル②: 【確率的時間遷移】マルコフ遷移 ➔ 次カテゴリ内での近傍探索
        transitions = self.markov_matrix[current_cat]
        sorted_next_cats = sorted(
            [(prob, cat) for cat, prob in transitions.items() if cat != current_cat],
            reverse=True
        )
        best_prob, next_cat = sorted_next_cats[0]
        
        time_candidates = []
        for item in self.items:
            if item["ai_category"] == next_cat:
                sim = cos_sim(target_vector, item["embedding"])
                time_candidates.append((sim, item))
                
        time_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_2 = [item for _, item in time_candidates[:top_n]]
        
        return carousel_1, carousel_2