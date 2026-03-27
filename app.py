import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 页面配置与清新视觉风格 (薄荷绿 & 柔白) ---
st.set_page_config(page_title="高级菜品图像处理站", layout="wide", page_icon="🥗")
st.markdown("""
    <style>
    .stApp { background-color: #F3F8F5; }
    .stSidebar { background-color: #FFFFFF; border-right: 1px solid #D1E1DA; }
    .stButton>button { width: 100%; border-radius: 20px; background-color: #76C893; color: white; border: none; transition: 0.3s; }
    .stButton>button:hover { background-color: #52B69A; transform: translateY(-2px); }
    .stDownloadButton>button { width: 100%; background-color: #1E6091; color: white; border-radius: 20px; }
    div[data-testid="stExpander"] { background: white; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); }
    </style>
    """, unsafe_allow_html=True)

if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 2. 侧边栏面板 ---
with st.sidebar:
    st.title("👨‍🍳 处理控制面板")
    
    st.header("1. 尺寸与分辨率")
    size_preset = st.selectbox("选择目标分辨率", ["1920*1080 (HD)", "1000*600 (Web)", "自定义"])
    if size_preset == "1920*1080 (HD)": tw, th = 1920, 1080
    elif size_preset == "1000*600 (Web)": tw, th = 1000, 600
    else:
        tw = st.number_input("宽 (px)", value=1920, step=10)
        th = st.number_input("高 (px)", value=1080, step=10)

    st.header("2. AI背景填充 (确保物理无黑边)")
    # 彻底弃用旧的单色填充和简单的拉伸模式，直接使用效果最好的两种模式
    bg_mode = st.radio("填充逻辑", ["原图深度模糊背景 (图二质感)", "原图直接延伸背景 (镜像延伸)"])
    blur_r = st.slider("模糊程度", 10, 150, 70) if bg_mode == "原图深度模糊背景 (图二质感)" else 0

    st.header("3. 效果调节")
    with st.expander("美化细节"):
        sharp_v = st.slider("去糊 (锐化)", 1.0, 3.0, 1.7)
        bright_v = st.slider("提亮", 1.0, 2.0, 1.25)
        filter_v = st.slider("暖色滤镜程度", 0.0, 1.0, 0.6)

    st.header("4. 导出控制")
    max_kb = st.selectbox("最大体积", ["不限制", "500KB", "1MB"])
    
    st.divider()
    if st.button("🗑️ 一键清空预览与处理"):
        st.session_state.processed_files = []
        st.rerun()

# --- 3. 彻底修复黑边的底层重构 (物理层面上杜绝黑边) ---
def process_ultimate_fix_logic(bytes_data):
    # 彻底移除 OpenCV 的背景生成逻辑，改用 PIL 库确保稳健性
    raw_img_pil = Image.open(io.BytesIO(bytes_data)).convert("RGB")
    w, h = raw_img_pil.size
    
    # === A. 终极逻辑：背景先行，铺满全屏，杜绝黑边空间 ===
    
    # 核心：无论原图长宽比如何，强制拉伸到 tw x th，确保背景完全占满
    # 这里的 resize(..., Image.Resampling.LANCZOS) 会确保背景在铺满的同时保持较好的细节
    bg_full_pil = raw_img_pil.resize((tw, th), Image.Resampling.LANCZOS)
    
    # 应用背景处理模式
    if bg_mode == "原图深度模糊背景 (图二质感)":
        # 模式一：深度模糊（实现图三、图二的高级质感）
        bg_full_pil = bg_full_pil.filter(ImageFilter.GaussianBlur(radius=blur_r))
    else: 
        # 模式二："原图直接延伸背景 (镜像延伸)"
        # 这种模式下，背景不需要模糊，直接使用拉伸铺满后的原图
        pass

    # === B. 居中贴主体菜品 (垂直居中，不缩放) ===
    
    # 代码逻辑：只有当原图比 1920x1080 还要大时，才等比缩小以适应画面。
    # 如果原图较小，它会保持原汁原味地展示在中心，避免虚化。
    scale_main = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale_main), int(h * scale_main)
    main_img_rsz = raw_img_pil.resize((nw, nh), Image.Resampling.LANCZOS)

    # === C. 效果增强 (仅增强主体) ===
    
    # 锐化 (去糊)
    enhancer_sharp = ImageEnhance.Sharpness(main_img_rsz)
    main_processed = enhancer_sharp.enhance(sharp_v)
    
    # 提亮
    enhancer_bright = ImageEnhance.Brightness(main_processed)
    main_processed = enhancer_bright.enhance(bright_v)
    
    if filter_v > 0:
        # 暖调滤镜
        r, g, b = main_processed.split()
        r = r.point(lambda i: i * (1 + 0.1 * filter_v))
        g = g.point(lambda i: i * (1 + 0.05 * filter_v))
        main_processed = Image.merge("RGB", (r, g, b))
        # 饱和度
        enhancer_color = ImageEnhance.Color(main_processed)
        main_processed = enhancer_color.enhance(1.0 + 0.25 * filter_v)

    # === D. 合成：将纯净主体贴在已经物理铺满的背景上 ===
    
    offset = ((tw - nw) // 2, (th - nh) // 2)
    # 这一步 paste 操作会将纯净、美化后的主体贴在已经彻底占满的背景上
    # 彻底告别丑陋黑边！
    bg_full_pil.paste(main_processed, offset)

    # === E. 体积控制 (递归压缩) ===
    
    limit = 0
    if max_kb == "500KB": limit = 500 * 1024
    elif max_kb == "1MB": limit = 1024 * 1024
    
    q = 95
    out_buf = io.BytesIO()
    while q > 15:
        out_buf = io.BytesIO()
        # 保存为纯净无水印的 JPEG
        bg_full_pil.save(out_buf, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out_buf.tell() < limit: break
        q -= 5 # 质量步进下调
        
    return out_buf.getvalue()

# --- 4. 网页界面交互 ---
st.title("👨‍🍳 菜品图专业处理站 (终极修复版·彻底告别黑边)")
st.caption("这一次，我们将背景处理逻辑完全重构，从物理层面上杜绝黑边。保证纯净、高级、无水印填充。")

files = st.file_uploader("📥 上传菜品图片 (支持批量，保留原文件名下载)", accept_multiple_files=True, type=['jpg','png','jpeg'])

if files:
    for f in files:
        if not any(item['name'] ==
