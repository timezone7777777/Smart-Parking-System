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
page=st.sidebar.radio("Navigate",["Dashboard","Settings","History","Security","Analytics"])
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
    if source=="Image":
        up_file=st.file_uploader("Upload Image",type=['jpg','png','jpeg'])
        if up_file:
            file_bytes=np.asarray(bytearray(up_file.read()),dtype=np.uint8)
            frame=cv2.imdecode(file_bytes,1)
            processed_frame,data=det.detect_frame(frame,set())
            frame_window.image(processed_frame,channels="BGR",use_container_width=True)
            if data:
                img_path=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                cv2.imwrite(img_path,processed_frame)
                payload={"plate_text":data['text'],"v_type":data['type'],"img_path":img_path,"gate_mode":gate_mode}
                res=requests.post(f"{API_URL}/vehicle",json=payload)
                api_data=res.json()
                status=api_data.get("status","Error")
                msg=api_data.get("message",api_data.get("detail"))
                rec=api_data.get("receipt",None)
                refresh_metrics(force=True)
                if status=="Entry":event_box.success(f"ENTRY: {data['text']}")
                elif status=="Exit":event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}")
                else:event_box.error(msg)
    
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
                    # This is the flash you're looking for 
                    event_box.error(f"🚨 SECURITY ALERT: Blacklisted Vehicle!\nPlate: {data['text']} | Reason: {r_spec.get('note')}")
                    st.session_state['processed_tracks'].add(data['track_id'])
                    continue # This 'continue' prevents the code below from running 
                
                # 3. NORMAL LOGGING: Only runs if NOT blacklisted 
                img_filename=f"captured_plates/{data['text']}_{int(time.time())}.jpg"
                cv2.imwrite(img_filename,processed_frame)
                payload={"plate_text":data['text'],"v_type":data['type'],"img_path":img_filename,"gate_mode":gate_mode}
                res=requests.post(f"{API_URL}/vehicle",json=payload)
                
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
                    if rec and rec.get("is_vip"):event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>🌟 VIP ENTRY: {data['text']}</b></div>",unsafe_allow_html=True)
                    else:event_box.success(f"ENTRY: {data['text']}\nTime: {fmt_time}")
                elif status=="Exit":
                    if rec and rec.get("is_vip"):event_box.markdown(f"<div style='background-color:gold;color:black;padding:10px;border-radius:5px;'><b>🌟 VIP EXIT: {data['text']} | Fee: $0.00</b></div>",unsafe_allow_html=True)
                    else:event_box.info(f"EXIT: {data['text']}\nFee: ${rec['fee']:.2f}\nTime: {rec['time']:.2f} min")
                else:event_box.error(msg)
            
            # Keep background metrics ticking without lagging video
            refresh_metrics(force=False)
        cap.release()

elif page=="Settings":cm.render_config_page()

elif page=="History":
    st.header("Financial & Parking Logs")
    a_data=requests.get(f"{API_URL}/logs/active").json()
    h_data=requests.get(f"{API_URL}/logs/history").json()
    df_active=pd.DataFrame(a_data) if a_data else pd.DataFrame()
    df_history=pd.DataFrame(h_data) if h_data else pd.DataFrame()
    sq=st.text_input("Search License Plate",placeholder="Type plate number...").strip().upper()
    
    if sq:
        if not df_active.empty:df_active=df_active[df_active['plate_number'].str.contains(sq,case=False,na=False)]
        if not df_history.empty:df_history=df_history[df_history['plate_number'].str.contains(sq,case=False,na=False)]
    
    if not df_active.empty:
        df_active['entry_time']=pd.to_datetime(df_active['entry_time']).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_active['evidence_img']=df_active['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    
    if not df_history.empty:
        for col in ['entry_time','exit_time']:df_history[col]=pd.to_datetime(df_history[col]).dt.strftime('%Y-%m-%d %H:%M:%S').str[:-3]
        df_history['evidence_img']=df_history['image_path'].apply(lambda x:get_img_as_base64(x) if x and os.path.exists(x) else None)
    
    cr,cd=st.columns([0.8,0.2])
    with cr:
        if st.button("Refresh History"):st.rerun()
    with cd:
        if not df_history.empty:st.download_button("Download CSV",df_history.to_csv(index=False).encode('utf-8'),f"parking_report_{time.strftime('%Y%m%d')}.csv","text/csv")
    
    st.subheader("Live Parking Status")
    if df_active.empty and sq:st.warning(f"No active vehicle found for '{sq}'")
    else:st.data_editor(df_active,column_config={"evidence_img":st.column_config.ImageColumn("Evidence"),"image_path":None,"plate_number":"License Plate","vehicle_type":"Type"},use_container_width=True,hide_index=True)
    
    st.markdown("---")
    st.subheader("Transaction History")
    if df_history.empty and sq:st.warning(f"No history found for '{sq}'")
    elif not df_history.empty:
        st.data_editor(df_history.style.format({"total_fee":"{:.2f}","duration_min":"{:.2f}"}),column_config={"evidence_img":st.column_config.ImageColumn("Entry Photo"),"image_path":None,"plate_number":"License Plate","total_fee":st.column_config.NumberColumn("Fee ($)",format="$%.2f")},use_container_width=True,hide_index=True)
        st.metric("Total Revenue (Filtered)",f"${df_history['total_fee'].sum():.2f}")

elif page=="Security":
    st.header("🚨 Security & VIP Management")
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
        c1,c2=st.columns(2)
        with c1:
            st.subheader("Traffic by Hour")
            e1=df_history[['entry_time']].copy() if not df_history.empty else pd.DataFrame(columns=['entry_time'])
            e2=df_active[['entry_time']].copy() if not df_active.empty else pd.DataFrame(columns=['entry_time'])
            all_e=pd.concat([e1,e2])
            all_e['entry_time']=pd.to_datetime(all_e['entry_time'])
            all_e['hour']=all_e['entry_time'].dt.hour
            st.bar_chart(all_e.groupby('hour').size(),color="#FF4B4B")
        with c2:
            st.subheader("Revenue by Day")
            if not df_history.empty:
                df_history['exit_time']=pd.to_datetime(df_history['exit_time'])
                df_history['day_of_week']=pd.Categorical(df_history['exit_time'].dt.day_name(),categories=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],ordered=True)
                st.bar_chart(df_history.groupby('day_of_week')['total_fee'].sum(),color="#00C246")
            else:st.info("No revenue data available yet.")
    else:st.warning("Not enough data to generate analytics. Process some vehicles first!")
# end
# python -m streamlit run main.py 
# terminal 1 python api.py
# (run in powershell)