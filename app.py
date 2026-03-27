import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 页面配置 ---
st.set_page_config(page_title="餐影工坊 | 菜品图像高级处理站", layout="wide", page_icon="🍽️")

# 自定义高级感 CSS
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #1f77b4; color: white; }
    .stDownloadButton>button { width: 100%; border-radius: 5px; background-color: #28a745; color: white; }
    .upload-text { font-size: 1.2rem; font-weight: bold; color: #495057; }
    </style>
    """, unsafe_allow_html=True)

# --- 初始化 Session State (用于一键清空) ---
if 'processed' not in st.session_state:
    st.session_state.processed = False
if 'file_key' not in st.session_state:
    st.session_state.file_key = 0

def clear_all():
    st.session_state.file_key += 1
    st.session_state.processed = False
    st.rerun()

# --- 核心处理函数 ---
def process_engine(image_bytes, config):
    # 读取图片
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size
    tw, th = config['size']

    # 1. 创建画布 (背景处理)
    if config['bg_mode'] == "深度高斯模糊":
        # 缩放原图填充背景并模糊
        bg = img.resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius']))
    else:
        # 提取原图中心部分或平铺（此处采用拉伸原图作为背景填充）
        bg = img.resize((tw, th), Image.Resampling.NEAREST)

    # 2. 垂直居中放置 (不缩放)
    # 计算偏移量，若原图大于画布则会被截断（符合“不缩放”逻辑）
    offset_x = (tw - orig_w) // 2
    offset_y = (th - orig_h) // 2
    bg.paste(img, (offset_x, offset_y))

    # 3. 效果增强
    # 提亮
    bg = ImageEnhance.Brightness(bg).enhance(config['bright_level'])
    # 去糊 (锐化)
    bg = ImageEnhance.Sharpness(bg).enhance(config['sharp_level'])
    
    # 滤镜选择
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = bg.split()
        r = ImageEnhance.Brightness(r).enhance(1.1)
        bg = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "冷色调 (清爽)":
        r, g, b = bg.split()
        b = ImageEnhance.Brightness(b).enhance(1.1)
        bg = Image.merge("RGB", (r, g, b))

    # 4. 体积控制
    limit_kb = config['limit_kb']
    q = 95
    out_io = io.BytesIO()
    while q > 10:
        out_io = io.BytesIO()
        bg.save(out_io, format="JPEG", quality=q, optimize=True)
        if limit_kb == 0 or out_io.tell() < limit_kb * 1024:
            break
        q -= 5
    return out_io.getvalue()

# --- UI 布局 ---
st.title("👨‍🍳 餐影工坊 · 菜品图高级处理")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 参数设置")
    
    # 1. 尺寸设置
    size_preset = st.selectbox("分辨率预设", ["1920*1080", "1000*600", "自定义"])
    if size_preset == "自定义":
        tw = st.number_input("宽", value=1280)
        th = st.number_input("高", value=720)
    else:
        tw, th = map(int, size_preset.split('*'))

    # 2. 体积控制
    vol_preset = st.selectbox("文件大小限制", ["500KB", "1MB", "不限制"])
    limit_kb = 500 if vol_preset == "500KB" else 1024 if vol_preset == "1MB" else 0

    # 3. 背景处理
    bg_mode = st.radio("背景填充模式", ["深度高斯模糊", "提取原背景"])
    blur_r = st.slider("模糊程度", 0, 100, 50) if bg_mode == "深度高斯模糊" else 0

    # 4. 效果增强
    st.subheader("滤镜与增强")
    filter_type = st.selectbox("选择滤镜", ["无", "暖色调 (食欲)", "冷色调 (清爽)"])
    bright = st.slider("亮度调整", 0.5, 2.0, 1.0, 0.1)
    sharp = st.slider("清晰度(去糊)", 1.0, 5.0, 2.0, 0.2)

    st.markdown("---")
    if st.button("🗑️ 一键清空重置", on_click=clear_all):
        pass

# --- 主操作区 ---
uploaded_files = st.file_uploader(
    "上传菜品图片", 
    type=['jpg', 'jpeg', 'png'], 
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.file_key}"
)

if uploaded_files:
    config = {
        'size': (tw, th),
        'limit_kb': limit_kb,
        'bg_mode': bg_mode,
        'blur_radius': blur_r,
        'filter': filter_type,
        'bright_level': bright,
        'sharp_level': sharp
    }

    processed_data = []
    
    col_run, col_status = st.columns([1, 4])
    with col_run:
        start_btn = st.button("🚀 开始处理")

    if start_btn:
        progress_bar = st.progress(0)
        for idx, file in enumerate(uploaded_files):
            # 处理
            result = process_engine(file.getvalue(), config)
            # 保留原文件名
            processed_data.append({"name": file.name, "data": result})
            progress_bar.progress((idx + 1) / len(uploaded_files))
        
        st.session_state.processed_files = processed_data
        st.session_state.processed = True

    if st.session_state.get('processed'):
        st.success(f"处理完成！已生成 {len(st.session_state.processed_files)} 张图片。")
        
        # 预览区
        st.subheader("🖼️ 处理结果预览 (前2张)")
        prev_cols = st.columns(2)
        for i, item in enumerate(st.session_state.processed_files[:2]):
            prev_cols[i].image(item['data'], caption=item['name'], use_container_width=True)

        # 下载区
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zf:
            for item in st.session_state.processed_files:
                zf.writestr(item['name'], item['data'])
        
        st.download_button(
            label="📦 点击下载全部处理后的原名图片 (ZIP)",
            data=zip_io.getvalue(),
            file_name=f"processed_images_{int(time.time())}.zip",
            mime="application/zip"
        )
else:
    st.info("请在上方上传图片开始处理。默认效果：原图垂直居中不缩放。")
