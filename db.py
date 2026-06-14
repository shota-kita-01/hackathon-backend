import os
import json
import sys
import pymysql
from google import genai  

# ==========================================
# 設定
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")

if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# Geminiクライアントの初期化
client = genai.Client(http_options={'api_version': 'v1'})

# データベース接続関数
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
        # 💡 ここで .env から読み込んだパブリックIPが正確に適用されるようになります！
        return pymysql.connect(
            host=host_env or "127.0.0.1",
            user=user,
            password=password,
            database=db_name,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

# ==========================================
# 成果物JSONをDBへUPSERT
# ==========================================
def import_hybrid_items(json_file_path):
    """
    焼き上がった日本語 ＆ ベクトルデータを読み込み、
    重複があれば上書き、なければ新規挿入（UPSERT）します。
    """
    if not os.path.exists(json_file_path):
        print(f"指定されたファイルが見つかりません: {json_file_path}")
        return

    print(f"📖 {json_file_path} をロード中...")
    with open(json_file_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"クラウドデータベース（Cloud SQL）に接続中...")
    connection = get_db_connection()
    
    # MySQLの標準的なUPSERT構文
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
            print("古いカタログデータの残党を完全にクレンジング中...")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE products;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            
            for item in items:
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
                
        connection.commit()
        print(f"成功：{success_count} 件の商品データを Cloud SQL へインポートしました！")
        
    except Exception as e:
        connection.rollback()
        print(f"データベース書き込み中にエラーが発生しました。ロールバックします: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
        import_hybrid_items(target_file)
    else:
        print("使い方: python3 db.py [インポートしたいJSONファイル名]")