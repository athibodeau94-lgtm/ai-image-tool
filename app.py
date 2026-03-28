import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 1. 环境兼容性检测 ---
@st.cache_resource
def load_ocr():
    try:
        import easyocr
        return easyocr.Reader(['ch_sim', 'en'], gpu=False)
    except Exception as e:
        st.warning(f"OCR组件加载中或环境受限，抹除功能暂不可用。")
        return None

try:
    from pdf2image import convert_from_bytes
    PDF_OK = True
except:
    PDF_OK = False

READER = load_ocr()

# --- 2. 核心功能函数 ---
def erase_text(pil_img):
    if READER is None: return pil_img
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    try:
        results = READER.readtext(cv_img)
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

# --- 3. 页面配置与样式 ---
st.set_page_config(page_title="餐影工坊 1.1.4", layout="wide")
if 'key' not in st.session_state: st.session_state.key = 0

def clear_all():
    st.session_state.key += 1
    st.rerun()

st.markdown("<style>header {visibility: hidden;} [data-testid='stSidebar'] {min-width: 300px;}</style>", unsafe_allow_html=True)

# --- 4. 侧边栏参数 ---
with st.sidebar:
    st.button("🗑️ 清空所有", on_click=clear_all, use_container_width=True)
    res_sel = st.selectbox("导出分辨率", ["1920*1080", "1000*600", "800*800"])
    tw, th = map(int, res_sel.split('*'))
    
    do_erase = st.toggle("智能抹除文字 (下载生效)", value=True)
    do_crop = st.toggle("自动拆解主体", value=True)
    
    bg_mode = st.radio("背景填充", ["纯色", "模糊", "提取原色"])
    c_sel = st.selectbox("颜色", ["白色", "黑色", "透明"]) if bg_mode == "纯色" else "白色"
    c_map = {"白色":(255,255,255,255), "黑色":(0,0,0,255), "透明":(0,0,0,0)}
    
    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("锐化", 1.0, 4.0, 1.8)

# --- 5. 处理引擎 ---
def engine(item, cfg, is_preview=False):
    # 统一转为PIL
    img = Image.open(io.BytesIO(item.getvalue())).convert("RGBA") if hasattr(item, 'getvalue') else item.convert("RGBA")
    
    # 仅下载时抹除
    if cfg['erase'] and not is_preview:
        img = erase_text(img).convert("RGBA")
        
    rw, rh = (tw//2, th//2) if is_preview else (tw, th)
    img.thumbnail((rw, rh), Image.Resampling.LANCZOS)
    
    if cfg['bg'] == "模糊":
        canvas = img.convert("RGB").resize((rw, rh)).filter(ImageFilter.GaussianBlur(30)).convert("RGBA")
    elif cfg['bg'] == "纯色":
        canvas = Image.new("RGBA", (rw, rh), cfg['color'])
    else:
        pix = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        canvas = Image.new("RGBA", (rw, rh), pix + (255,))

    canvas.paste(img, ((rw - img.size[0])//2, (rh - img.size[1])//2), img)
    final = ImageEnhance.Sharpness(ImageEnhance.Brightness(canvas.convert("RGB")).enhance(cfg['br'])).enhance(cfg['sh'])
    
    buf = io.BytesIO()
    fmt = "PNG" if cfg['color'] == (0,0,0,0) else "JPEG"
    final.save(buf, format=fmt, quality=90)
    return buf.getvalue(), fmt

# --- 6. 主逻辑 ---
st.title("🍽️ 餐影工坊 1.1.4")
files = st.file_uploader("素材上传", type=['jpg','png','pdf'], accept_multiple_files=True, key=f"u_{st.session_state.key}")

if files:
    final_list = [] # 统一变量名，彻底解决AttributeError
    
    with st.spinner("解析中..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_OK:
                pages = convert_from_bytes(f.read(), dpi=150)
                for i, p in enumerate(pages):
                    if do_crop:
                        for idx, dish in enumerate(get_subjects(p)):
                            dish.name = f"{f.name[:-4]}_P{i+1}_{idx+1}"
                            final_list.append(dish)
                    else:
                        p.name = f"{f.name[:-4]}_P{i+1}"
                        final_list.append(p)
            else:
                if do_crop:
                    raw = Image.open(f)
                    for idx, dish in enumerate(get_subjects(raw)):
                        dish.name = f"{f.name.split('.')[0]}_{idx+1}"
                        final_list.append(dish)
                else:
                    final_list.append(f)

    cfg = {'size':(tw,th), 'bg':bg_mode, 'color':c_map.get(c_sel), 'br':br, 'sh':sh, 'erase':do_erase}

    st.subheader(f"预览 ({len(final_list)} 张)")
    with st.container(height=500, border=True):
        cols = st.columns(3)
        for i, itm in enumerate(final_list):
            with cols[i % 3]:
                p_data, _ = engine(itm, cfg, is_preview=True)
                st.image(p_data, use_container_width=True, caption=getattr(itm, 'name', f"素材_{i+1}"))

    with st.sidebar:
        st.markdown("---")
        if len(final_list) > 0:
            if st.button("🚀 导出 ZIP", use_container_width=True):
                z_buf = io.BytesIO()
                with zipfile.ZipFile(z_buf, 'w') as zf:
                    for i, itm in enumerate(final_list):
                        d, e = engine(itm, cfg)
                        zf.writestr(f"{getattr(itm, 'name', str(i))}.{e.lower()}", d)
                st.download_button("📦 点击下载", z_buf.getvalue(), "images.zip", use_container_width=True)
else:
    st.info("💡 请上传图片或PDF。")
