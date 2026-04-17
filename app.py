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

# --- 1. 页面配置与状态初始化 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 状态记忆：upload_key用于清空，adj用于存储每张图的坐标，editing_key用于标记当前微调对象
if 'upload_key' not in st.session_state: st.session_state.upload_key = 0
if 'adj' not in st.session_state: st.session_state.adj = {} 
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
    div.stExpander { border: none !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    /* 微调激活状态样式 */
    .edit-active { border: 3px solid #FF4B4B !important; background: #fff1f1; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 (完全保留原始拆分逻辑) ---
def smart_extract_multiple_subjects(pil_img):
    try:
        open_cv_image = np.array(pil_img.convert('RGB'))
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15,15))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        extracted_images = []
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for c in contours:
            area = cv2.contourArea(c)
            x, y, w, h = cv2.boundingRect(c)
            if area < 8000 or w > img.shape[1] * 0.95 or h > img.shape[0] * 0.95: continue
            crop_img = img[y:y+h, x:x+w]
            extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))
        return extracted_images if extracted_images else [pil_img]
    except: return [pil_img]

def process_engine(img_input, config, adj_params=None, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        tw, th = config['size']
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        
        # 获取微调偏移和缩放
        zoom = adj_params.get('zoom', 1.0) if adj_params else 1.0
        off_x = adj_params.get('off_x', 0) if adj_params else 0
        off_y = adj_params.get('off_y', 0) if adj_params else 0
        if is_preview: # 预览模式坐标减半
            off_x //= 2
            off_y //= 2

        # 1. 强制铺满背景逻辑 (高斯模糊)
        img_bg = img.convert("RGB")
        bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
        bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
        img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
        bg = img_bg.crop(((img_bg.width-render_w)/2, (img_bg.height-render_h)/2, (img_bg.width+render_w)/2, (img_bg.height+render_h)/2))
        bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
        bg = Image.alpha_composite(bg, Image.new("RGBA", (render_w, render_h), (0, 0, 0, 25)))
        
        # 2. 主体缩放居中 + 位移微调
        img_main = img.copy()
        target_main_w = int(render_w * zoom)
        target_main_h = int(render_h * zoom)
        img_main.thumbnail((target_main_w, target_main_h), Image.Resampling.LANCZOS)
        
        paste_pos = (
            int((render_w - img_main.width) // 2 + off_x),
            int((render_h - img_main.height) // 2 + off_y)
        )
        bg.paste(img_main, paste_pos, img_main)
        res = bg

        # 3. 后期增强
        alpha = res.getchannel('A')
        res = ImageEnhance.Brightness(res.convert("RGB")).enhance(config['bright'])
        res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
        res.putalpha(alpha)
        
        # 4. 体积控制逻辑 (JPEG压缩循环)
        out_io = io.BytesIO()
        ext = "JPEG"
        q = 90 if is_preview else 95
        while q > 30:
            out_io = io.BytesIO()
            res.convert("RGB").save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
            q -= 5
        return out_io.getvalue(), ext
    except Exception as e:
        return None, str(e)

# --- 4. 界面布局 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], 
                             accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    with st.expander("🛠️ 规格设置", expanded=True):
        res_map = {"聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "自定义": "custom"}
        res_label = st.selectbox("比例预设", list(res_map.keys()), index=None, placeholder="请选择输出比例...")
        
        tw, th = 1920, 1080
        if res_label == "自定义":
            tw = st.number_input("宽", 100, 4000, 1920)
            th = st.number_input("高", 100, 4000, 1080)
        elif res_label:
            tw, th = map(int, res_map[res_label].split('*'))
        
        # 自动切换体积逻辑：1920或5:3规格下默认为500KB，其余为空
        def_vol_idx = None
        if res_label in ["聚合标准 (1920*1080)", "Kiosk/Emenu标准 (5:3)"]:
            def_vol_idx = 1 # 指向500KB
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"], index=def_vol_idx, placeholder="待选择...")
        kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
        if vol_opt == "自定义":
            kb = st.number_input("体积阈值 (KB)", 1, 10240, 500)

    with st.expander("🎨 视觉效果", expanded=True):
        auto_crop = st.toggle("多主体识别拆分", value=False)
        b_radius = st.slider("模糊强度", 0, 100, 40)
        br = st.slider("亮度", 0.5, 1.5, 1.05)
        sh = st.slider("锐化", 1.0, 4.0, 1.5)
        
        conf = {'size': (tw, th), 'limit_kb': kb, 'blur_radius': b_radius, 'bright': br, 'sharp': sh}

        # 微调操控面板
        if st.session_state.editing_key:
            st.markdown("---")
            st.markdown(f"📍 **调整中**: `{st.session_state.editing_key}`")
            ek = st.session_state.editing_key
            if ek not in st.session_state.adj: st.session_state.adj[ek] = {'zoom':1.0, 'off_x':0, 'off_y':0}
            
            st.session_state.adj[ek]['zoom'] = st.slider("🔍 缩放大小", 0.5, 2.0, st.session_state.adj[ek]['zoom'], step=0.05)
            st.session_state.adj[ek]['off_x'] = st.slider("↔️ 左右移动", -tw//2, tw//2, st.session_state.adj[ek]['off_x'], step=10)
            st.session_state.adj[ek]['off_y'] = st.slider("↕️ 上下移动", -th//2, th//2, st.session_state.adj[ek]['off_y'], step=10)
            
            if st.button("✅ 保存并返回全局", use_container_width=True):
                st.session_state.editing_key = None
                st.rerun()

    if st.button("🔄 全部重置", use_container_width=True): reset_uploader()

with right_col:
    st.subheader("🔍 实时预览区")
    if not res_label:
        st.warning("⚠️ 请选择比例预设以开启预览。")
    elif files:
        final_list = []
        # PDF/图片 拆分与重组逻辑 (保留原始命名规则)
        for f in files:
            try:
                if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                    pages = convert_from_bytes(f.read(), dpi=120)
                    for i, p in enumerate(pages):
                        if auto_crop:
                            for idx, dish in enumerate(smart_extract_multiple_subjects(p)):
                                dish.unique_id = f"{f.name}_P{i+1}_{idx+1}"; final_list.append(dish)
                        else: p.unique_id = f"{f.name}_P{i+1}"; final_list.append(p)
                else:
                    img_obj = Image.open(f)
                    if auto_crop:
                        for idx, dish in enumerate(smart_extract_multiple_subjects(img_obj)):
                            dish.unique_id = f"{f.name.split('.')[0]}_{idx+1}"; final_list.append(dish)
                    else:
                        img_obj.unique_id = f.name; final_list.append(img_obj)
            except: continue

        with st.container(height=550):
            cols = st.columns(3)
            for i, item in enumerate(final_list):
                u_id = getattr(item, 'unique_id', f"img_{i}")
                with cols[i % 3]:
                    is_active = (st.session_state.editing_key == u_id)
                    if is_active: st.markdown('<div class="edit-active">', unsafe_allow_html=True)
                    
                    # 获取该图对应的微调参数
                    f_adj = st.session_state.adj.get(u_id, {'zoom':1.0, 'off_x':0, 'off_y':0})
                    p_bytes, _ = process_engine(item, conf, adj_params=f_adj, is_preview=True)
                    
                    if p_bytes:
                        st.image(p_bytes, use_container_width=True)
                        if st.button(f"🎯 调整区域", key=f"btn_{u_id}"):
                            st.session_state.editing_key = u_id
                            st.rerun()
                    if is_active: st.markdown('</div>', unsafe_allow_html=True)

        st.write("---")
        # 批量打包下载逻辑
        if st.button("🚀 一键打包下载 (合并所有微调)", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for item in final_list:
                    u_id = getattr(item, 'unique_id', "output")
                    f_adj = st.session_state.adj.get(u_id, {'zoom':1.0, 'off_x':0, 'off_y':0})
                    data, ext = process_engine(item, conf, adj_params=f_adj, is_preview=False)
                    if data:
                        zf.writestr(f"{u_id}.{ext.lower()}", data)
            
            date_str = datetime.now().strftime('%m%d')
            st.download_button("📥 点击获取 ZIP 压缩包", zip_buf.getvalue(), 
                               file_name=f"Batch_{date_str}.zip", use_container_width=True)
