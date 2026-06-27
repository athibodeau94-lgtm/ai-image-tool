import streamlit as st
import fitz  # PyMuPDF[cite: 5]
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
import gc
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 初始化 Session State
if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 2. 样式注入 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage > img { border-radius: 4px; object-fit: contain; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 图像核心引擎 ---
def super_resolve_and_sharpen(img_obj):
    w, h = img_obj.size
    if w < 1000 or h < 1000:
        scale_factor = 2 if max(w, h) > 500 else 3
        img_obj = img_obj.resize((int(w * scale_factor), int(h * scale_factor)), Image.Resampling.LANCZOS)
    img_obj = img_obj.filter(ImageFilter.EDGE_ENHANCE)
    return ImageEnhance.Sharpness(img_obj).enhance(1.4)

def process_engine(img_input, config):
    try:
        img = Image.open(io.BytesIO(img_input) if isinstance(img_input, bytes) else img_input)
        img = img.convert("RGBA")
        target_w, target_h = config['size']
        
        # 处理逻辑
        res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS) if config.get('scale_mode') == "居中裁剪铺满 (大图感)" else img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        # 亮度与锐度
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        res_img.convert("RGB").save(out_io, format="JPEG", quality=90, optimize=True)
        data = out_io.getvalue()
        
        # 显式内存释放
        del img, res_img, out_io
        gc.collect()
        return data, "JPEG"
    except Exception as e:
        return None, str(e)

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入中心")
    raw_uploads = st.file_uploader("支持上传 PDF 或图片", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True)
    
    # 规格设置
    tw, th = 1920, 1080
    bg_m, p_color = "深度高斯模糊", "白色"
    b_radius, br, sh = 70, 1.0, 1.5
    scale_mode = "等比完整展示 (留背景)"
    
    if st.button("🔄 重置设置"): reset_all_settings()

with right_col:
    st.subheader("🔍 实时预览")
    if raw_uploads:
        processed_data = []
        # 使用 ThreadPoolExecutor 限制并发，防止内存爆炸
        with ThreadPoolExecutor(max_workers=2) as executor:
            config = {'size': (tw, th), 'bright': br, 'sharp': sh, 'scale_mode': scale_mode}
            futures = [executor.submit(process_engine, f.getvalue(), config) for f in raw_uploads]
            for f in futures:
                res, ext = f.result()
                if res: processed_data.append(res)
        
        for item in processed_data:
            st.image(item, use_container_width=True)
    else:
        st.info("请上传文件开始处理。")
