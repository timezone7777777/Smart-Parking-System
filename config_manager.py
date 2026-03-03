import streamlit as st
import requests
import time
API_URL="http://localhost:8000"
def render_sidebar_status(placeholder):
    with placeholder.container():
        c_req=requests.get(f"{API_URL}/spots/car").json()
        b_req=requests.get(f"{API_URL}/spots/bike").json()
        cfg=requests.get(f"{API_URL}/config").json()["config"]
        cars_in,car_limit=c_req['occupied'],c_req['limit']
        bikes_in,bike_limit=b_req['occupied'],b_req['limit']
        total_floors=cfg[1] if cfg[1]>0 else 1
        st.subheader("Live Availability")
        st.write(f"**Cars:** {car_limit-cars_in} free")
        car_spots_per_floor=car_limit//total_floors
        for f in range(1,total_floors+1):
            floor_cap=car_spots_per_floor
            prev_occupancy=(f-1)*floor_cap
            remaining=cars_in-prev_occupancy
            on_this_floor=max(0,min(remaining,floor_cap))
            pct=on_this_floor/floor_cap if floor_cap>0 else 0
            st.caption(f"Floor {f}: {floor_cap-on_this_floor} free")
            st.progress(pct)
        st.markdown("---")
        st.write(f"**Bikes:** {bike_limit-bikes_in} free")
        bike_spots_per_floor=bike_limit//total_floors
        for f in range(1,total_floors+1):
            floor_cap=bike_spots_per_floor
            prev_occupancy=(f-1)*floor_cap
            remaining=bikes_in-prev_occupancy
            on_this_floor=max(0,min(remaining,floor_cap))
            pct=on_this_floor/floor_cap if floor_cap>0 else 0
            st.caption(f"Floor {f}: {floor_cap-on_this_floor} free")
            st.progress(pct)
        st.markdown("---")
def render_config_page():
    st.header("System Configuration")
    cfg=requests.get(f"{API_URL}/config").json()["config"]
    with st.form("config_form"):
        c1,c2=st.columns(2)
        with c1:
            st.subheader("Parking Capacity")
            new_floors=st.number_input("Total Floors",min_value=1,value=cfg[1])
            new_cars=st.number_input("Car Slots",min_value=1,value=cfg[2])
            new_bikes=st.number_input("Bike Slots",min_value=1,value=cfg[3])
        with c2:
            st.subheader("Billing Rates ($/hr)")
            new_car_rate=st.number_input("Car Rate",min_value=0.0,value=cfg[4])
            new_bike_rate=st.number_input("Bike Rate",min_value=0.0,value=cfg[5])
            new_wiggle=st.number_input("Free Minutes (Entry/Exit)",min_value=0,value=cfg[6])
        if st.form_submit_button("Save Settings"):
            payload={"floors":new_floors,"cars":new_cars,"bikes":new_bikes,"c_rate":new_car_rate,"b_rate":new_bike_rate,"wiggle":new_wiggle}
            requests.post(f"{API_URL}/config",json=payload)
            st.success("Configuration updated!")
            time.sleep(1)
            st.rerun() 
    st.markdown("---")
    st.subheader("Danger Zone")
    st.warning("Resetting the database will delete all history and active logs.")
    if st.button("FACTORY RESET DATABASE"):
        requests.post(f"{API_URL}/reset")
        st.success("New Database created! System is fresh.")
        time.sleep(1.5)
        st.rerun()