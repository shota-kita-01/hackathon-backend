from fastapi import APIRouter, HTTPException
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db import get_db_connection, client
from schemas import RecommendRequest

router = APIRouter()

@router.post("/api/recommend")
def get_recommendations(req: RecommendRequest):
    connection = get_db_connection()
    try:
        # フロントから送られてきたフィルター条件を安全に取得
        filter_status = getattr(req, "filter_status", "both")

        actual_mode = req.mode
        if actual_mode in ["mood", "both"] and not req.mood_text.strip():
            actual_mode = "history"

        # OpenAIによるテキストの英語キーワード化
        english_keywords = ""
        if actual_mode in ["mood", "both"] and req.mood_text.strip():
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a semantic processing engine for a fashion e-commerce search. Convert the user input into a space-separated list of optimal English search keywords. Output ONLY the space-separated lowercase keywords. No punctuation."},
                        {"role": "user", "content": f'User input: "{req.mood_text}"'}
                    ],
                    temperature=0.2,
                )
                english_keywords = response.choices[0].message.content.strip().lower()
            except Exception:
                english_keywords = req.mood_text

        with connection.cursor() as cursor:
            # 1. SQLの段階で「新着順」を取得のベースにする
            if filter_status == "active":
                cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items WHERE status = 'on_sale' ORDER BY id DESC")
            elif filter_status == "sold_out":
                cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items WHERE status = 'sold_out' ORDER BY id DESC")
            else:
                cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items ORDER BY id DESC")
                
            # 🆕 【対策1】すべて list() で包んで、型の衝突エラーを根絶する
            items = list(cursor.fetchall())
            if not items: return []

            cursor.execute("SELECT i.name, i.description FROM purchases p JOIN items i ON p.item_id = i.id WHERE p.buyer_id = %s", (req.user_id,))
            past_purchases = list(cursor.fetchall())
            
            cursor.execute("SELECT i.name, i.description FROM likes l JOIN items i ON l.item_id = i.id WHERE l.user_id = %s", (req.user_id,))
            past_likes = list(cursor.fetchall())
            
            # 🆕 【対策2】.get() を使って、データが欠損していても落ちないように文字列結合
            history_list = past_purchases + past_likes
            history_text = " ".join([f"{p.get('name', '')} {p.get('description', '')}" for p in history_list])

            # 🆕 【対策3】完全に新規ユーザーで入力もない場合の安全装置
            if actual_mode == "history" and not history_text.strip():
                for item in items:
                    base_score = 1.0
                    # .get("status") でKeyErrorを回避
                    if filter_status == "both" and item.get("status") == "sold_out":
                        item["score"] = base_score * 0.9
                    else:
                        item["score"] = base_score
                
                # スコア順 ＞ 新着順 でソートして返す
                return sorted(items, key=lambda x: (x.get("score", 0), x.get("id", 0)), reverse=True)

            # TF-IDFが空文字でエラーを吐かないためのダミーテキスト
            safe_history = history_text if history_text.strip() else "dummy_history_empty"
            safe_mood = english_keywords if english_keywords.strip() else "dummy_mood_empty"

            item_texts = [f"{item.get('name', '')} {item.get('description', '')}" for item in items]
            
            all_texts = item_texts + [safe_history, safe_mood]

            vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            # ベクトルの切り分け
            item_vectors = tfidf_matrix[:-2]
            history_vector = tfidf_matrix[-2]
            mood_vector = tfidf_matrix[-1]

            # 履歴と気分のスコアを別々に計算
            sim_history = cosine_similarity(history_vector, item_vectors).flatten()
            sim_mood = cosine_similarity(mood_vector, item_vectors).flatten()

            for idx, item in enumerate(items):
                # モードに応じた加重平均スコアの算出
                if actual_mode == "history":
                    base_score = float(sim_history[idx])
                elif actual_mode == "mood":
                    base_score = float(sim_mood[idx])
                elif actual_mode == "both":
                    # ハイブリッド： 今の気分(80%) ＋ 過去の履歴(20%) 
                    base_score = (float(sim_mood[idx]) * 0.8) + (float(sim_history[idx]) * 0.2)
                else:
                    base_score = 0.0

                # 売り切れの0.9倍ペナルティ適用
                if filter_status == "both" and item.get("status") == "sold_out":
                    item["score"] = base_score * 0.9
                else:
                    item["score"] = base_score

            # 一斉ソート
            recommended_items = sorted(items, key=lambda x: (x.get("score", 0), x.get("id", 0)), reverse=True)
            return recommended_items
            
    except Exception as e:
        # 🆕 【対策4】万が一エラーが起きても、ターミナルに理由を出力して原因追及できるようにする
        print(f"🔥 Recommend API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()