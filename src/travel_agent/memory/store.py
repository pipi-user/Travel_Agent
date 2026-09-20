 # SQLite 用户画像存储
import sqlite3
import json
import os

DB_PATH = "data/travel_memory.db"
os.makedirs("data", exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            allergies TEXT DEFAULT '[]',
            fears TEXT DEFAULT '[]',
            dietary TEXT DEFAULT '[]',
            pace_preference TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def load_profile(user_id: str) -> dict:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT allergies, fears, dietary, pace_preference FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {"allergies": [], "fears": [], "dietary": [], "pace_preference": None}
    return {
        "allergies": json.loads(row[0]),
        "fears": json.loads(row[1]),
        "dietary": json.loads(row[2]),
        "pace_preference": row[3]
    }

def save_profile(user_id: str, profile: dict):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO user_profiles (user_id, allergies, fears, dietary, pace_preference)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            allergies = excluded.allergies,
            fears = excluded.fears,
            dietary = excluded.dietary,
            pace_preference = excluded.pace_preference
    """, (user_id, json.dumps(profile.get("allergies", [])), json.dumps(profile.get("fears", [])), json.dumps(profile.get("dietary", [])), profile.get("pace_preference")))
    conn.commit()
    conn.close()