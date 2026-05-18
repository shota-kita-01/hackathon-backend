from fastapi import APIRouter, HTTPException
from db import get_db_connection
from schemas import UserRegister, LoginData

router = APIRouter()

@router.post("/api/register")
def register_user(user_data: UserRegister):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="このメールアドレスは既に登録されています")
            
            sql = "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)"
            cursor.execute(sql, (user_data.name, user_data.email, user_data.password))
            connection.commit()
            return {"status": "success", "message": "ユーザー登録が完了しました！"}
    finally:
        connection.close()

@router.get("/api/users")
def get_users():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, email FROM users")
            return cursor.fetchall()
    finally:
        connection.close()

@router.post("/api/auth/login")
def auth_login(data: LoginData):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE firebase_uid = %s", (data.firebase_uid,))
            user = cursor.fetchone()
            if user: return {"status": "success", "id": user["id"]}
            
            cursor.execute("SELECT id FROM users WHERE email = %s", (data.email,))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.execute("UPDATE users SET firebase_uid = %s WHERE id = %s", (data.firebase_uid, existing_user["id"]))
                connection.commit()
                return {"status": "success", "id": existing_user["id"]}
            
            cursor.execute("INSERT INTO users (name, email, firebase_uid, password_hash) VALUES (%s, %s, %s, %s)", (data.name, data.email, data.firebase_uid, ""))
            connection.commit()
            return {"status": "success", "id": cursor.lastrowid}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()