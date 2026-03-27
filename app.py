import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance
import os

st.set_page_config(page_title="AI 图像处理站", layout="wide")

st.title("🖼️ 智能图像自动化处理站")

# 侧边栏配置
with st.sidebar:
    st.header("设置")
    width = st.number_input("目标宽度", value=1920)
    height = st.number_input("目标高度", value=1080)
    max_kb = st.slider("最大体积 (KB)", 100, 2000, 500)
    auto_fix = st.checkbox("自动增强 (去暗/去糊)", value=True)

uploaded_files = st.file_uploader("上传图片或文件夹", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

def process_img(image_bytes):
    # 读取
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # 尺寸调整与填充
    h, w = img.shape[:2]
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    scale = min(width/w, height/h)
    nw, nh = int(w*scale), int(h*scale)
    resized = cv2.resize(img, (nw, nh))
    yoff, xoff = (height-nh)//2, (width-nw)//2
    canvas[yoff:yoff+nh, xoff:xoff+nw] = resized
    
    # 基础增强
    if auto_fix:
        pil_img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        pil_img = ImageEnhance.Brightness(pil_img).enhance(1.1)
        canvas = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
    return canvas

if uploaded_files:
    for uploaded_file in uploaded_files:
        processed = process_img(uploaded_file.read())
        st.image(processed, channels="BGR", caption=f"已处理: {uploaded_file.name}")
        _, buffer = cv2.imencode(".jpg", processed, [cv2.IMWRITE_JPEG_QUALITY, 80])
        st.download_button("下载结果", data=buffer.tobytes(), file_name=f"processed_{uploaded_file.name}")
