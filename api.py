from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
import database as db
import sqlite3
import pandas as pd
import uvicorn
import os

# building the decoupled microservice layer for WHI demo
app=FastAPI(title="Smart Parking API")
@app.on_event("startup")
def startup():db.init_db()
# Pydantic schemas enforce strict data validation from Streamlit
class VehicleData(BaseModel):
    plate_text:str
    v_type:str
    img_path:str=None
    gate_mode:str="Auto"
class ConfigData(BaseModel):
    floors:int;cars:int;bikes:int;c_rate:float;b_rate:float;wiggle:int
class SpecialPlate(BaseModel):
    plate:str;category:str;note:str
@app.get("/spots/{v_type}")
def get_spots(v_type:str):
    occ,lim=db.get_free_spots(v_type)
    return {"occupied":occ,"limit":lim}
@app.post("/vehicle")
def log_vehicle(data:VehicleData):
    status,msg,rec=db.handle_vehicle(data.plate_text,data.v_type,data.img_path,data.gate_mode)
    if status=="Error":raise HTTPException(status_code=400,detail=msg)
    return {"status":status,"message":msg,"receipt":rec}
@app.get("/revenue")
def get_revenue():return {"revenue":db.get_total_revenue()}
@app.get("/config")
def get_config():return {"config":db.get_config()}
@app.post("/config")
def update_config(data:ConfigData):
    db.update_config(data.floors,data.cars,data.bikes,data.c_rate,data.b_rate,data.wiggle)
    return {"message":"success"}
@app.get("/special")
def get_special():return {"plates":db.get_all_special_plates()}
@app.post("/special")
def add_special(data:SpecialPlate):
    db.add_special_plate(data.plate,data.category,data.note)
    return {"message":"success"}
@app.delete("/special/{plate}")
def del_special(plate:str):
    db.remove_special_plate(plate)
    return {"message":"success"}
@app.get("/special/{plate}")
def get_special_plate(plate:str):
    res=db.get_special_plate(plate)
    if res:return {"category":res[0],"note":res[1]}
    return None
# endpoints to serve pandas dataframes to the frontend analytics
@app.get("/logs/active")
def get_active():
    conn=sqlite3.connect(db.DB_NAME)
    df=pd.read_sql_query("SELECT * FROM active_parking",conn)
    conn.close()
    return df.to_dict(orient="records")
@app.get("/logs/history")
def get_history():
    conn=sqlite3.connect(db.DB_NAME)
    df=pd.read_sql_query("SELECT * FROM transaction_history ORDER BY id DESC",conn)
    conn.close()
    return df.to_dict(orient="records")
@app.post("/reset")
def factory_reset():
    try:os.remove("parking.db")
    except:pass
    db.init_db()
    return {"message":"Database reset"}
if __name__=="__main__":
    # local server on port 8000
    uvicorn.run(app,host="0.0.0.0",port=8000)
@app.get("/special/{plate}")
def get_special_plate(plate:str):
    print(f"DEBUG: Checking blacklist for {plate}") # Add this 
    res=db.get_special_plate(plate)
    return {"category":res[0],"note":res[1]} if res else None
# ... inside api.py ...
@app.get("/special/{plate}")
def get_special_plate(plate:str):
    res=db.get_special_plate(plate)
    # return a structured object for the frontend to parse easily
    if res:return {"category":res[0],"note":res[1]}
    return None