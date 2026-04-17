import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置与状态初始化 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state: st.session_state.upload_key = 0
# 用于存储每张图的独立配置 {文件名: 配置字典}
if 'individual_configs' not in st.session_state: st.session_state.individual_configs = {}
# 当前正在微调的图片文件名
if 'editing_file' not in st.session_state: st.session_state.editing_file = None

def reset_all():
    st.session_state.upload_key += 1
    st.session_state.individual_configs = {}
    st.session_state.editing_file = None
    st.rerun()

# --- 2. 注入 CSS ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    [data-testid="stSidebar"] {display: none;}
    .stImage { border-radius: 4px; border: 1px solid #eee; }
    .edit-active { border: 2px solid #FF4B4B !important; background: #fff1f1; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 ---
def process_engine(img_input, config, is_preview=False):
    try:
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        tw, th = config['size']
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        
        if config['fill_screen']:
            img_bg = img.convert("RGB")
            bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
            bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
            img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
            left, top = (img_bg.width - render_w) / 2, (img_bg.height - render_h) / 2
            res = img_bg.crop((left, top, left + render_w, top + render_h)).convert("RGBA")
        else:
            img_main = img.copy()
            img_main.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
            img_bg = img.convert("RGB")
            bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
            img_bg = img_bg.resize((int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio)), Image.Resampling.LANCZOS)
            bg = img_bg.crop(((img_bg.width-render_w)/2, (img_bg.height-render_h)/2, (img_bg.width+render_w)/2, (img_bg.height+render_h)/2))
            bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
            bg.paste(img_main, ((render_w - img_main.width)//2, (render_h - img_main.height)//2), img_main)
            res = bg

        # 亮度/锐化
        alpha = res.getchannel('A')
        res = ImageEnhance.Brightness(res.convert("RGB")).enhance(config['bright'])
        res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
        res.putalpha(alpha)
        
        out_io = io.BytesIO()
        res.convert("RGB").save(out_io, format="JPEG", quality=90 if is_preview else 95, optimize=True)
        return out_io.getvalue(), "JPEG"
    except: return None, "ERR"

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1, 2.5], gap="large")

with left_col:
    st.header("🎨 控制面板")
    files = st.file_uploader("上传图片", type=['jpg','png','jpeg'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    # 获取当前配置来源（是全局还是正在编辑的单张）
    is_editing = st.session_state.editing_file is not None
    current_title = f"正在微调：{st.session_state.editing_file}" if is_editing else "全局批量设置"
    
    with st.expander(current_title, expanded=True):
        if is_editing:
            st.info("💡 当前滑块仅对红框图片生效")
        
        is_fill = st.checkbox("强行铺满", value=False)
        b_radius = st.slider("背景模糊", 0, 100, 40)
        br = st.slider("亮度", 0.5, 1.5, 1.0)
        sh = st.slider("锐化", 1.0, 5.0, 1.5)
        
        current_config = {
            'size': (1920, 1080), 'limit_kb': 0, 'bg_mode': "深度高斯模糊", 
            'blur_radius': b_radius, 'bright': br, 'sharp': sh, 'fill_screen': is_fill, 'pure_color':"白色", 'filter':"原色"
        }
        
        # 如果在编辑模式，实时保存配置到 session_state
        if is_editing:
            st.session_state.individual_configs[st.session_state.editing_file] = current_config
        
        if is_editing and st.button("完成微调 (保存并返回全局)", use_container_width=True):
            st.session_state.editing_file = None
            st.rerun()

    if st.button("🗑️ 全部清空", use_container_width=True): reset_all()

with right_col:
    if files:
        st.subheader("🔍 预览与微调 (点击微调可单独设置)")
        
        with st.container(height=550):
            cols = st.columns(3)
            for i, f in enumerate(files):
                # 逻辑：如果这张图有独立配置，用独立的；否则用当前的全局配置
                f_config = st.session_state.individual_configs.get(f.name, current_config if not is_editing else st.session_state.individual_configs.get(f.name, current_config))
                
                # 如果正处于全局模式，f_config 实时跟随滑块
                if not is_editing and f.name not in st.session_state.individual_configs:
                    f_config = current_config

                with cols[i % 3]:
                    # 正在编辑的图片加红框
                    is_this_editing = (st.session_state.editing_file == f.name)
                    container_class = "edit-active" if is_this_editing else ""
                    
                    st.markdown(f'<div class="{container_class}">', unsafe_allow_html=True)
                    p_bytes, _ = process_engine(f, f_config, is_preview=True)
                    if p_bytes:
                        st.image(p_bytes, caption=f.name[:15], use_container_width=True)
                    
                    if st.button("🛠️ 微调此图", key=f"btn_{f.name}"):
                        st.session_state.editing_file = f.name
                        # 进入微调时，如果它还没独立配置，先把当前的全局配置拷给它
                        if f.name not in st.session_state.individual_configs:
                            st.session_state.individual_configs[f.name] = current_config
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

        # --- 批量打包下载 ---
        if st.button("🚀 准备好所有图片，一键打包下载", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for f in files:
                    # 下载逻辑：优先使用 individual_configs 里的参数
                    final_cfg = st.session_state.individual_configs.get(f.name, current_config)
                    data, _ = process_engine(f, final_cfg, is_preview=False)
                    zf.writestr(f.name, data)
            
            st.download_button("📥 点击下载 ZIP (包含所有微调结果)", zip_buf.getvalue(), 
                               file_name=f"Batch_Fixed_{datetime.now().strftime('%H%M')}.zip", use_container_width=True)
    else:
        st.info("等待上传图片...")
