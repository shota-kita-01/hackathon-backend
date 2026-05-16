import os
import pymysql
from fastapi import FastAPI

app = FastAPI()

def get_db_connection():
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PWD")
    db_name = os.getenv("MYSQL_DATABASE")
    host_env = os.getenv("MYSQL_HOST", "")
    
    # Cloud Run環境（Unixドメインソケット）かローカル環境（IPアドレス）かを自動判定
    if host_env.startswith("unix("):
        # unix(/cloudsql/接続名) -> /cloudsql/接続名 の形にパース
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

@app.get("/")
def read_root():
    return {"message": "Hello from Cloud Run (Python)!"}

# マニュアルの最後にある「SELECTが行えることの確認」用のエンドポイント
@app.get("/users")
def get_users():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, age FROM user")
            result = cursor.fetchall()
            return result
    finally:
        connection.close()