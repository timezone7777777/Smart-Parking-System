import streamlit as st
import requests
import pandas as pd

# Optimized for mobile viewing
st.set_page_config(page_title="Smart Parking Live", layout="centered", initial_sidebar_state="collapsed")

# Hide the Streamlit top menu and footer for a cleaner "app" feel
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

API_URL = "http://localhost:8000"

st.title("Live Parking Status")
st.markdown("Check availability before you arrive or find your parked vehicle.")

# --- LIVE AVAILABILITY ---
try:
    c_req = requests.get(f"{API_URL}/spots/car", timeout=2).json()
    b_req = requests.get(f"{API_URL}/spots/bike", timeout=2).json()
    
    car_free = c_req['limit'] - c_req['occupied']
    bike_free = b_req['limit'] - b_req['occupied']
    
    col1, col2 = st.columns(2)
    
    # Traffic Light Color Logic: Green if spots exist, Red if full
    with col1:
        car_color = "#2e7d32" if car_free > 0 else "#c62828"
        st.markdown(f"<div style='text-align: center; padding: 20px; border-radius: 10px; background-color: {car_color}; color: white;'><h2>CARS</h2><h1>{car_free}</h1><p>Spots Available</p></div>", unsafe_allow_html=True)
        
    with col2:
        bike_color = "#2e7d32" if bike_free > 0 else "#c62828"
        st.markdown(f"<div style='text-align: center; padding: 20px; border-radius: 10px; background-color: {bike_color}; color: white;'><h2>BIKES</h2><h1>{bike_free}</h1><p>Spots Available</p></div>", unsafe_allow_html=True)
        
except Exception as e:
    st.error("System currently offline. Please try again later.")

st.markdown("---")

# --- FIND MY CAR ---
st.subheader("Find My Vehicle")
search_plate = st.text_input("Enter your License Plate (e.g., DL8C...)").strip().upper()

if search_plate:
    try:
        active_data = requests.get(f"{API_URL}/logs/active", timeout=2).json()
        df_active = pd.DataFrame(active_data) if active_data else pd.DataFrame()
        
        if not df_active.empty and search_plate in df_active['plate_number'].values:
            car_info = df_active[df_active['plate_number'] == search_plate].iloc[0]
            st.success(f"**Vehicle Found!**\n\nIt is currently parked safely in **Slot {car_info['slot_number']}**.")
        else:
            st.warning("Vehicle not found. Please verify your plate number.")
    except:
        st.error("Could not search for vehicle at this time.")
#python -m streamlit run driver_app.py --server.address 0.0.0.0 (your ipv4 address)--server.port 8502
#http://0.0.0.0:850/