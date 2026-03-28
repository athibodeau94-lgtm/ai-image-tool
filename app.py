import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 0. 环境检测与 OCR 容错 ---
@st.cache_resource
def load_ocr_engine():
    try:
        import easyocr
        return easyocr.Reader(['ch_sim', 'en'], gpu=False)
    except Exception:
        return None

try:
    from pdf2image import convert_from_bytes
    PDF_READY = True
except ImportError:
    PDF_READY = False

OCR_READER = load_ocr_engine()

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.1", layout="wide", page_icon="🍽️")

if 'up_key' not in st.session_state:
    st.session_state.up_key = 0

def reset_app():
    st.session_state.up_key += 1
    st.rerun()

# 极致紧凑 UI 样式
st.markdown("""
    <style>
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem !important; padding-top: 0rem !important; }
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    header {visibility: hidden;}
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法逻辑 ---
def extract_subjects(pil_img):
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
    cnts, _ = cv2.findContours(cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15,15))), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    results = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        x, y, w, h = cv2.boundingRect(c)
        if cv2.contourArea(c) < 5000 or w > cv_img.shape[1] * 0.9 or h > cv_img.shape[0] * 0.9: continue
        crop = cv_img[y:y+h, x:x+w]
        results.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
    return results if results else [pil_img]

# --- 3. 处理引擎 (包含体积控制) ---
def process_engine(item, cfg, is_preview=False):
    # 加载图片
    img = Image.open(io.BytesIO(item.getvalue())).convert("RGBA") if hasattr(item, 'getvalue') else item.convert("RGBA")
    
    tw, th = cfg['size']
    rw, rh = (tw//2, th//2) if is_preview else (tw, th)
    img.thumbnail((rw, rh), Image.Resampling.LANCZOS)
    
    # 背景生成
    if cfg['bg'] == "深度高斯模糊":
        canvas = img.convert("RGB").resize((rw, rh)).filter(ImageFilter.GaussianBlur(40)).convert("RGBA")
    elif cfg['bg'] == "特定颜色":
        canvas = Image.new("RGBA", (rw, rh), cfg['color'])
    else:
        sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        canvas = Image.new("RGBA", (rw, rh), sample + (255,))

    canvas.paste(img, ((rw - img.size[0])//2, (rh - img.size[1])//2), img)
    final = canvas.convert("RGB")
    final = ImageEnhance.Brightness(final).enhance(cfg['br'])
    final = ImageEnhance.Sharpness(final).enhance(cfg['sh'])
    
    # 体积控制与输出
    out_io = io.BytesIO()
    ext = "PNG" if cfg['color'] == (0,0,0,0) else "JPEG"
    
    if ext == "JPEG":
        quality = 95
        target_size = cfg['kb_limit'] * 1024
        while quality > 15:
            out_io = io.BytesIO()
            final.save(out_io, format="JPEG", quality=quality, optimize=True)
            if is_preview or cfg['kb_limit'] == 0 or out_io.tell() <= target_size:
                break
            quality -= 5
    else:
        canvas.save(out_io, format="PNG")
        
    return out_io.getvalue(), ext

# --- 4. 侧边栏交互 ---
with st.sidebar:
    st.button("🗑️ 清空重置", on_click=reset_app, use_container_width=True)
    
    c1, c2 = st.columns(2)
    with c1:
        res_sel = st.selectbox("分辨率", ["1920*1080", "1000*600", "800*800"])
        tw, th = map(int, res_sel.split('*'))
    with c2:
        vol_sel = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
        kb_limit = {"不限制":0, "500KB":500, "1MB":1024}.get(vol_sel)

    do_crop = st.toggle("多主体拆解", value=True)
    bg_mode = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    
    pure_c = (255,255,255,255)
    if bg_mode == "特定颜色":
        c_name = st.selectbox("选择颜色", ["白色", "黑色", "透明"])
        pure_c = {"白色":(255,255,255,255), "黑色":(0,0,0,255), "透明":(0,0,0,0)}.get(c_name)

    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("锐化调节", 1.0, 4.0, 1.8)

# --- 5. 主逻辑 ---
st.title("🍽️ 餐影工坊 1.1")
uploaded = st.file_uploader("上传图片或 PDF", type=['jpg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.up_key}")

if uploaded:
    final_list = []
    with st.spinner("解析素材中..."):
        for f in uploaded:
            if f.name.lower().endswith('.pdf') and PDF_READY:
                pages = convert_from_bytes(f.read(), dpi=150)
                for i, p in enumerate(pages):
                    if do_crop:
                        for idx, dish in enumerate(extract_subjects(p)):
                            dish.filename = f"{f.name[:-4]}_P{i+1}_{idx+1}.jpg"
                            final_list.append(dish)
                    else:
                        p.filename = f"{f.name[:-4]}_P{i+1}.jpg"; final_list.append(p)
            else:
                if do_crop:
                    raw = Image.open(f)
                    for idx, dish in enumerate(extract_subjects(raw)):
                        dish.filename = f"{f.name.split('.')[0]}_{idx+1}.jpg"
                        final_list.append(dish)
                else:
                    final_list.append(f)

    config = {'size':(tw, th), 'bg':bg_mode, 'color':pure_c, 'br':br, 'sh':sh, 'kb_limit':kb_limit}

    st.subheader(f"🖼️ 预览 ({len(final_list)} 张)")
    with st.container(height=550, border=True):
        cols = st.columns(3)
        for i, itm in enumerate(final_list):
            with cols[i % 3]:
                p_data, _ = process_engine(itm, config, is_preview=True)
                st.image(p_data, use_container_width=True, caption=getattr(itm, 'filename', getattr(itm, 'name', f"素材_{i+1}")))

    with st.sidebar:
        st.markdown("---")
        if final_list and st.button("🚀 导出 ZIP", use_container_width=True):
            z_io = io.BytesIO()
            with zipfile.ZipFile(z_io, 'w') as zf:
                for i, itm in enumerate(final_list):
                    d, e = process_engine(itm, config)
                    name = getattr(itm, 'filename', getattr(itm, 'name', f"{i+1}.jpg"))
                    zf.writestr(f"{name.split('.')[0]}.{e.lower()}", d)
            st.download_button("📦 点击下载 ZIP", z_io.getvalue(), "batch_output.zip", use_container_width=True)
else:
    st.info("💡 请上传素材开始。")
