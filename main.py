import streamlit as st
import cv2
import pandas as pd
import requests
import time
import numpy as np
import os
import config_manager as cm
import detector as det
import utils
import base64
import altair as alt
import qrcode
import socket
from io import BytesIO

st.set_page_config(page_title="High-Performance Parking System",layout="wide")
API_URL="http://localhost:8000"

# Initialize session states for tracking and sync
if 'last_processed' not in st.session_state:st.session_state['last_processed']=0
if 'last_metric_sync' not in st.session_state:st.session_state['last_metric_sync']=0 
if 'processed_tracks' not in st.session_state:st.session_state['processed_tracks']=set()

os.makedirs("captured_plates",exist_ok=True)

def get_img_as_base64(file_path):
    with open(file_path,"rb") as f:data=f.read()
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"

st.sidebar.title("Parking Management")
page=st.sidebar.radio("Navigate",["Dashboard","Map View","Settings","History","Security","Analytics"])
is_gpu,device_name=utils.check_gpu()
st.sidebar.success(f"Running on: {device_name}")

# Verify API status
try:requests.get(f"{API_URL}/revenue", timeout=1)
except:st.sidebar.error("API SERVER OFFLINE. Run 'python api.py' in a new terminal.")

if page=="Dashboard":
    st.title("Real-Time AI Dashboard")
    col1,col2,col3=st.columns(3)
    m1,m2,m3=col1.empty(),col2.empty(),col3.empty()
    sidebar_placeholder=st.sidebar.empty()

    def refresh_metrics(force=False):
        curr=time.time()
        # Throttled polling: Only hit API if forced or 2 seconds elapsed
        if force or (curr-st.session_state['last_metric_sync']>2):
            try:
                c_req=requests.get(f"{API_URL}/spots/car",timeout=0.5).json()
                b_req=requests.get(f"{API_URL}/spots/bike",timeout=0.5).json()
                rev_req=requests.get(f"{API_URL}/revenue",timeout=0.5).json()
                m1.metric("Car Spaces Left",f"{c_req['limit']-c_req['occupied']}",f"{c_req['occupied']} Occupied",delta_color="inverse")
                m2.metric("Bike Spaces Left",f"{b_req['limit']-b_req['occupied']}",f"{b_req['occupied']} Occupied",delta_color="inverse")
                m3.metric("Today's Revenue",f"${rev_req['revenue']:.2f}")
                cm.render_sidebar_status(sidebar_placeholder)
                st.session_state['last_metric_sync']=curr
            except:pass 

    # Initial UI render
    refresh_metrics(force=True)
    st.markdown("---")
    
    c_src,c_gate=st.columns(2)
    with c_src:source=st.radio("Select Input Source",["Image","Video","Webcam"],horizontal=True)
    with c_gate:gate_type=st.radio("Gate Role",["Entry Gate","Exit Gate","Auto (Combined)"],horizontal=True)
    gate_mode=gate_type.split()[0] 

    col_video,col_stats=st.columns([0.7,0.3])
    with col_video:
        st.subheader(f"Live Feed: {gate_type}")
        frame_window=st.empty()
    with col_stats:
        st.subheader("System Activity")
        event_box=st.empty()

    cap,stop_btn=None,False
    
    # We need to make sure the image upload goes through the same security check as the video feed
    if source=="Image":
        up_file=st.file_uploader("Upload Image",type=['jpg','png','jpeg'])
        if up_file:
            file_bytes=np.asarray(bytearray(up_file.read()),dtype=np.uint8)
            frame=cv2.imdecode(file_bytes,1)
            processed_frame,data=det.detect_frame(frame,set())
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            
            if data:
                # 1. SECURITY CHECK: Hit the API to check special plates first
                r_spec = requests.get(f"{API_URL}/special/{data['text']}").json()
                
                # 2. TRIGGER ALERT: If category is Blacklist, show error and STOP
                if r_spec and r_spec.get("category") == 'Blacklist':
                    event_box.error(f"SECURITY ALERT: Blacklisted Vehicle!\nPlate: {data['text']} | Reason: {r_spec.get('note')}")
                    # Stop here, do not log the entry
                else:
                    # 3. NORMAL LOGGING: Only runs if NOT blacklisted
                    img_path=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                    cv2.imwrite(img_path,processed_frame)
                    payload={"plate_text":data['text'],"v_type":data['type'],"img_path":img_path,"gate_mode":gate_mode}
                    res=requests.post(f"{API_URL}/vehicle",json=payload)
                    api_data=res.json()
                    status=api_data.get("status","Error")
                    msg=api_data.get("message",api_data.get("detail"))
                    rec=api_data.get("receipt",None)
                    refresh_metrics(force=True)
                    
                    if status=="Entry":
                        if rec and rec.get("is_vip"):
                            event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>VIP ENTRY: {data['text']}</b></div>",unsafe_allow_html=True)
                        else:
                            event_box.success(f"ENTRY: {data['text']}")
                    elif status=="Exit":
                        if rec and rec.get("is_vip"):
                            event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>VIP EXIT: {data['text']} | Fee: $0.00</b></div>",unsafe_allow_html=True)
                        else:
                            event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}")
                    else:
                        event_box.error(msg)
    
    elif source=="Video":
        up_video=st.file_uploader("Upload Video",type=['mp4','webm'])
        if up_video:
            ext=up_video.name.split('.')[-1]
            with open(f"temp.{ext}","wb") as f:f.write(up_video.read())
            cap=cv2.VideoCapture(f"temp.{ext}")
            stop_btn=st.button("Stop Video Processing")
    
    elif source=="Webcam":
        if st.button("Start Camera"):
            cap=cv2.VideoCapture(0)
            stop_btn=st.button("Stop Camera")

    if cap:
        while cap.isOpened():
            ret,frame=cap.read()
            if not ret or stop_btn:break
            processed_frame,data=det.detect_frame(frame,st.session_state['processed_tracks'])
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            if data:
                # 1. SECURITY CHECK: Hit the API to check special plates first 
                r_spec=requests.get(f"{API_URL}/special/{data['text']}").json()
                
                # 2. TRIGGER ALERT: If category is Blacklist, show error and STOP 
                if r_spec and r_spec.get("category") == 'Blacklist':
                    event_box.error(f"SECURITY ALERT: Blacklisted Vehicle!\nPlate: {data['text']} | Reason: {r_spec.get('note')}")
                    st.session_state['processed_tracks'].add(data['track_id'])
                    continue # This 'continue' prevents the code below from running 
                
                # 3. NORMAL LOGGING: Only runs if NOT blacklisted 
                img_filename=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                cv2.imwrite(img_filename,processed_frame)
                payload={"plate_text":data['text'],"v_type":data['type'],"img_path":img_filename,"gate_mode":gate_mode}
                
                res=requests.post(f"{API_URL}/vehicle",json=payload)
                api_data=res.json()
                
                status=api_data.get("status","Error")
                msg=api_data.get("message",api_data.get("detail"))
                rec=api_data.get("receipt",None)
                
                st.session_state['processed_tracks'].add(data['track_id'])
                refresh_metrics(force=True) # Immediate update after detection
                
                fmt_time=time.strftime('%H:%M:%S',time.localtime())+f".{int((time.time()%1)*100):02d}"
                if status=="Entry":
                    if rec and rec.get("is_vip"):event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>VIP ENTRY: {data['text']}</b></div>",unsafe_allow_html=True)
                    else:event_box.success(f"ENTRY: {data['text']}\nTime: {fmt_time}")
                elif status=="Exit":
                    if rec and rec.get("is_vip"):event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>VIP EXIT: {data['text']} | Fee: $0.00</b></div>",unsafe_allow_html=True)
                    else:event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}\nTime: {rec['time']:.2f} min")
                else:event_box.error(msg)
            
            # Keep background metrics ticking without lagging video
            refresh_metrics(force=False)
        cap.release()

