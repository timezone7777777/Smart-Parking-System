import sqlite3
from datetime import datetime
import math

DB_NAME="parking.db"

def init_db():
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    # Using WAL mode to prevent database locks during high-frequency API calls
    # Honestly, WAL mode saves us from so many locking headaches when the UI is polling
    c.execute("PRAGMA journal_mode=WAL")
    
    c.execute('''CREATE TABLE IF NOT EXISTS parking_config(id INTEGER PRIMARY KEY,total_floors INTEGER,car_slots INTEGER,bike_slots INTEGER,car_rate REAL,bike_rate REAL,wiggle_min INTEGER)''')
    
    # We added slot_number here so we can track the physical location on the 2D map
    c.execute('''CREATE TABLE IF NOT EXISTS active_parking(id INTEGER PRIMARY KEY,plate_number TEXT UNIQUE,vehicle_type TEXT,entry_time TEXT,image_path TEXT, slot_number INTEGER)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transaction_history(id INTEGER PRIMARY KEY,plate_number TEXT,vehicle_type TEXT,entry_time TEXT,exit_time TEXT,duration_min REAL,total_fee REAL,image_path TEXT)''')
    
    # This table handles both VIPs (gold highlight/free) and Blacklisted (security alerts)
    c.execute('''CREATE TABLE IF NOT EXISTS special_plates(plate_text TEXT PRIMARY KEY,category TEXT,note TEXT)''')
    
    c.execute("SELECT count(*) FROM parking_config")
    if c.fetchone()[0]==0:
        c.execute("INSERT INTO parking_config VALUES(1,2,16,10,20.0,10.0,5)")
    conn.commit()
    conn.close()

def get_config():
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("SELECT * FROM parking_config")
    cfg=c.fetchone()
    conn.close()
    return cfg

def update_config(floors,cars,bikes,c_rate,b_rate,wiggle):
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("UPDATE parking_config SET total_floors=?,car_slots=?,bike_slots=?,car_rate=?,bike_rate=?,wiggle_min=? WHERE id=1",(floors,cars,bikes,c_rate,b_rate,wiggle))
    conn.commit()
    conn.close()

def get_free_spots(v_type):
    cfg=get_config()
    limit=cfg[2] if v_type=='car' else cfg[3]
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("SELECT count(*) FROM active_parking WHERE vehicle_type=?",(v_type,))
    occupied=c.fetchone()[0]
    conn.close()
    return occupied,limit

# Let's grab the first available physical spot integer for the map
def get_free_spot_id(v_type):
    cfg = get_config()
    limit = cfg[2] if v_type == 'car' else cfg[3]
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT slot_number FROM active_parking WHERE vehicle_type=?", (v_type,))
    occupied_slots = [row[0] for row in c.fetchall() if row[0] is not None]
    conn.close()
    
    # Just loop through until we find a number that isn't taken
    for i in range(1, limit + 1):
        if i not in occupied_slots:
            return i
    return None

def get_special_plate(plate_text):
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    # Case-insensitive check to ensure alerts fire regardless of OCR casing
    c.execute("SELECT category,note FROM special_plates WHERE UPPER(plate_text)=?",(plate_text.upper(),))
    res=c.fetchone()
    conn.close()
    return res

def add_special_plate(plate,category,note):
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("REPLACE INTO special_plates (plate_text,category,note) VALUES(?,?,?)",(plate.upper(),category,note))
    conn.commit()
    conn.close()

def remove_special_plate(plate):
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("DELETE FROM special_plates WHERE UPPER(plate_text)=?",(plate.upper(),))
    conn.commit()
    conn.close()

def get_all_special_plates():
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("SELECT * FROM special_plates")
    res=c.fetchall()
    conn.close()
    return res

def handle_vehicle(plate_text,v_type,img_path=None,gate_mode="Auto"):
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("SELECT * FROM active_parking WHERE plate_number=?",(plate_text,))
    existing=c.fetchone()
    special=get_special_plate(plate_text)
    is_vip=special and special[0]=='VIP'
    
    # Enforcement for Multi-Gate: Exit gate cannot log a new entry, and vice versa
    if gate_mode=="Entry" and existing:
        conn.close()
        return "Error",f"{plate_text} is already logged inside.",None
    if gate_mode=="Exit" and not existing:
        conn.close()
        return "Error",f"{plate_text} has no entry record.",None
        
    if existing and gate_mode in ["Exit","Auto"]:
        entry_time_str=existing[3]
        entry_img=existing[4]
        entry_time=datetime.strptime(entry_time_str,"%Y-%m-%d %H:%M:%S")
        total_fee,duration,exit_time=calculate_fee(entry_time,v_type)
        if is_vip:total_fee=0.0 # CEO/VIP cars are set to $0 fee automatically
        
        c.execute("DELETE FROM active_parking WHERE plate_number=?",(plate_text,))
        c.execute("INSERT INTO transaction_history(plate_number,vehicle_type,entry_time,exit_time,duration_min,total_fee,image_path) VALUES(?,?,?,?,?,?,?)",(plate_text,v_type,entry_time_str,exit_time.strftime("%Y-%m-%d %H:%M:%S"),duration,total_fee,entry_img))
        conn.commit()
        conn.close()
        return "Exit","Vehicle Exited",{"fee":total_fee,"time":duration,"is_vip":is_vip}
        
    elif not existing and gate_mode in ["Entry","Auto"]:
        occupied,limit=get_free_spots(v_type)
        if occupied>=limit:
            conn.close()
            return "Error",f"No {v_type} spots available!",None
            
        # We assign the physical slot ID right as they enter
        assigned_slot = get_free_spot_id(v_type)
        entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("INSERT INTO active_parking(plate_number,vehicle_type,entry_time,image_path,slot_number) VALUES(?,?,?,?,?)",(plate_text,v_type,entry_time,img_path,assigned_slot))
        conn.commit()
        conn.close()
        return "Entry","Vehicle Entered",{"is_vip":is_vip, "slot": assigned_slot}
        
    conn.close()
    return "Error","Invalid gate operation",None

def calculate_fee(entry_time,vehicle_type):
    cfg=get_config()
    rate=cfg[4] if vehicle_type=='car' else cfg[5]
    wiggle=cfg[6]
    exit_time=datetime.now()
    duration_sec=(exit_time-entry_time).total_seconds()
    duration_min=round(duration_sec/60,2)
    
    # Standard 1-hour minimum charge block
    if duration_min<=60:billable_hours=1
    else:
        # Subtract wiggle room minutes before rounding up to the next hour
        adjusted_min=duration_min-wiggle
        if adjusted_min<=0:billable_hours=0
        else:billable_hours=math.ceil(adjusted_min/60)
        
    total_fee=billable_hours*rate
    return total_fee,duration_min,exit_time

def get_total_revenue():
    conn=sqlite3.connect(DB_NAME)
    c=conn.cursor()
    c.execute("SELECT SUM(total_fee) FROM transaction_history")
    result=c.fetchone()[0]
    conn.close()
    return result if result else 0.0