import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 0. PDF 支持检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 Pro Max", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# 侧边栏样式微调
st.markdown("""
    <style>
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    header {visibility: hidden;}
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：表格网格拆解 ---
def smart_area_extraction(pil_img):
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 强化表格线连接
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    _, thresh = cv2.threshold(closed, 225, 255, cv2.THRESH_BINARY_INV)
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    extracted = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if cv2.contourArea(c) < 20000: continue
        if w > img.shape[1] * 0.9 or h > img.shape[0] * 0.9: continue
        
        crop = img[y:y+h, x:x+w]
        extracted.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
    
    return extracted if extracted else [pil_img]

def smart_crop_dish(pil_img):
    img = np.array(pil_img.convert('RGB'))
    img_cv = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(cv2.GaussianBlur(gray, (5,5), 0), 240, 255, cv2.THRESH_BINARY_INV)
    cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        return pil_img.crop((x, y, x + w, y + h))
    return pil_img

# --- 3. 合成引擎 ---
def process_engine(img_input, config, is_preview=False):
    img = img_input.convert("RGBA")
    if config.get('auto_crop'):
        img = smart_crop_dish(img).convert("RGBA")
    
    tw, th = config['size']
    img.thumbnail((tw, th), Image.Resampling.LANCZOS)
    
    bg = Image.new("RGBA", (tw, th), (255,255,255,255))
    if config['bg_mode'] == "深度高斯模糊":
        bg = img_input.convert("RGB").resize((tw, th)).filter(ImageFilter.GaussianBlur(30)).convert("RGBA")
    
    bg.paste(img, ((tw - img.size[0]) // 2, (th - img.size[1]) // 2), img)
    res = bg.convert("RGB")
    
    # 简单画质增强
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])

    out_io = io.BytesIO()
    res.save(out_io, format="JPEG", quality=85 if not is_preview else 60)
    return out_io.getvalue()

# --- 4. 侧边栏 UI ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    st.button("🗑️ 清空列表", on_click=reset_uploader, use_container_width=True)
    
    res_sel = st.selectbox("分辨率", ["1920*1080", "1000*600", "自定义"])
    tw, th = (1920, 1080) if res_sel == "1920*1080" else (1000, 600)
    
    vol_mode = st.radio("体积单位", ["KB", "MB"], horizontal=True)
    vol_val = st.number_input("目标大小", 0.1, 100.0, 1.0)
    kb_limit = int(vol_val * 1024) if vol_mode == "MB" else int(vol_val)

    bg_m = st.selectbox("背景", ["深度高斯模糊", "白色填充"])
    br = st.slider("亮度", 0.5, 1.5, 1.0)
    sh = st.slider("锐化", 1.0, 3.0, 1.5)

# --- 5. 主逻辑 ---
st.title("🍽️ 餐影工坊 Pro Max")

if not PDF_SUPPORT:
    st.error("⚠️ 系统未检测到 PDF 组件，请确保已添加 packages.txt 并重启应用。")

files = st.file_uploader("上传图片或PDF", type=['jpg','png','pdf'], accept_multiple_files=True, key=f"u_{st.session_state.upload_key}")

if files:
    all_items = []
    with st.spinner("解析中..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pages = convert_from_bytes(f.read(), dpi=200)
                for i, p in enumerate(pages):
                    sub_images = smart_area_extraction(p)
                    for j, img in enumerate(sub_images):
                        img.filename = f"{f.name.split('.')[0]}_P{i+1}_{j+1}.jpg"
                        all_items.append(img)
            else:
                img = Image.open(f)
                img.name = f.name
                all_items.append(img)

    if all_items:
        conf = {'size': (tw, th), 'limit_kb': kb_limit, 'bg_mode': bg_m, 'bright': br, 'sharp': sh, 'auto_crop': True}
        
        # 修复属性读取逻辑
        sample = all_items[0]
        sample_name = getattr(sample, 'filename', getattr(sample, 'name', "预览图"))
        
        st.subheader(f"预览: {sample_name}")
        preview_bytes = process_engine(sample, conf, True)
        st.image(preview_bytes, use_container_width=True)
        
        if st.button(f"🚀 导出全部 {len(all_items)} 张图"):
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for idx, item in enumerate(all_items):
                    data = process_engine(item, conf)
                    name = getattr(item, 'filename', getattr(item, 'name', f"{idx}.jpg"))
                    zf.writestr(name, data)
            st.download_button("📥 下载 ZIP", zip_io.getvalue(), "output.zip", use_container_width=True)
