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
        filter_status = req.filter_status # 🆕 フィルター条件の取得

        english_keywords = ""
        if req.mode in ["mood", "both"] and req.mood_text.strip():
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
            except Exception as openai_err:
                english_keywords = req.mood_text

        with connection.cursor() as cursor:
            # 🆕 1. SQLの段階で「販売中のみ」「売切のみ」は弾く
            if filter_status == "active":
                cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items WHERE status = 'on_sale'")
            elif filter_status == "sold_out":
                cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items WHERE status = 'sold_out'")
            else:
                cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items")
                
            items = cursor.fetchall()
            if not items: return []

            cursor.execute("SELECT i.name, i.description FROM purchases p JOIN items i ON p.item_id = i.id WHERE p.buyer_id = %s", (req.user_id,))
            past_purchases = cursor.fetchall()
            
            cursor.execute("SELECT i.name, i.description FROM likes l JOIN items i ON l.item_id = i.id WHERE l.user_id = %s", (req.user_id,))
            past_likes = cursor.fetchall()
            
            history_text = " ".join([f"{p['name']} {p['description']}" for p in past_purchases + past_likes])

            combined_user_text = english_keywords if req.mode == "mood" else history_text if req.mode == "history" else f"{english_keywords} {history_text}".strip()
            if not combined_user_text: return items[:10]

            item_texts = [f"{item['name']} {item['description']}" for item in items]
            all_texts = item_texts + [combined_user_text]

            vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            item_vectors = tfidf_matrix[:-1]
            user_vector = tfidf_matrix[-1]
            similarities = cosine_similarity(user_vector, item_vectors).flatten()

            # 🆕 2. 「両方」が選ばれている時だけ、売切商品のスコアに0.5の減衰ペナルティを課す
            # 🆕 マッチングスコアの付与と「0.9倍ペナルティ」への調整
            for idx, item in enumerate(items):
                base_score = float(similarities[idx])
                
                # 💡 0.5倍は強すぎたので、0.9倍にして「少しだけ順位を下げる」絶妙な塩梅にチューニング
                if filter_status == "both" and item["status"] == "sold_out":
                    item["score"] = base_score * 0.9
                else:
                    item["score"] = base_score

            # 補正後のスコアで一斉ソート
            recommended_items = sorted(items, key=lambda x: x["score"], reverse=True)
            
            # 💡 [:40] の切り捨てを撤廃し、ソート済み全件をフロントに返す！
            return recommended_items
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()