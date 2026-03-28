import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.1", layout="wide", page_icon="🍽️")

if 'up_key' not in st.session_state:
    st.session_state.up_key = 0

def reset_app():
    st.session_state.up_key += 1
    st.rerun()

# UI 样式精简
st.markdown("<style>header {visibility: hidden;} div[data-testid='stSidebar'] button:first-child { background-color: #ff4b4b !important; color: white !important; }</style>", unsafe_allow_html=True)

# --- 2. 自动裁剪算法 ---
def extract_subjects(pil_img):
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
    cnts, _ = cv2.findContours(cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15,15))), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    res = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        x, y, w, h = cv2.boundingRect(c)
        if cv2.contourArea(c) < 5000: continue
        res.append(Image.fromarray(cv2.cvtColor(cv_img[y:y+h, x:x+w], cv2.COLOR_BGR2RGB)))
    return res if res else [pil_img]

# --- 3. 核心处理引擎 (包含体积控制) ---
def engine(item, cfg, is_preview=False):
    # 读取图片
    img = Image.open(io.BytesIO(item.getvalue())).convert("RGBA") if hasattr(item, 'getvalue') else item.convert("RGBA")
    
    # 缩放处理
    tw, th = cfg['size']
    rw, rh = (tw//2, th//2) if is_preview else (tw, th)
    img.thumbnail((rw, rh), Image.Resampling.LANCZOS)
    
    # 背景模式
    if cfg['bg'] == "特定颜色":
        canvas = Image.new("RGBA", (rw, rh), cfg['color'])
    elif cfg['bg'] == "深度高斯模糊":
        canvas = img.convert("RGB").resize((rw, rh)).filter(ImageFilter.GaussianBlur(30)).convert("RGBA")
    else:
        pix = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        canvas = Image.new("RGBA", (rw, rh), pix + (255,))

    # 居中合成
    canvas.paste(img, ((rw - img.size[0])//2, (rh - img.size[1])//2), img)
    
    # 滤镜增强
    final = ImageEnhance.Sharpness(ImageEnhance.Brightness(canvas.convert("RGB")).enhance(cfg['br'])).enhance(cfg['sh'])
    
    # 体积压缩逻辑 (仅在导出时生效)
    out_io = io.BytesIO()
    ext = "PNG" if cfg['color'] == (0,0,0,0) else "JPEG"
    if ext == "JPEG":
        q = 95
        while q > 10:
            out_io = io.BytesIO()
            final.save(out_io, format="JPEG", quality=q, optimize=True)
            # 满足预览、不限制、或达到体积目标则跳出
            if is_preview or cfg['limit'] == 0 or out_io.tell() <= cfg['limit'] * 1024:
                break
            q -= 5
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
        limit_kb = {"不限制":0, "500KB":500, "1MB":1024}.get(vol_sel)
    
    do_crop = st.toggle("多主体拆解", value=True)
    bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    
    c_val = (255,255,255,255)
    if bg_m == "特定颜色":
        c_name = st.selectbox("颜色", ["白色", "黑色", "透明"])
        c_val = {"白色":(255,255,255,255), "黑色":(0,0,0,255), "透明":(0,0,0,0)}.get(c_name)

    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("锐化", 1.0, 4.0, 1.8)

# --- 5. 主界面 ---
st.title("🍽️ 餐影工坊 1.1")
files = st.file_uploader("上传图片/PDF", type=['jpg','png','pdf'], accept_multiple_files=True, key=f"u_{st.session_state.up_key}")

if files:
    final_list = []
    with st.spinner("处理素材中..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pages = convert_from_bytes(f.read(), dpi=150)
                for i, p in enumerate(pages):
                    if do_crop:
                        for idx, dish in enumerate(extract_subjects(p)):
                            dish.filename = f"{f.name[:-4]}_P{i+1}_{idx+1}.jpg"; final_list.append(dish)
                    else:
                        p.filename = f"{f.name[:-4]}_P{i+1}.jpg"; final_list.append(p)
            else:
                raw = Image.open(f)
                if do_crop:
                    for idx, dish in enumerate(extract_subjects(raw)):
                        dish.filename = f"{f.name.split('.')[0]}_{idx+1}.jpg"; final_list.append(dish)
                else:
                    final_list.append(f)

    cfg = {'size':(tw,th), 'limit':limit_kb, 'bg':bg_m, 'color':c_val, 'br':br, 'sh':sh}
    
    st.subheader(f"🖼️ 预览 ({len(final_list)} 张)")
    with st.container(height=550, border=True):
        cols = st.columns(3)
        for i, itm in enumerate(final_list):
            with cols[i % 3]:
                p_data, _ = engine(itm, cfg, is_preview=True)
                st.image(p_data, use_container_width=True, caption=getattr(itm, 'filename', f"素材_{i+1}"))

    # 导出按钮
    if st.sidebar.button("🚀 导出 ZIP", use_container_width=True):
        z_buf = io.BytesIO()
        with zipfile.ZipFile(z_buf, 'w') as zf:
            for i, itm in enumerate(final_list):
                d, e = engine(itm, cfg)
                zf.writestr(f"{i+1}.{e.lower()}", d)
        st.sidebar.download_button("📦 下载压缩包", z_buf.getvalue(), "output.zip", use_container_width=True)
else:
    st.info("💡 请上传图片或 PDF 开始制作。")
