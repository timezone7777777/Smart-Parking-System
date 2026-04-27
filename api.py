from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3
import time
from datetime import datetime
import os
import receipt_gen
import math

app = FastAPI()
DB_PATH = "parking.db"

# --- DATABASE INITIALIZATION ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Ensure WAL mode for high-concurrency
    cursor.execute("PRAGMA journal_mode=WAL")
    
    # Active Parking
    cursor.execute('''CREATE TABLE IF NOT EXISTS active_parking (
        plate_text TEXT PRIMARY KEY,
        v_type TEXT,
        entry_time TEXT,
        img_path TEXT,
        slot_number INTEGER
    )''')
    
    # History
    cursor.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plate_number TEXT,
        vehicle_type TEXT,
        entry_time TEXT,
        exit_time TEXT,
        duration_min REAL,
        total_fee REAL,
        image_path TEXT,
        receipt_path TEXT
    )''')
    
    # Security/VIP table
    cursor.execute('''CREATE TABLE IF NOT EXISTS special_plates (
        plate TEXT PRIMARY KEY,
        category TEXT,
        note TEXT
    )''')
    
    # Settings/Config table (Updated to 7 columns to include free_minutes)
    cursor.execute('''CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY,
        floors INTEGER,
        car_limit INTEGER,
        bike_limit INTEGER,
        car_rate REAL,
        bike_rate REAL,
        free_minutes INTEGER
    )''')
    
    # Default Config: 1 Floor, 10 Cars, 5 Bikes, $20/hr, $10/hr, 5 Min Wiggle Room
    cursor.execute("INSERT OR IGNORE INTO config VALUES (1, 1, 10, 5, 20.0, 10.0, 5)")
    
    conn.commit()
    conn.close()

init_db()

# --- DATA MODELS & HELPERS ---
class VehicleLog(BaseModel):
    plate_text: str
    v_type: str
    img_path: str
    gate_mode: str

def get_config():
    conn = sqlite3.connect(DB_PATH)
    cfg = conn.execute("SELECT * FROM config WHERE id=1").fetchone()
    conn.close()
    return cfg

def get_free_slot(v_type, limit):
    conn = sqlite3.connect(DB_PATH)
    occupied = [r[0] for r in conn.execute("SELECT slot_number FROM active_parking WHERE v_type=?", (v_type,)).fetchall()]
    conn.close()
    for s in range(1, limit + 1):
        if s not in occupied: 
            return s
    return None

# --- CORE LOGIC ENDPOINT ---
@app.post("/vehicle")
async def process_vehicle(data: VehicleLog):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cfg = get_config()
    
    # Check if vehicle is already inside
    current = cursor.execute("SELECT * FROM active_parking WHERE plate_text=?", (data.plate_text,)).fetchone()
    
    # LOGIC: EXIT
    if current and data.gate_mode in ["Exit", "Auto"]:
        entry_time_str = current[2]
        saved_img_path = current[3]
        v_type = current[1]
        slot_num = current[4]
        
        # Calculate Time & Wiggle Room
        entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
        exit_now = datetime.now()
        total_duration = (exit_now - entry_dt).total_seconds() / 60
        
        free_minutes = cfg[6]
        billable_duration = max(0, total_duration - free_minutes)
        rate = cfg[4] if v_type == "car" else cfg[5]
        
        # Check if VIP (Free parking)
        is_vip = cursor.execute("SELECT 1 FROM special_plates WHERE plate=? AND category='VIP'", (data.plate_text,)).fetchone()
        billable_hours = math.ceil(billable_duration / 60) if billable_duration > 0 else 0
        fee = 0.0 if is_vip else float(billable_hours * rate)
        
        # 1. GENERATE VISUAL RECEIPT
        exit_str = exit_now.strftime('%Y-%m-%d %H:%M:%S')
        receipt_path = receipt_gen.generate_receipt(
            data.plate_text, v_type, entry_time_str, exit_str, total_duration, fee, saved_img_path
        )
        
        # 2. MOVE TO HISTORY
        cursor.execute('''INSERT INTO history 
            (plate_number, vehicle_type, entry_time, exit_time, duration_min, total_fee, image_path, receipt_path) 
            VALUES (?,?,?,?,?,?,?,?)''', 
            (data.plate_text, v_type, entry_time_str, exit_str, total_duration, fee, data.img_path, receipt_path))
        
        # 3. REMOVE FROM ACTIVE
        cursor.execute("DELETE FROM active_parking WHERE plate_text=?", (data.plate_text,))
        
        conn.commit()
        conn.close()
        
        return {
            "status": "Exit", 
            "message": f"Goodbye {data.plate_text}", 
            "receipt": {"fee": fee, "time": total_duration, "is_vip": bool(is_vip), "path": receipt_path}
        }

    # LOGIC: ENTRY
    elif not current and data.gate_mode in ["Entry", "Auto"]:
        limit = cfg[2] if data.v_type == "car" else cfg[3]
        slot = get_free_slot(data.v_type, limit)
        
        if slot is None:
            conn.close()
            return {"status": "Full", "message": f"No {data.v_type} slots available"}
        
        entry_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("INSERT INTO active_parking VALUES (?,?,?,?,?)", 
                       (data.plate_text, data.v_type, entry_now, data.img_path, slot))
        
        is_vip = cursor.execute("SELECT 1 FROM special_plates WHERE plate=? AND category='VIP'", (data.plate_text,)).fetchone()
        
        conn.commit()
        conn.close()
        
        return {"status": "Entry", "message": f"Welcome {data.plate_text}", "receipt": {"is_vip": bool(is_vip), "slot": slot}}

    conn.close()
    return {"status": "Stay", "message": "Vehicle already logged or gate mismatch"}

# --- UTILITY ENDPOINTS ---
@app.get("/map/active")
async def get_active_map():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT slot_number, plate_text, v_type FROM active_parking").fetchall()
    conn.close()
    return [{"slot": r[0], "plate": r[1], "type": r[2]} for r in rows]

@app.get("/map/slot/{slot_id}")
async def get_slot_details(slot_id: int):
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute("SELECT plate_text, v_type, entry_time, img_path FROM active_parking WHERE slot_number=?", (slot_id,)).fetchone()
    conn.close()
    if r:
        return {"plate": r[0], "type": r[1], "entry_time": r[2], "image_path": r[3]}
    raise HTTPException(status_code=404, detail="Slot empty")

@app.get("/spots/{v_type}")
async def get_spots(v_type: str):
    cfg = get_config()
    limit = cfg[2] if v_type == "car" else cfg[3]
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM active_parking WHERE v_type=?", (v_type,)).fetchone()[0]
    conn.close()
    return {"occupied": count, "limit": limit}

@app.get("/revenue")
async def get_revenue():
    conn = sqlite3.connect(DB_PATH)
    rev = conn.execute("SELECT SUM(total_fee) FROM history WHERE date(exit_time) = date('now')").fetchone()[0]
    conn.close()
    return {"revenue": rev if rev else 0.0}

@app.get("/config")
async def fetch_config():
    return {"config": get_config()}

@app.post("/config")
async def update_config(data: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        UPDATE config 
        SET floors=?, car_limit=?, bike_limit=?, car_rate=?, bike_rate=?, free_minutes=? 
        WHERE id=1
    ''', (data['floors'], data['cars'], data['bikes'], data['c_rate'], data['b_rate'], data['wiggle']))
    conn.commit()
    conn.close()
    return {"msg": "Config updated"}

