import os
import json
import sys
import pymysql
from google import genai  

# 🧠 Geminiクライアントの初期化
client = genai.Client()

# データベース接続関数（ロジックは完全維持です！）
def get_db_connection():
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PWD")
    db_name = os.getenv("MYSQL_DATABASE")
    host_env = os.getenv("MYSQL_HOST", "")
    
    if host_env.startswith("unix("):
        socket_path = host_env.replace("unix(", "").rstrip(")")
        return pymysql.connect(
            user=user,
            password=password,
            database=db_name,
            unix_socket=socket_path,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    else:
        return pymysql.connect(
            host=host_env or "127.0.0.1",
            user=user,
            password=password,
            database=db_name,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

# ==========================================
# 🚀 🆕 成果物JSONをDBへUPSERT（追記・更新）する関数
# ==========================================
def import_hybrid_items(json_file_path):
    """
    焼き上がった日本語 ＆ ベクトルデータを読み込み、
    重複があれば上書き、なければ新規挿入（UPSERT）します。
    """
    if not os.path.exists(json_file_path):
        print(f"🚨 指定されたファイルが見つかりません: {json_file_path}")
        return

    print(f"📖 {json_file_path} をロード中...")
    with open(json_file_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"🔌 データベースに接続中...")
    connection = get_db_connection()
    
    # 💡 MySQLで最も安全にベクトルを扱うハック：
    # 768次元リストを json.dumps() で文字列化して TEXT/JSON 型に突っ込みます。
    # あとで推薦エンジン側で取り出す時に、json.loads() で一瞬でPythonのリストに戻せます。
    
    # MySQLの標準的なUPSERT構文（ON DUPLICATE KEY UPDATE）
    sql = """
        INSERT INTO products (
            asin, name_en, name, ai_category, price, 
            description_en, description, image_url, embedding
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            description = VALUES(description),
            embedding = VALUES(embedding);
    """

    success_count = 0
    try:
        with connection.cursor() as cursor:
            for item in items:
                # 768次元のfloat配列を文字列にキャスト
                embedding_str = json.dumps(item["embedding"])
                
                params = (
                    item["asin"],
                    item["name_en"],
                    item["name"],
                    item["ai_category"],
                    item["price"],
                    item["description_en"],
                    item["description"],
                    item["image_url"],
                    embedding_str
                )
                cursor.execute(sql, params)
                success_count += 1
                
        # コミットして物理ディスクに完全に書き込む
        connection.commit()
        print(f"✨ 成功：{success_count} 件の商品データをインポート/更新しました！")
        
    except Exception as e:
        connection.rollback()
        print(f"🚨 データベース書き込み中にエラーが発生しました。ロールバックします: {e}")
    finally:
        connection.close()

# 💡 ターミナルからこのスクリプトを直接叩いてインポートできるようにする機構
if __name__ == "__main__":
    # コマンドライン引数にファイル名が指定されているかチェック
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
        import_hybrid_items(target_file)
    else:
        print("💡 使い方: python3 db.py [インポートしたいJSONファイル名]")