elif page == "Map View":
    st.title("Live Floor Map")
    st.markdown("Click on any occupied slot to inspect the vehicle details and evidence photo.")
    
    view_type = st.radio("Select Parking Lot", ["Cars", "Bikes"], horizontal=True)
    target_type = "car" if view_type == "Cars" else "bike"
    
    # Grab the config so we know how big to draw the grid
    cfg = requests.get(f"{API_URL}/config").json()["config"]
    
    try:
        active_slots_data = requests.get(f"{API_URL}/map/active").json()
        active_slots = {item['slot']: item for item in active_slots_data if item['type'] == target_type}
        
        # NEW: Fetch the special plates list so we know who is a VIP
        special_data = requests.get(f"{API_URL}/special").json().get("plates", [])
        # Extract just the plate numbers that have the 'VIP' category
        vip_plates = [p[0] for p in special_data if p[1] == 'VIP']
    except:
        active_slots = {}
        vip_plates = []

    total_floors = cfg[1] if cfg[1] > 0 else 1
    total_limit = cfg[2] if target_type == "car" else cfg[3]
    
    if total_floors > 0 and total_limit > 0:
        base_slots_per_floor = total_limit // total_floors
        leftover_slots = total_limit % total_floors 
    else:
        base_slots_per_floor = 0
        leftover_slots = 0

    if base_slots_per_floor > 0 or leftover_slots > 0:
        tabs = st.tabs([f"Floor {i}" for i in range(1, total_floors + 1)])
        current_slot_tracker = 1 

        for floor_idx, tab in enumerate(tabs):
            with tab:
                st.markdown("<br>", unsafe_allow_html=True)
                
                slots_this_floor = base_slots_per_floor
                if floor_idx == total_floors - 1:
                    slots_this_floor += leftover_slots
                
                if slots_this_floor > 0:
                    cols_per_row = 4
                    start_slot = current_slot_tracker
                    end_slot = start_slot + slots_this_floor

                    for row_start in range(start_slot, end_slot, cols_per_row):
                        cols = st.columns(cols_per_row)
                        for col_idx, col in enumerate(cols):
                            current_slot = row_start + col_idx
                            
                            if current_slot < end_slot:
                                is_occupied = current_slot in active_slots
                                
                                # NEW: Color-coded LED Status Logic
                                if is_occupied:
                                    plate_txt = active_slots[current_slot]['plate']
                                    if plate_txt in vip_plates:
                                        status_marker = "🟣 [VIP]"
                                    else:
                                        status_marker = "🔴 [OCCUPIED]"
                                    plate_display = f"\n{plate_txt}"
                                else:
                                    status_marker = "🟢 [EMPTY]"
                                    plate_display = ""
                                    
                                btn_label = f"{status_marker} Slot {current_slot}{plate_display}"

                                if col.button(btn_label, key=f"slot_{target_type}_{current_slot}", use_container_width=True):
                                    if is_occupied:
                                        slot_info = requests.get(f"{API_URL}/map/slot/{current_slot}").json()
                                        st.sidebar.markdown("---")
                                        st.sidebar.subheader(f"Slot {current_slot} Details")
                                        st.sidebar.write(f"**Plate:** `{slot_info['plate']}`")
                                        st.sidebar.write(f"**Type:** {slot_info['type'].title()}")
                                        st.sidebar.write(f"**Entry Time:** {slot_info['entry_time']}")
                                        
                                        if slot_info['image_path'] and os.path.exists(slot_info['image_path']):
                                            st.sidebar.image(slot_info['image_path'], caption="Entry Camera Evidence")
                                        else:
                                            st.sidebar.warning("Image evidence not found on disk.")
                                    else:
                                        st.sidebar.markdown("---")
                                        st.sidebar.success(f"Slot {current_slot} is currently vacant and available.")
                        
                        current_slot_tracker = end_slot
    else:
        st.info(f"No {view_type.lower()} slots configured. Check Settings.")