@app.post("/reset")
async def reset_db():
    # Only drops the tracking tables, keeps config
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS active_parking")
    conn.execute("DROP TABLE IF EXISTS history")
    conn.commit()
    conn.close()
    init_db() # Rebuild them empty
    return {"msg": "Database reset"}

@app.post("/special")
async def add_special(data: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO special_plates VALUES (?,?,?)", (data['plate'], data['category'], data['note']))
    conn.commit()
    conn.close()
    return {"msg": "Success"}

@app.get("/special/{plate}")
async def check_special(plate: str):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT category, note FROM special_plates WHERE plate=?", (plate,)).fetchone()
    conn.close()
    if res: return {"category": res[0], "note": res[1]}
    return None

@app.get("/special")
async def list_special():
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT * FROM special_plates").fetchall()
    conn.close()
    return {"plates": res}

@app.delete("/special/{plate}")
async def del_special(plate: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM special_plates WHERE plate=?", (plate,))
    conn.commit()
    conn.close()
    return {"msg": "Deleted"}

@app.get("/logs/active")
async def get_active_logs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT plate_text, v_type, entry_time, slot_number, img_path FROM active_parking").fetchall()
    conn.close()
    return [{"plate_number": r[0], "vehicle_type": r[1], "entry_time": r[2], "slot_number": r[3], "image_path": r[4]} for r in rows]

@app.get("/logs/history")
async def get_history_logs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT plate_number, vehicle_type, entry_time, exit_time, duration_min, total_fee, image_path, receipt_path FROM history ORDER BY id DESC").fetchall()
    conn.close()
    return [{"plate_number": r[0], "vehicle_type": r[1], "entry_time": r[2], "exit_time": r[3], "duration_min": r[4], "total_fee": r[5], "image_path": r[6], "receipt_path": r[7]} for r in rows]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)