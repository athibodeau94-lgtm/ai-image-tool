import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import fitz

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

# --- 算法引擎 ---
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
        # 兼容性处理
        img = Image.open(io.BytesIO(img_input)) if isinstance(img_input, bytes) else img_input
        img = img.convert("RGBA")
        
        # 自动抠图逻辑
        if config.get('auto_crop'): 
            img = advanced_extract_foreground(img)
            
        tw, th = config['size']
        # 渲染背景
        if config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明":
            res_img = Image.new("RGBA", (tw, th), (0,0,0,0))
        elif config['bg_mode'] == "特定颜色":
            color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255)}
            res_img = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
        else:
            res_img = Image.new("RGBA", (tw, th), (255,255,255,255))
            
        # 贴图
        ratio = min(tw/img.size[0], th/img.size[1])
        resized = img.resize((int(img.size[0]*ratio), int(img.size[1]*ratio)), Image.Resampling.LANCZOS)
        res_img.alpha_composite(resized, ((tw-resized.size[0])//2, (th-resized.size[1])//2))
        
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])
        
        out_io = io.BytesIO()
        ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
        res_img.convert("RGB" if ext=="JPEG" else "RGBA").save(out_io, format=ext, quality=90)
        return out_io.getvalue(), ext
    except: return None, None

# --- 界面 ---
left, right = st.columns([1.2, 2.4], gap="large")
with left:
    raw_uploads = st.file_uploader("上传图片", type=['jpg','jpeg','png'], accept_multiple_files=True)
    with st.expander("规格设置", expanded=True):
        res_map = {"": None, "聚合标准 (1920*1080)": "1920*1080", "Kiosk (5:3)": "1000*600", "封面 (1080*1250)": "1080*1250", "屏保 (1080*1920)": "1080*1920", "自定义": "custom"}
        res_label = st.selectbox("比例预设", list(res_map.keys()), key="res_sel")
        tw, th = 1920, 1080
        if res_map.get(res_label) and res_map[res_label] != "custom": tw, th = map(int, res_map[res_label].split('*'))
        elif res_label == "自定义": tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
        vol_mode = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
        if vol_mode == "自定义": st.number_input("大小 (KB)", 100, 5000, 500)

    with st.expander("视觉设置", expanded=True):
        auto_crop = st.checkbox("开启智能自动抠图 (智能提取菜品)")
        if auto_crop:
            bg_m = st.selectbox("背景模式", ["特定颜色"])
            p_color = st.selectbox("底色选择", ["-- 请选择底色 --", "白色", "黑色", "灰色", "透明"])
        else:
            bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
            p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"])
        br = st.slider("亮度", 0.5, 1.5, 1.0); sh = st.slider("锐化", 1.0, 4.0, 1.5)

with right:
    if raw_uploads and res_label != "" and (not auto_crop or p_color != "-- 请选择底色 --"):
        conf = {'size': (tw, th), 'bg_mode': bg_m, 'pure_color': p_color, 'bright': br, 'sharp': sh, 'auto_crop': auto_crop}
        with ThreadPoolExecutor() as exe:
            processed = [exe.submit(process_engine, f.getvalue(), conf).result() for f in raw_uploads]
        cols = st.columns(3)
        for i, (data, ext) in enumerate(processed):
            if data: cols[i%3].image(data, use_container_width=True)
    elif auto_crop and p_color == "-- 请选择底色 --":
        st.warning("请选择底色以继续渲染")
