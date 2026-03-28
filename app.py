import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except:
    PDF_SUPPORT = False

# 优化 OCR 加载逻辑：避免启动即报错
@st.cache_resource
def load_ocr():
    try:
        import easyocr
        return easyocr.Reader(['ch_sim', 'en'], gpu=False)
    except:
        return None

OCR_READER = load_ocr()

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.1.1", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# --- 极致紧凑样式 ---
st.markdown("""
    <style>
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem !important; padding-top: 0rem !important; }
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    header {visibility: hidden;}
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; }
    .stImage { border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 文字抹除算法 ---
def erase_text_from_image(pil_img):
    if OCR_READER is None:
        return pil_img
    
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    results = OCR_READER.readtext(cv_img)
    
    if not results:
        return pil_img

    mask = np.zeros(cv_img.shape[:2], dtype="uint8")
    for (bbox, text, prob) in results:
        pts = np.array(bbox, dtype="int32")
        cv2.fillPoly(mask, [pts], 255)
    
    # 扩大掩膜范围，确保抹除干净
    mask = cv2.dilate(mask, np.ones((5,5), np.uint8), iterations=1)
    dst_cv = cv2.inpaint(cv_img, mask, 7, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(dst_cv, cv2.COLOR_BGR2RGB))

# --- 3. 处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    # 统一输入为 PIL 对象
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    # 抹除文字
    if config.get('erase_text') and not is_preview:
        img = erase_text_from_image(img).convert("RGBA")

    tw, th = config['size']
    render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
    img.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
    
    # 背景处理
    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((render_w, render_h)).filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (render_w, render_h), color_map.get(config['pure_color'], (255,255,255,255)))
    else:
        sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        bg = Image.new("RGBA", (render_w, render_h), sample + (255,))

    bg.paste(img, ((render_w - img.size[0]) // 2, (render_h - img.size[1]) // 2), img)
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    res.save(out_io, format=ext, quality=90 if not is_preview else 70)
    return out_io.getvalue(), ext

# --- 4. 侧边栏 ---
with st.sidebar:
    st.button("🗑️ 清空列表", on_click=reset_uploader, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        res_opt = st.selectbox("分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
        tw, th = map(int, res_opt.split('*')) if res_opt != "自定义" else (1920, 1080)
    with c2:
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
    
    erase_on = st.toggle("抹除已有文字", value=True)
    bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"]) if bg_m == "特定颜色" else "白色"
    b_radius = st.slider("模糊程度", 10, 100, 40) if bg_m == "深度高斯模糊" else 40
    
    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("锐化", 1.0, 4.0, 1.8)

# --- 5. 主界面 ---
st.title("🍽️ 餐影工坊 1.1.1")
files = st.file_uploader("上传图片/PDF", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    final_list = []
    for f in files:
        if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
            pages = convert_from_bytes(f.read(), dpi=150)
            for i, p in enumerate(pages):
                p.filename = f"{f.name.rsplit('.', 1)[0]}_P{i+1}.jpg"
                final_list.append(p)
        else:
            final_list.append(f)

    conf = {'size': (tw, th), 'limit_kb': 500 if vol_opt=="500KB" else 1024, 'bg_mode': bg_m, 
            'pure_color': p_color, 'blur_radius': b_radius, 'bright': br, 'sharp': sh, 'erase_text': erase_on}

    st.subheader(f"预览 ({len(final_list)} 张)")
    with st.container(height=500, border=True):
        cols = st.columns(3)
        for idx, item in enumerate(final_list):
            with cols[idx % 3]:
                # 预览时不执行 OCR 抹除以保证速度
                p_bytes, _ = process_engine(item, conf, is_preview=True)
                st.image(p_bytes, use_container_width=True, caption=getattr(item, 'filename', getattr(item, 'name', "img")))

    with st.sidebar:
        if len(final_list) == 1:
            data, ext = process_engine(final_list[0], conf)
            st.download_button("📥 下载图片", data, f"output.{ext.lower()}", use_container_width=True)
        else:
            if st.button("🚀 导出 ZIP", use_container_width=True):
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for i, itm in enumerate(final_list):
                        data, ext = process_engine(itm, conf)
                        name = getattr(itm, 'filename', getattr(itm, 'name', f"{i}.jpg"))
                        zf.writestr(f"{name.rsplit('.', 1)[0]}.{ext.lower()}", data)
                st.download_button("📦 点击下载 ZIP", zip_buf.getvalue(), "batch.zip", use_container_width=True)