elif page=="Settings":
    # 1. First, render your existing configuration form (from config_manager.py)
    cm.render_config_page()
    
    # 2. Add the QR Section Logic
    st.markdown("---")
    st.subheader("Driver Website Access")
    st.info("Drivers scan this QR code to see live availability on their phones.")

    # Auto-detect your PC's Local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Using Google DNS as a dummy target to find the active network interface
        s.connect(("8.8.8.8", 80)) 
        local_ip = s.getsockname()[0]
        s.close()
    except:
        # Fallback to your currently known IP if detection fails
        local_ip = "10.18.44.132"

    # Build the URL pointing to the Driver App terminal (Port 8502)
    driver_url = f"http://{local_ip}:8502"
    
    st.write(f"**Current Driver URL:** `{driver_url}`")

    # Generate the QR Code image
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(driver_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert the PIL image to bytes so Streamlit can display it
    buf = BytesIO()
    img.save(buf, format="PNG")
    byte_im = buf.getvalue()

    # Layout for QR and Instructions
    col1, col2 = st.columns([0.4, 0.6])
    with col1:
        st.image(byte_im, caption="Scan to open Driver App")
    with col2:
        st.write("### Instructions for Drivers")
        st.markdown(f"""
        1. **Connect:** Ensure your phone is on the same Hotspot.
        2. **Scan:** Open your camera and scan the code.
        3. **Browse:** If the browser doesn't open, manually type:  
           `{driver_url}`
        """)
        st.warning("Keep the `driver_app.py` terminal running on port 8502 for this link to work!")

elif page=="History":
    st.header("Financial & Parking Logs")
    
    # 1. Fetch Data from API SAFELY
    try:
        a_data=requests.get(f"{API_URL}/logs/active").json()
        h_data=requests.get(f"{API_URL}/logs/history").json()
    except:
        st.error("API Error: Could not fetch database logs. Check your api.py terminal.")
        a_data, h_data = [], []
        
    df_active=pd.DataFrame(a_data) if a_data else pd.DataFrame()
    df_history=pd.DataFrame(h_data) if h_data else pd.DataFrame()
    
    # 2. Global Search Bar
    sq=st.text_input("Search License Plate",placeholder="Type plate number...").strip().upper()
    
    if sq:
        if not df_active.empty:
            df_active=df_active[df_active['plate_number'].str.contains(sq,case=False,na=False)]
        if not df_history.empty:
            df_history=df_history[df_history['plate_number'].str.contains(sq,case=False,na=False)]
    
    # 3. Data Formatting for Visualization
    if not df_active.empty:
        df_active['entry_time']=pd.to_datetime(df_active['entry_time']).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_active['evidence_img']=df_active['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    
    if not df_history.empty:
        for col in ['entry_time','exit_time']:
            df_history[col]=pd.to_datetime(df_history[col]).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_history['evidence_img']=df_history['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)

    # 4. Action Buttons (Refresh & Export)
    cr,cd=st.columns([0.8,0.2])
    with cr:
        if st.button("Refresh History"):st.rerun()
    with cd:
        if not df_history.empty:
            st.download_button("Download CSV",df_history.to_csv(index=False).encode('utf-8'),f"parking_report_{time.strftime('%Y%m%d')}.csv","text/csv")
    
    # 5. Tables Display
    st.subheader("Live Parking Status")
    if df_active.empty and sq:
        st.warning(f"No active vehicle found for '{sq}'")
    else:
        st.data_editor(df_active,column_config={"evidence_img":st.column_config.ImageColumn("Evidence"),"image_path":None,"plate_number":"License Plate","vehicle_type":"Type", "slot_number":"Slot ID"},use_container_width=True,hide_index=True)
    
    st.markdown("---")
    st.subheader("Transaction History")
    if df_history.empty and sq:
        st.warning(f"No history found for '{sq}'")
    elif not df_history.empty:
        st.data_editor(df_history.style.format({"total_fee":"{:.2f}","duration_min":"{:.2f}"}),column_config={"evidence_img":st.column_config.ImageColumn("Entry Photo"),"image_path":None,"plate_number":"License Plate","total_fee":st.column_config.NumberColumn("Fee ($)",format="$%.2f")},use_container_width=True,hide_index=True)
        st.metric("Total Revenue (Filtered)",f"${df_history['total_fee'].sum():.2f}")

    # 6. Receipt Explorer (Integrated with Search)
    st.markdown("---")
    st.subheader("Receipt Explorer")
    if not df_history.empty:
        available_plates = df_history['plate_number'].unique()
        
        # If user searched for a specific plate, we auto-select it in the dropdown
        index_val = 0
        if sq in available_plates:
            index_val = list(available_plates).index(sq)

        selected_plate = st.selectbox("Select Plate to view Receipt", available_plates, index=index_val)
        
        receipt_folder = "receipts"
        if os.path.exists(receipt_folder):
            # Find the generated PNGs for the selected plate
            receipt_files = [f for f in os.listdir(receipt_folder) if selected_plate in f]
            
            if receipt_files:
                # Grab the latest receipt for this plate
                latest_receipt = os.path.join(receipt_folder, receipt_files[-1])
                with open(latest_receipt, "rb") as img_file:
                    st.download_button("Download Receipt Image", img_file, file_name=f"receipt_{selected_plate}.png", key=f"dl_{selected_plate}")
                st.image(latest_receipt, caption=f"Digital Ticket for {selected_plate}", width=350)
            else:
                st.info(f"No digital receipt file found for {selected_plate} in the local directory.")
        else:
            st.warning("Receipts folder not found. A vehicle must exit the lot to generate the first receipt.")
elif page=="Security":
    st.header("Security & VIP Management")
    with st.form("add_special_plate"):
        c1,c2,c3=st.columns(3)
        new_plate=c1.text_input("License Plate").strip().upper()
        new_cat=c2.selectbox("Category",["VIP","Blacklist"])
        new_note=c3.text_input("Note/Reason")
        if st.form_submit_button("Add to System"):
            if new_plate:
                requests.post(f"{API_URL}/special",json={"plate":new_plate,"category":new_cat,"note":new_note})
                st.success(f"Added {new_plate} as {new_cat}")
                time.sleep(1)
                st.rerun()
    st.markdown("---")
    st.subheader("Registered Plates")
    p_data=requests.get(f"{API_URL}/special").json().get("plates",[])
    if p_data:
        df_special=pd.DataFrame(p_data,columns=["Plate","Category","Note"])
        st.dataframe(df_special,use_container_width=True,hide_index=True)
        del_plate=st.selectbox("Select plate to remove",df_special["Plate"])
        if st.button("Remove Plate"):
            requests.delete(f"{API_URL}/special/{del_plate}")
            st.success("Plate removed")
            time.sleep(1)
            st.rerun()
    else:st.info("No special plates registered yet.")

elif page=="Analytics":
    st.header("Business Intelligence")
    a_data=requests.get(f"{API_URL}/logs/active").json()
    h_data=requests.get(f"{API_URL}/logs/history").json()
    df_active=pd.DataFrame(a_data) if a_data else pd.DataFrame()
    df_history=pd.DataFrame(h_data) if h_data else pd.DataFrame()
    
    if not df_history.empty or not df_active.empty:
        # Top Row: Two main columns for Traffic and Revenue
        c1, c2 = st.columns(2)
        
        # 1. TRAFFIC BY HOUR (Locked to 0)
        with c1:
            st.subheader("Traffic by Hour")
            e1 = df_history[['entry_time']].copy() if not df_history.empty else pd.DataFrame()
            e2 = df_active[['entry_time']].copy() if not df_active.empty else pd.DataFrame()
            all_e = pd.concat([e1, e2])
            all_e['entry_time'] = pd.to_datetime(all_e['entry_time'])
            all_e['hour'] = all_e['entry_time'].dt.hour
            
            traffic_data = all_e.groupby('hour').size().reset_index(name='count')
            traffic_chart = alt.Chart(traffic_data).mark_bar(color="#FF4B4B").encode(
                x=alt.X('hour:O', title='Hour of Day (24h)'),
                y=alt.Y('count:Q', title='Vehicle Count', scale=alt.Scale(domainMin=0))
            )
            st.altair_chart(traffic_chart, use_container_width=True)

        # 2. REVENUE BY DAY (Locked to 0)
        with c2:
            st.subheader("Revenue by Day")
            if not df_history.empty:
                df_history['exit_time'] = pd.to_datetime(df_history['exit_time'])
                df_history['day_of_week'] = pd.Categorical(
                    df_history['exit_time'].dt.day_name(),
                    categories=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
                    ordered=True
                )
                rev_data = df_history.groupby('day_of_week')['total_fee'].sum().reset_index()
                
                rev_chart = alt.Chart(rev_data).mark_bar(color="#00C246").encode(
                    x=alt.X('day_of_week:O', title='Day of Week', sort=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']),
                    y=alt.Y('total_fee:Q', title='Revenue ($)', scale=alt.Scale(domainMin=0))
                )
                st.altair_chart(rev_chart, use_container_width=True)
            else:
                st.info("No revenue data available yet.")

        # Full Width Section: HEATMAP
        st.markdown("---")
        st.subheader("Weekly Occupancy Heatmap")
        
        # Reuse combined entry data for the heatmap
        h_entries = df_history[['entry_time']].copy() if not df_history.empty else pd.DataFrame()
        a_entries = df_active[['entry_time']].copy() if not df_active.empty else pd.DataFrame()
        heatmap_df = pd.concat([h_entries, a_entries])
        
        heatmap_df['entry_time'] = pd.to_datetime(heatmap_df['entry_time'])
        heatmap_df['Hour'] = heatmap_df['entry_time'].dt.hour
        heatmap_df['Day'] = heatmap_df['entry_time'].dt.day_name()
        
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        heatmap_data = heatmap_df.groupby(['Day', 'Hour']).size().reset_index(name='Vehicles')
        
        # Build the heatmap chart
        heatmap_chart = alt.Chart(heatmap_data).mark_rect().encode(
            x=alt.X('Hour:O', title='Hour of Day (24h)'),
            y=alt.Y('Day:O', sort=days_order, title='Day of Week'),
            color=alt.Color('Vehicles:Q', scale=alt.Scale(scheme='viridis'), title='Intensity'),
            tooltip=['Day', 'Hour', 'Vehicles']
        ).properties(height=350)
        
        st.altair_chart(heatmap_chart, use_container_width=True)
        
    else:
        st.warning("Not enough data to generate analytics. Process some vehicles first!") 
# end
# python -m streamlit run main.py 
# python api.py
