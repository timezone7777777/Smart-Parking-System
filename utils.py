import torch
def check_gpu():
    is_gpu=torch.cuda.is_available()
    if is_gpu:device_name=torch.cuda.get_device_name(0)
    else:device_name="CPU"
    return is_gpu,device_name
# python -m streamlit run main.py 
# python api.py
