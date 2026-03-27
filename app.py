import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# 尝试加载 PDF 支持
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

st.markdown(f"""
    <style>
    [data-testid="stSidebar"] * {{ font-size: 0.85rem !important; }}
    [data-testid="stSidebar"] {{ min-width: 28% !important; max-width: 28% !important; }}
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.3rem !important; padding-top: 0.5rem !important; }}
    .stMarkdown h1, .stMarkdown h2 {{ font-size: 1.1rem !important; margin-bottom: 0.1rem !important; }}
    header {{visibility: hidden;}}
    div[data-testid="stSidebar"] button:first-child {{ background-color: #ff4b4b !important; color: white !important; border: none !important; }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：智能多主体提取 ---
def smart_extract_multiple_subjects(pil_img):
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
        aspect_ratio = w / float(h)
        if area < 5000 or w > img.shape[1] * 0.9 or h > img.shape[0] * 0.9: continue
        if aspect_ratio > 3.0 or aspect_ratio < 0.3: continue
        
        crop_img = img[y:y+h, x:x+w]
        if crop_img.shape[0] < 50 or crop_img.shape[1] < 50: continue
        extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))

    return extracted_images if extracted_images else [pil_img]

# --- 3. 增强处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    # 尺寸缩放
    tw, th = config['size']
    ratio = min(tw / img.size[0], th / img.size[1])
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
    img_fit = img.resize(new_size, Image.Resampling.LANCZOS)

    # 背景合成
    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
    else:
        sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        bg = Image.new("RGBA", (tw, th), sample + (255,))

    bg.paste(img_fit, ((tw - new_size[0]) // 2, (th - new_size[1]) // 2), img_fit)
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    # 压缩逻辑
    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    if ext == "JPEG":
        q = 95
        limit_kb = config['limit_kb']
        while q > 15:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= limit_kb * 1024 or is_preview or limit_kb == 0: break
            q -= 5
    else:
        bg.save(out_io, format="PNG")
    return out_io.getvalue(), ext

# --- 4. 侧边栏 ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    st.button("🗑️ 一键清空处理列表", on_click=reset_uploader, use_container_width=True)
    st.markdown("---")
    
    res_opt = st.selectbox("目标分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
    tw, th = (1920, 1080)
    if res_opt == "自定义":
        tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))

    vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
    kb_val = 0
    if vol_opt == "自定义":
        col_v, col_u = st.columns([2, 1])
        with col_u: unit = st.radio("单位", ["KB", "MB"], horizontal=True)
        with col_v:
            if unit == "KB": kb_val = st.number_input("数值", 10, 102400, 500)
            else: kb_val = int(st.number_input("数值", 0.1, 100.0, 1.0, step=0.1) * 1024)
    elif vol_opt != "不限制":
        kb_val = 500 if vol_opt == "500KB" else 1024

    auto_crop = st.toggle("激进裁切 & 多主体拆解", value=True)
    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色": p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊": b_radius = st.slider("模糊程度", 0, 100, 40)

    flt = st.selectbox("滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度", 0.5, 1.5, 1.05); sh = st.slider("锐化", 1.0, 4.0, 1.8)

# --- 5. 主逻辑 ---
st.title("🍽️ 餐影工坊 Pro Max")

files = st.file_uploader("上传文件", type=['jpg','jpeg','png','pdf'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    final_dishes_list = []
    with st.spinner("正在解析素材..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pdf_pages = convert_from_bytes(f.read(), dpi=300)
                for i, page in enumerate(pdf_pages):
                    if auto_crop:
                        extracted = smart_extract_multiple_subjects(page)
                        for idx, dish in enumerate(extracted):
                            dish.filename = f"{f.name.rsplit('.', 1)[0]}_P{i+1}_{idx+1}.jpg"
                            final_dishes_list.append(dish)
                    else:
                        page.filename = f"{f.name.rsplit('.', 1)[0]}_P{i+1}.jpg"
                        final_dishes_list.append(page)
            else:
                final_dishes_list.append(f)

    conf = {'size': (tw, th), 'limit_kb': kb_val, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'auto_crop': auto_crop}

    # 【修复重点】：安全获取名称，解决 AttributeError
    sample_item = final_dishes_list[0]
    display_name = getattr(sample_item, 'filename', getattr(sample_item, 'name', "未知素材"))
    
    p_bytes, p_ext = process_engine(sample_item, conf, is_preview=True)
    
    st.subheader("👀 实时预览")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.image(p_bytes, use_container_width=True, caption=f"预览效果：{display_name}")
    with col2:
        st.success(f"就绪: {len(final_dishes_list)} 张")
        if st.button("🚀 批量合成下载", use_container_width=True):
            zip_buf = io.BytesIO()
            p_bar = st.progress(0)
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for idx, itm in enumerate(final_dishes_list):
                    data, ext = process_engine(itm, conf)
                    fname = getattr(itm, 'filename', getattr(itm, 'name', f"img_{idx}.jpg"))
                    zf.writestr(f"{fname.rsplit('.', 1)[0]}.{ext.lower()}", data)
                    p_bar.progress((idx+1)/len(final_dishes_list))
            st.download_button("📦 下载 ZIP", zip_buf.getvalue(), "processed_images.zip", use_container_width=True)
