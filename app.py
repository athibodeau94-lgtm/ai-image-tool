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
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.0", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# --- 极致紧凑样式 ---
st.markdown("""
    <style>
    /* 侧边栏顶部和组件间距最小化 */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem !important; padding-top: 0rem !important; }
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    [data-testid="stSidebar"] { min-width: 25% !important; }
    header {visibility: hidden;}
    
    /* 按钮样式 */
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; border: none !important; height: 2rem !important;}
    
    /* 预览图样式 */
    .stImage { border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    
    /* 调整输入框和滑块高度 */
    div[data-testid="stNumberInput"] { margin-bottom: -1rem !important; }
    div[data-testid="stSlider"] { margin-bottom: -0.5rem !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法 ---
def smart_extract_multiple_subjects(pil_img):
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                     cv2.THRESH_BINARY_INV, 11, 2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15,15))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    extracted_images = []
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    for c in contours:
        area = cv2.contourArea(c)
        x, y, w, h = cv2.boundingRect(c)
        if area < 5000 or w > img.shape[1] * 0.9 or h > img.shape[0] * 0.9: continue
        if (w/float(h)) > 3.0 or (w/float(h)) < 0.3: continue
        crop_img = img[y:y+h, x:x+w]
        if crop_img.shape[0] < 50 or crop_img.shape[1] < 50: continue
        extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))
    return extracted_images if extracted_images else [pil_img]

# --- 3. 处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")
    tw, th = config['size']
    render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
    img.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
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
    if config['filter'] == "暖色调":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.1); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.1); res = Image.merge("RGB", (r, g, b))
    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    if ext == "JPEG":
        q = 85 if is_preview else 95
        while q > 20:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
            q -= 5
    else: bg.save(out_io, format="PNG")
    return out_io.getvalue(), ext

# --- 4. 极致紧凑侧边栏 ---
with st.sidebar:
    st.button("🗑️ 清空列表", on_click=reset_uploader, use_container_width=True)
    
    # 分辨率与体积并排
    c1, c2 = st.columns(2)
    with c1:
        res_opt = st.selectbox("分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
        tw, th = map(int, res_opt.split('*')) if res_opt != "自定义" else (1920, 1080)
    with c2:
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
    
    kb = 0
    if vol_opt == "自定义": kb = st.number_input("KB", 10, 5120, 500)
    elif vol_opt == "500KB": kb = 500
    elif vol_opt == "1MB": kb = 1024

    auto_crop = st.toggle("多主体拆解", value=True)
    
    # 背景与颜色/模糊并排
    bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色": p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊": b_radius = st.slider("模糊程度", 10, 100, 40)

    # 滤镜与画质
    flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"])
    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("锐化", 1.0, 4.0, 1.8)

# --- 5. 主界面 ---
st.title("🍽️ 餐影工坊 1.0")

files = st.file_uploader("上传图片/PDF", type=['jpg','jpeg','png','pdf'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    final_list = []
    with st.spinner("处理中..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pages = convert_from_bytes(f.read(), dpi=200)
                for i, p in enumerate(pages):
                    page_name = f.name.rsplit('.', 1)[0]
                    if auto_crop:
                        for idx, dish in enumerate(smart_extract_multiple_subjects(p)):
                            dish.filename = f"{page_name}_P{i+1}_{idx+1}.jpg"
                            final_list.append(dish)
                    else:
                        p.filename = f"{page_name}_P{i+1}.jpg"; final_list.append(p)
            else: final_list.append(f)

    conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh}

    st.subheader(f"🖼️ 预览 ({len(final_list)} 张)")
    with st.container(height=650, border=True):
        cols = st.columns(3)
        for idx, item in enumerate(final_list):
            with cols[idx % 3]:
                p_bytes, _ = process_engine(item, conf, is_preview=True)
                st.image(p_bytes, use_container_width=True, caption=getattr(item, 'filename', getattr(item, 'name', f"Img_{idx+1}")))

    with st.sidebar:
        st.success(f"就绪: {len(final_list)} 张")
        if st.button("🚀 导出 ZIP", use_container_width=True):
            zip_buf = io.BytesIO()
            p_bar = st.progress(0, text="打包中...")
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for idx, itm in enumerate(final_list):
                    data, ext = process_engine(itm, conf)
                    name_raw = getattr(itm, 'filename', getattr(itm, 'name', f"output_{idx}.jpg"))
                    zf.writestr(f"{name_raw.rsplit('.', 1)[0]}.{ext.lower()}", data)
                    p_bar.progress((idx+1)/len(final_list))
            st.download_button("📥 立即下载", zip_buf.getvalue(), f"Batch_{datetime.now().strftime('%H%M')}.zip", use_container_width=True)
else:
    st.info("💡 请上传文件开始。")
