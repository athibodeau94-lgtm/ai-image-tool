import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
import gc
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import fitz  # PyMuPDF[cite: 5]

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 2. 图像核心引擎 (包含原有的图像重构与处理) ---
def super_resolve_and_sharpen(img_obj):
    w, h = img_obj.size
    if w < 1000 or h < 1000:
        scale_factor = 2 if max(w, h) > 500 else 3
        img_obj = img_obj.resize((int(w * scale_factor), int(h * scale_factor)), Image.Resampling.LANCZOS)
    img_obj = img_obj.filter(ImageFilter.EDGE_ENHANCE)
    return ImageEnhance.Sharpness(img_obj).enhance(1.4)

def process_engine(img_input, config):
    try:
        img = Image.open(io.BytesIO(img_input))
        img = img.convert("RGBA")
        target_w, target_h = config['size']
        
        # 居中裁剪铺满逻辑
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            res_img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        res_img.convert("RGB").save(out_io, format="JPEG", quality=95, optimize=True)
        data = out_io.getvalue()
        
        # 内存强制回收
        del img, res_img
        gc.collect() 
        return data, "JPEG"
    except Exception as e:
        return None, str(e)

# --- 3. 布局与逻辑 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入中心")
    raw_uploads = st.file_uploader("支持上传 PDF 或图片", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True)
    
    # 规格设置恢复
    tw = st.number_input("宽", 100, 4000, 1920)
    th = st.number_input("高", 100, 4000, 1080)
    scale_mode = st.radio("模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"])
    br = st.slider("亮度", 0.5, 1.5, 1.0)
    sh = st.slider("锐化", 1.0, 4.0, 1.5)

with right_col:
    st.subheader("🔍 实时预览")
    if raw_uploads:
        processed_list = []
        # PDF 解析逻辑恢复
        for f in raw_uploads:
            if f.name.endswith('.pdf'):
                doc = fitz.open(stream=f.getvalue(), filetype="pdf")
                for page in doc:
                    for img_info in page.get_images(full=True):
                        base_image = doc.extract_image(img_info[0])
                        raw_pil = Image.open(io.BytesIO(base_image["image"]))
                        hd_pil = super_resolve_and_sharpen(raw_pil)
                        hd_io = io.BytesIO()
                        hd_pil.save(hd_io, format="JPEG")
                        processed_list.append(hd_io.getvalue())
            else:
                processed_list.append(f.getvalue())
        
        # 并行处理限制
        config = {'size': (tw, th), 'bright': br, 'sharp': sh, 'scale_mode': scale_mode}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(process_engine, img_bytes, config) for img_bytes in processed_list]
            for f in futures:
                res, ext = f.result()
                if res: st.image(res, use_container_width=True)
    else:
        st.info("请上传文件开始处理。")
