import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置与状态管理 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 初始化微调配置字典
if 'upload_key' not in st.session_state: st.session_state.upload_key = 0
if 'adj' not in st.session_state: st.session_state.adj = {} # 存储每张图的 {缩放, 偏移X, 偏移Y}
if 'editing_key' not in st.session_state: st.session_state.editing_key = None

def reset_uploader():
    st.session_state.upload_key += 1
    st.session_state.adj = {}
    st.session_state.editing_key = None
    st.rerun()

# --- 2. 注入 CSS ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    [data-testid="stSidebar"] {display: none;}
    .block-container {padding-top: 2rem !important; padding-bottom: 0rem !important;}
    .stImage { border-radius: 4px; border: 1px solid #eee; margin-bottom: 10px; }
    .edit-active { border: 3px solid #FF4B4B !important; background: #fff1f1; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 (保留并增强) ---
def process_engine(img_input, config, adj_params=None, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        tw, th = config['size']
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        
        # 获取微调参数 (缩放比例, X偏移, Y偏移)
        zoom = adj_params.get('zoom', 1.0) if adj_params else 1.0
        off_x = adj_params.get('off_x', 0) if adj_params else 0
        off_y = adj_params.get('off_y', 0) if adj_params else 0
        
        # 预览模式下数值减半
        if is_preview:
            off_x //= 2
            off_y //= 2

        # 背景逻辑
        img_bg = img.convert("RGB")
        bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
        bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
        img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
        bg = img_bg.crop(((img_bg.width-render_w)/2, (img_bg.height-render_h)/2, (img_bg.width+render_w)/2, (img_bg.height+render_h)/2))
        bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
        bg = Image.alpha_composite(bg, Image.new("RGBA", (render_w, render_h), (0, 0, 0, 25)))

        # 主体逻辑：应用缩放和位移
        main_w = int(render_w * zoom)
        main_h = int(render_h * zoom)
        img_main = img.copy()
        img_main.thumbnail((main_w, main_h), Image.Resampling.LANCZOS)
        
        pos_x = (render_w - img_main.width) // 2 + off_x
        pos_y = (render_h - img_main.height) // 2 + off_y
        
        bg.paste(img_main, (int(pos_x), int(pos_y)), img_main)
        res = bg

        # 亮度/锐化
        alpha = res.getchannel('A')
        res = ImageEnhance.Brightness(res.convert("RGB")).enhance(config['bright'])
        res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
        res.putalpha(alpha)
        
        out_io = io.BytesIO()
        ext = "JPEG"
        q = 90 if is_preview else 95
        while q > 30:
            out_io = io.BytesIO()
            res.convert("RGB").save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
            q -= 5
        return out_io.getvalue(), ext
    except: return None, "ERR"

# --- 4. UI 布局 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 规格与体积")
    files = st.file_uploader("上传图片", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    with st.expander("🛠️ 原始设定 (比例/体积)", expanded=True):
        res_map = {"聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "自定义": "custom"}
        res_label = st.selectbox("比例预设", list(res_map.keys()), index=0)
        
        # 保留你的宽高逻辑
        tw, th = (1920, 1080)
        if res_label == "Kiosk/Emenu标准 (5:3)": tw, th = 1000, 600
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
        kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)

    # 视觉面板
    with st.expander("🎨 视觉效果", expanded=True):
        b_radius = st.slider("模糊强度", 0, 100, 40)
        br = st.slider("亮度", 0.5, 1.5, 1.05)
        sh = st.slider("锐化", 1.0, 4.0, 1.5)
        
        # 封装基础配置
        base_config = {'size': (tw, th), 'limit_kb': kb, 'blur_radius': b_radius, 'bright': br, 'sharp': sh, 'fill_screen': False}

    # --- 核心：微调控制区 ---
    if st.session_state.editing_key:
        st.subheader(f"📍 正在微调区域")
        key = st.session_state.editing_key
        # 初始化该图的位移参数
        if key not in st.session_state.adj:
            st.session_state.adj[key] = {'zoom': 1.0, 'off_x': 0, 'off_y': 0}
        
        # 直观调节：使用较大幅度的步长实现“挪动”感
        st.session_state.adj[key]['zoom'] = st.slider("🔍 缩放大小", 0.1, 2.0, st.session_state.adj[key]['zoom'], step=0.05)
        st.session_state.adj[key]['off_x'] = st.slider("↔️ 左右移动", -tw, tw, st.session_state.adj[key]['off_x'], step=10)
        st.session_state.adj[key]['off_y'] = st.slider("↕️ 上下移动", -th, th, st.session_state.adj[key]['off_y'], step=10)
        
        if st.button("✅ 保存此图位置", use_container_width=True):
            st.session_state.editing_key = None
            st.rerun()

    if st.button("🔄 全部清空", use_container_width=True): reset_uploader()

with right_col:
    if files:
        st.subheader("🔍 实时预览区")
        with st.container(height=550):
            cols = st.columns(3)
            for i, f in enumerate(files):
                f_key = f.name
                # 获取该图对应的微调参数
                f_adj = st.session_state.adj.get(f_key, {'zoom': 1.0, 'off_x': 0, 'off_y': 0})
                
                with cols[i % 3]:
                    is_this = (st.session_state.editing_key == f_key)
                    if is_this: st.markdown('<div class="edit-active">', unsafe_allow_html=True)
                    
                    p_bytes, _ = process_engine(f, base_config, adj_params=f_adj, is_preview=True)
                    if p_bytes:
                        st.image(p_bytes, use_container_width=True)
                        if st.button(f"🎯 调整展示区域", key=f"edit_{i}"):
                            st.session_state.editing_key = f_key
                            st.rerun()
                    
                    if is_this: st.markdown('</div>', unsafe_allow_html=True)

        # 批量下载
        if st.button("🚀 一键打包下载 (保留所有微调)", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for f in files:
                    # 使用各自的微调参数进行最终渲染
                    final_adj = st.session_state.adj.get(f.name, {'zoom': 1.0, 'off_x': 0, 'off_y': 0})
                    data, _ = process_engine(f, base_config, adj_params=final_adj, is_preview=False)
                    zf.writestr(f.name, data)
            st.download_button("📥 下载 ZIP 压缩包", zip_buf.getvalue(), file_name="output.zip", use_container_width=True)
