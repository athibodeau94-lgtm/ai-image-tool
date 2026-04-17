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

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 初始化状态
if 'upload_key' not in st.session_state: st.session_state.upload_key = 0
if 'individual_configs' not in st.session_state: st.session_state.individual_configs = {}
if 'editing_file' not in st.session_state: st.session_state.editing_file = None

def reset_uploader():
    st.session_state.upload_key += 1
    st.session_state.individual_configs = {}
    st.session_state.editing_file = None
    st.rerun()

# --- 2. 注入 CSS ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    [data-testid="stSidebar"] {display: none;}
    .block-container {padding-top: 2rem !important; padding-bottom: 0rem !important;}
    .stImage { border-radius: 4px; border: 1px solid #eee; }
    .edit-active { border: 3px solid #FF4B4B !important; background: #fff1f1; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 ---
def process_engine(img_input, config, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        tw, th = config['size']
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        
        # 预览模式下偏移量也要减半
        off_x = config.get('off_x', 0) // 2 if is_preview else config.get('off_x', 0)
        off_y = config.get('off_y', 0) // 2 if is_preview else config.get('off_y', 0)

        if config['fill_screen']:
            img_bg = img.convert("RGB")
            bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
            bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
            img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
            # 铺满模式下应用偏移（裁切框移动）
            left = (img_bg.width - render_w) / 2 - off_x
            top = (img_bg.height - render_h) / 2 - off_y
            res = img_bg.crop((left, top, left + render_w, top + render_h)).convert("RGBA")
        else:
            img_main = img.copy()
            img_main.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
            
            # 背景处理
            img_bg = img.convert("RGB")
            bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
            bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
            img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
            bg = img_bg.crop(((img_bg.width-render_w)/2, (img_bg.height-render_h)/2, (img_bg.width+render_w)/2, (img_bg.height+render_h)/2))
            bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
            bg = Image.alpha_composite(bg, Image.new("RGBA", (render_w, render_h), (0, 0, 0, 25)))
            
            # 合成主体：应用位置微调
            pos_x = (render_w - img_main.width) // 2 + off_x
            pos_y = (render_h - img_main.height) // 2 + off_y
            bg.paste(img_main, (int(pos_x), int(pos_y)), img_main)
            res = bg

        # 滤镜/后期
        alpha = res.getchannel('A')
        res = ImageEnhance.Brightness(res.convert("RGB")).enhance(config['bright'])
        res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
        res.putalpha(alpha)
        
        out_io = io.BytesIO()
        res.convert("RGB").save(out_io, format="JPEG", quality=90 if is_preview else 95, optimize=True)
        return out_io.getvalue(), "JPEG"
    except: return None, "ERR"

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 规格设置")
    files = st.file_uploader("上传图片", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    is_editing = st.session_state.editing_file is not None
    
    with st.expander("🛠️ 参数调整", expanded=True):
        res_label = st.selectbox("比例预设", ["聚合标准 (1920*1080)", "Kiosk (5:3)", "自定义"], index=0)
        tw, th = (1920, 1080) if "1920" in res_label else (1000, 600)
        
        is_fill = st.checkbox("强行铺满画布", value=False)
        b_radius = st.slider("背景模糊", 0, 100, 40)
        br = st.slider("亮度", 0.5, 1.5, 1.0)
        sh = st.slider("锐化", 1.0, 4.0, 1.5)
        
        st.markdown("---")
        # --- 微调位置功能区 ---
        st.write("📍 **展示区域微调 (仅对微调图生效)**" if is_editing else "📍 **展示区域 (全局)**")
        off_x = st.slider("左右偏移", -500, 500, 0)
        off_y = st.slider("上下偏移", -500, 500, 0)
        
        current_config = {
            'size': (tw, th), 'limit_kb': 0, 'bg_mode': "深度高斯模糊", 
            'blur_radius': b_radius, 'bright': br, 'sharp': sh, 
            'fill_screen': is_fill, 'off_x': off_x, 'off_y': off_y
        }
        
        if is_editing:
            st.session_state.individual_configs[st.session_state.editing_file] = current_config
            if st.button("✅ 完成并保存位置", use_container_width=True):
                st.session_state.editing_file = None
                st.rerun()

    if st.button("🔄 全部重置", use_container_width=True): reset_uploader()

with right_col:
    if files:
        st.subheader("🔍 实时预览区")
        with st.container(height=550):
            cols = st.columns(3)
            for i, f in enumerate(files):
                # 确定每张图的配置
                if st.session_state.editing_file == f.name:
                    f_cfg = current_config
                else:
                    f_cfg = st.session_state.individual_configs.get(f.name, current_config)

                with cols[i % 3]:
                    is_this_edit = (st.session_state.editing_file == f.name)
                    if is_this_edit: st.markdown('<div class="edit-active">', unsafe_allow_html=True)
                    
                    p_bytes, _ = process_engine(f, f_cfg, is_preview=True)
                    if p_bytes:
                        st.image(p_bytes, use_container_width=True, caption=f.name)
                        if st.button(f"🛠️ 调整位置/参数", key=f"btn_{i}"):
                            st.session_state.editing_file = f.name
                            st.rerun()
                    
                    if is_this_edit: st.markdown('</div>', unsafe_allow_html=True)

        if st.button("🚀 一键打包下载 (包含位置微调)", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for f in files:
                    final_cfg = st.session_state.individual_configs.get(f.name, current_config)
                    data, _ = process_engine(f, final_cfg, is_preview=False)
                    zf.writestr(f.name, data)
            st.download_button("📥 下载 ZIP", zip_buf.getvalue(), file_name="Batch_Fixed.zip", use_container_width=True)
