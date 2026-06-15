import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
import os
import numpy as np
import cv2
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide")

if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 2. 样式 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage > img { border-radius: 4px; background-color: #ffffff; background-image: linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0), linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0) !important; background-size: 16px 16px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 核心引擎 ---
def advanced_extract_foreground(img_obj):
    try:
        src = np.array(img_obj)
        if src.shape[2] < 4: src = cv2.cvtColor(src, cv2.COLOR_RGB2RGBA)
        h, w = src.shape[:2]
        rect = (int(w*0.05), int(h*0.05), int(w*0.9), int(h*0.9))
        mask = np.zeros((h, w), np.uint8)
        bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
        cv2.grabCut(src[:,:,:3], mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
        bin_mask = np.where((mask==2)|(mask==0), 0, 1).astype('uint8') * 255
        out_rgba = src.copy(); out_rgba[:,:,3] = np.minimum(out_rgba[:,:,3], cv2.GaussianBlur(bin_mask, (11,11), 0))
        return Image.fromarray(out_rgba)
    except: return img_obj

def process_engine(img_input, config):
    try:
        img = Image.open(io.BytesIO(img_input)) if isinstance(img_input, bytes) else img_input
        img = img.convert("RGBA")
        if config.get('auto_crop'): img = advanced_extract_foreground(img)
        tw, th = config['size']
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (tw, th), Image.Resampling.LANCZOS)
        else:
            ratio = min(tw/img.size[0], th/img.size[1])
            res_img = Image.new("RGBA", (tw, th), (255,255,255,0) if config['pure_color']=="透明" else (255,255,255,255))
            resized = img.resize((int(img.size[0]*ratio), int(img.size[1]*ratio)), Image.Resampling.LANCZOS)
            res_img.alpha_composite(resized, ((tw-resized.size[0])//2, (th-resized.size[1])//2))
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])
        out_io = io.BytesIO()
        res_img.convert("RGB" if config['pure_color']!="透明" else "RGBA").save(out_io, format="JPEG" if config['pure_color']!="透明" else "PNG", quality=90)
        return out_io.getvalue(), "JPEG" if config['pure_color']!="透明" else "PNG"
    except: return None, None

# --- 3. 界面 ---
left, right = st.columns([1.2, 2.4], gap="large")
with left:
    raw_uploads = st.file_uploader("上传图片", type=['jpg','jpeg','png'], accept_multiple_files=True)
    with st.expander("规格设置", expanded=True):
        res_map = {"": None, "聚合标准 (1920*1080)": "1920*1080", "Kiosk (5:3)": "1000*600", "封面 (1080*1250)": "1080*1250", "屏保 (1080*1920)": "1080*1920"}
        res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"res_{st.session_state.settings_key}")
        if res_map[res_label]: tw, th = map(int, res_map[res_label].split('*'))
        else: tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
        
        vol_mode = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
        vol_limit = st.number_input("自定义大小 (KB)", 100, 5000, 500) if vol_mode == "自定义" else 0
        scale_mode = st.radio("填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"])

    with st.expander("视觉设置", expanded=True):
        auto_crop = st.checkbox("开启智能自动抠图")
        bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"])
        br = st.slider("亮度", 0.5, 1.5, 1.0); sh = st.slider("锐化", 1.0, 4.0, 1.5)

with right:
    if raw_uploads and (res_map[res_label] or res_label == ""):
        conf = {'size': (tw, th), 'bg_mode': bg_m, 'pure_color': p_color, 'bright': br, 'sharp': sh, 'scale_mode': scale_mode, 'auto_crop': auto_crop}
        with ThreadPoolExecutor() as exe:
            processed = [exe.submit(process_engine, f.getvalue(), conf).result() for f in raw_uploads]
        cols = st.columns(3)
        for i, (data, ext) in enumerate(processed):
            if data: cols[i%3].image(data, use_container_width=True)
        if len(raw_uploads) == 1 and processed[0][0]:
            st.download_button("下载", processed[0][0], "processed."+processed[0][1].lower())
    else:
        st.info("请选择比例或上传图片。")
