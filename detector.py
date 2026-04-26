import cv2
import numpy as np
from ultralytics import YOLO
import easyocr
import torch
import re

model=None
reader=None

def load_models():
    global model,reader
    if model is None:model=YOLO('yolov8n.pt') 
    if reader is None:
        gpu_avail=torch.cuda.is_available()
        reader=easyocr.Reader(['en'],gpu=gpu_avail)
    return model,reader

def detect_frame(frame,processed_ids,conf_thresh=0.25): 
    model_inst,reader_inst=load_models()
    results=model_inst.track(frame,classes=[2,3,5,7],conf=conf_thresh,persist=True,tracker="bytetrack.yaml",verbose=False)
    annotated_frame=frame.copy()
    detection_data=None 

    for r in results:
        if r.boxes.id is None:continue 
        for box,trk_id in zip(r.boxes,r.boxes.id):
            x1,y1,x2,y2=map(int,box.xyxy[0])
            cls_id=int(box.cls[0])
            t_id=int(trk_id.item())
            
            v_type,color,label_text=("bike",(0,255,255),f"BIKE ID:{t_id}") if cls_id==3 else ("car",(0,255,0),f"CAR ID:{t_id}")
            cv2.rectangle(annotated_frame,(x1,y1),(x2,y2),color,2)

            if t_id not in processed_ids and detection_data is None:
                # 0.25 crop to ensure we get the full trunk area even if car box is slightly off
                plate_y1=y1+int((y2-y1)*0.25) 
                roi=frame[plate_y1:y2,x1:x2]
                
                if roi.size>0:
                    # 1. Keep it simple: Just grayscale and lighting balance (CLAHE)
                    gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
                    clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8))
                    enhanced=clahe.apply(gray)
                    
                    # 2. Let EasyOCR handle the upscaling natively using mag_ratio
                    # Added 'beamsearch' decoder so it double-checks similar letters like O and Q
                    ocr_results=reader_inst.readtext(
                        enhanced,
                        allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                        mag_ratio=2.0,        
                        text_threshold=0.6,   
                        decoder='beamsearch'  
                    )
                    
                    plate_texts=[text.replace(" ","").upper() for _,text,conf in ocr_results if conf>0.15]
                    
                    if plate_texts:
                        full_string="".join(plate_texts)
                        match=re.search(r'[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}',full_string)
                        if match:
                            full_plate=match.group()
                            detection_data={'text':full_plate,'type':v_type,'conf':0.99,'track_id':t_id}
                            cv2.putText(annotated_frame,f"PLATE: {full_plate}",(x1,y2+25),cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,255),2)

    return annotated_frame,detection_data