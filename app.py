import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 1. 环境与 OCR 延时加载 ---
@st.cache_resource
def get_ocr_reader():
    try:
        import easyocr
        return easyocr.Reader(['ch_sim', 'en'], gpu=False)
    except:
        return None

try:
    from pdf2image import convert_from_bytes
    PDF_READY = True
except:
    PDF_READY = False

# --- 2. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.1.3", layout="wide", page_icon="🍽️")

if 'up_key' not in st.session_state:
    st.session_state.up_key = 0

def reset_all():
    st.session_state.up_key += 1
    st.rerun()

# 极致紧凑 UI 
st.markdown("""
    <style>
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem !important; padding-top: 0rem !important; }
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    header {visibility: hidden;}
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心工具函数 ---
def erase_text_logic(pil_img, reader):
    if reader is None: return pil_img
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    try:
        results = reader.readtext(cv_img)
        if not results: return pil_img
        mask = np.zeros(cv_img.shape[:2], dtype="uint8")
        for (bbox, text, prob) in results:
            pts = np.array(bbox, dtype="int32")
            cv2.fillPoly(mask, [pts], 255)
        mask = cv2.dilate(mask, np.ones((5,5), np.uint8), iterations=1)
        clean_cv = cv2.inpaint(cv_img, mask, 3, cv2.INPAINT_TELEA)
        return Image.fromarray(cv2.cvtColor(clean_cv, cv2.COLOR_BGR2RGB))
    except:
        return pil_img

def get_subjects(pil_img):
    img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
    cnts, _ = cv2.findContours(cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15,15))), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    res = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(c) < 5000: continue
        x, y, w, h = cv2.boundingRect(c)
        if w > img.shape[1] * 0.9 or h > img.shape[0] * 0.9: continue
        res.append(Image.fromarray(cv2.cvtColor(img[y:y+h, x:x+w], cv2.COLOR_BGR2RGB)))
    return res if res else [pil_img]

# --- 4. 处理引擎 ---
def main_engine(item, cfg, is_pre=False):
    # 加载图片
    if hasattr(item, 'getvalue'):
        img = Image.open(io.BytesIO(item.getvalue())).convert("RGBA")
    else:
        img = item.convert("RGBA")

    # 执行抹除 (仅在正式导出且开启时)
    if cfg.get('erase') and not is_pre:
        img = erase_text_logic(img, cfg.get('reader')).convert("RGBA")

    # 缩放
    tw, th = cfg['size']
    rw, rh = (tw//2, th//2) if is_pre else (tw, th)
    img.thumbnail((rw, rh), Image.Resampling.LANCZOS)
    
    # 背景
    if cfg['bg'] == "模糊":
        canvas = img.convert("RGB").resize((rw, rh)).filter(ImageFilter.GaussianBlur(30)).convert("RGBA")
    elif cfg['bg'] == "纯色":
        canvas = Image.new("RGBA", (rw, rh), cfg['color'])
    else:
        pix = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        canvas = Image.new("RGBA", (rw, rh), pix + (255,))

    canvas.paste(img, ((rw - img.size[0])//2, (rh - img.size[1])//2), img)
    final = canvas.convert("RGB")
    final = ImageEnhance.Brightness(final).enhance(cfg['br'])
    final = ImageEnhance.Sharpness(final).enhance(cfg['sh'])
    
    buf = io.BytesIO()
    ext = "PNG" if cfg.get('color') == (0,0,0,0) else "JPEG"
    final.save(buf, format=ext, quality=85)
    return buf.getvalue(), ext

# --- 5. UI 逻辑 ---
with st.sidebar:
    st.button("🗑️ 清空重置", on_click=reset_all, use_container_width=True)
    size_sel = st.selectbox("分辨率", ["1920*1080", "1000*600", "800*800"])
    tw, th = map(int, size_sel.split('*'))
    
    ocr_on = st.toggle("智能抹除文字", value=True)
    crop_on = st.toggle("自动拆解主体", value=True)
    
    st.markdown("---")
    bg_sel = st.radio("背景模式", ["纯色", "模糊", "提取原色"])
    c_sel = st.selectbox("背景色", ["白色", "黑色", "透明"]) if bg_sel == "纯色" else "白色"
    c_map = {"白色":(255,255,255,255), "黑色":(0,0,0,255), "透明":(0,0,0,0)}
    
    br_val = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh_val = st.slider("锐化调节", 1.0, 4.0, 1.8)

st.title("🍽️ 餐影工坊 1.1.3")
up_files = st.file_uploader("上传图片或 PDF", type=['jpg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.up_key}")

if up_files:
    final_list = []
    reader_inst = get_ocr_reader() if ocr_on else None
    
    with st.spinner("正在解析素材..."):
        for f in up_files:
            if f.name.lower().endswith('.pdf') and PDF_READY:
                pages = convert_from_bytes(f.read(), dpi=150)
                for i, p in enumerate(pages):
                    if crop_on:
                        for idx, dish in enumerate(get_subjects(p)):
                            dish.name = f"{f.name[:-4]}_P{i+1}_{idx+1}.jpg"
                            final_list.append(dish)
                    else:
                        p.name = f"{f.name[:-4]}_P{i+1}.jpg"
                        final_list.append(p)
            else:
                if crop_on:
                    raw = Image.open(f)
                    for idx, dish in enumerate(get_subjects(raw)):
                        dish.name = f"{f.name.split('.')[0]}_{idx+1}.jpg"
                        final_list.append(dish)
                else:
                    final_list.append(f)

    cfg = {'size':(tw, th), 'bg':bg_sel, 'color':c_map.get(c_sel), 'br':br_val, 'sh':sh_val, 'erase':ocr_on, 'reader':reader_inst}

    st.subheader(f"🖼️ 预览 ({len(final_list)} 张)")
    with st.container(height=550, border=True):
        cols = st.columns(3)
        for i, item in enumerate(final_list):
            with cols[i % 3]:
                p_data, _ = main_engine(item, cfg, is_pre=True)
                st.image(p_data, use_container_width=True, caption=getattr(item, 'name', f"Image_{i+1}"))

    with st.sidebar:
        st.markdown("---")
        if len(final_list) == 1:
            data, ext = main_engine(final_list[0], cfg)
            st.download_button("📥 下载图片", data, f"output.{ext.lower()}", use_container_width=True)
        elif len(final_list) > 1:
            if st.button("🚀 导出 ZIP", use_container_width=True):
                z_io = io.BytesIO()
                with zipfile.ZipFile(z_io, 'w') as zf:
                    for i, itm in enumerate(final_list):
                        d, e = main_engine(itm, cfg)
                        nm = getattr(itm, 'name', f"{i+1}.jpg")
                        zf.writestr(f"{nm.split('.')[0]}.{e.lower()}", d)
                st.download_button("📦 点击下载 ZIP", z_io.getvalue(), "batch.zip", use_container_width=True)
else:
    st.info("💡 请上传素材开始。")
