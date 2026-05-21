import os
import json
import numpy as np

def cos_sim(v1, v2):
    """768次元ベクトルのコサイン類似度を計算"""
    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))

class RecommendationEngine:
    def __init__(self):
        print("🧠 レコメンドエンジンを初期化中...")
        
        # 💡 スクリプトが存在するフォルダの絶対パスを取得し、安全に data/ フォルダを指すようにします
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        
        # 1. ベクトル付き商品データの読み込み（Day 0 の成果物ファイルをターゲットにします）
        # ➔ パス: hackathon-backend/data/items_with_embeddings_day_0.json
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

        # 2. マルコフ遷移確率行列の読み込み 
        # ➔ 💡 ここです！ "data" を挟んで hackathon-backend/data/markov_transition_matrix.json を正確に狙い撃ちします
        matrix_path = os.path.join(BASE_DIR, "data", "markov_transition_matrix.json")
        with open(matrix_path, "r", encoding="utf-8") as f:
            self.markov_matrix = json.load(f)
            
        print(f"   ➔ ロード完了: 商品数 {len(self.items)} 件 / マルコフ行列 33x33")

    def get_recommendations(self, target_asin, top_n=3):
        # ターゲット商品の特定
        target_item = next((item for item in self.items if item["asin"] == target_asin), None)
        if not target_item:
            print(f"❌ ASIN: {target_asin} が見つかりませんでした。")
            return None, None
            
        current_cat = target_item["ai_category"]
        target_vector = target_item["embedding"]
        
        print(f"\n🎯 [現在の商品]: {target_item['name']} ({current_cat})")
        print("-" * 60)

        # ──────────────────────────────────────────────────
        # カルーセル①: 【空間的類似】同じカテゴリ内でのコサイン類似度検索
        # ──────────────────────────────────────────────────
        space_candidates = []
        for item in self.items:
            if item["asin"] != target_asin and item["ai_category"] == current_cat:
                sim = cos_sim(target_vector, item["embedding"])
                space_candidates.append((sim, item))
                
        # 類似度順にソートして上位を抽出
        space_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_1 = [item for _, item in space_candidates[:top_n]]

        # ──────────────────────────────────────────────────
        # カルーセル②: 【確率的時間遷移】マルコフ遷移 ➔ 次カテゴリ内での近傍探索
        # ──────────────────────────────────────────────────
        transitions = self.markov_matrix[current_cat]
        
        sorted_next_cats = sorted(
            [(prob, cat) for cat, prob in transitions.items() if cat != current_cat],
            reverse=True
        )
        best_prob, next_cat = sorted_next_cats[0]
        print(f"🎲 [マルコフ予測]: 次に回遊しやすいジャンルは [{next_cat}] (確率: {best_prob:.1%})")
        
        time_candidates = []
        for item in self.items:
            if item["ai_category"] == next_cat:
                sim = cos_sim(target_vector, item["embedding"])
                time_candidates.append((sim, item))
                
        time_candidates.sort(key=lambda x: x[0], reverse=True)
        carousel_2 = [item for _, item in time_candidates[:top_n]]
        
        return carousel_1, carousel_2

# ── 🔬 ローカルでのロジック検証用メイン処理 ──
if __name__ == "__main__":
    engine = RecommendationEngine()
    
    # データの存在チェックをしてからテスト実行
    if engine.items:
        test_asin = engine.items[0]["asin"]
        c1, c2 = engine.get_recommendations(test_asin, top_n=3)
        
        if c1 and c2:
            print("\n📦 カルーセル①【空間的類似】この商品と似ているアイテム:")
            for i, item in enumerate(c1):
                print(f"  {i+1}. [{item['ai_category']}] {item['name']} ({item['price']}円)")
                
            print("\n📦 カルーセル②【確率的時間遷移】次にこれを買い回る人が多いジャンル:")
            for i, item in enumerate(c2):
                print(f"  {i+1}. [{item['ai_category']}] {item['name']} ({item['price']}円)")