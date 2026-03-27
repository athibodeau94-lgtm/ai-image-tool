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

# --- 2. 核心算法：激进裁切 ---
def smart_crop_dish_aggressive(pil_img):
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        if w > 80 and h > 80:
            crop_img = img[y:y+h, x:x+w]
            return Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
    return pil_img

# --- 3. 增强引擎 (找回体积控制) ---
def process_engine(img_input, config, is_preview=False):
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    if config.get('auto_crop', True):
        img = smart_crop_dish_aggressive(img).convert("RGBA")
    
    tw, th = config['size']
    ratio = min(tw / img.size[0], th / img.size[1])
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
    img_fit = img.resize(new_size, Image.Resampling.LANCZOS)

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
    
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    
    if ext == "JPEG":
        q = 95
        limit = config['limit_kb'] * 1024 if config['limit_kb'] > 0 else 999999999
        while q > 15:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= limit or is_preview: break
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
    if res_opt == "自定义":
        tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))

    # --- 【体积控制自定义优化】 ---
    vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
    if vol_opt == "自定义":
        kb = st.number_input("输入限制 (KB)", 10, 5120, 300)
    elif vol_opt == "不限制":
        kb = 0
    else:
        kb = 500 if vol_opt == "500KB" else 1024

    auto_crop = st.toggle("激进版自动裁切脏边", value=True)
    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色":
        p_color = st.selectbox("颜色选择", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊":
        b_radius = st.slider("模糊程度", 0, 100, 40)

    flt = st.selectbox("选择滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("锐化强度", 1.0, 4.0, 1.8)

# --- 5. 主逻辑 ---
st.title("🍽️ 餐影工坊 Pro Max")

files = st.file_uploader("上传图片或PDF", type=['jpg','jpeg','png','pdf'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    final_list = []
    with st.spinner("解析素材中..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pages = convert_from_bytes(f.read(), dpi=300)
                for i, page in enumerate(pages):
                    page.filename = f"{f.name.rsplit('.', 1)[0]}_P{i+1}.jpg"
                    final_list.append(page)
            else:
                final_list.append(f)

    conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'auto_crop': auto_crop}

    st.subheader("👀 实时预览")
    p_bytes, p_ext = process_engine(final_list[0], conf, is_preview=True)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.image(p_bytes, use_container_width=True)
    with col2:
        st.success(f"就绪: {len(final_list)} 张")
        if len(final_list) == 1:
            data, ext = process_engine(final_list[0], conf)
            fname = getattr(final_list[0], 'filename', final_list[0].name).rsplit('.', 1)[0]
            st.download_button("📥 下载单图", data, f"{fname}_{tw}x{th}.{ext.lower()}", use_container_width=True)
        else:
            if st.button("🚀 批量合成全部", use_container_width=True):
                today = datetime.now().strftime("%Y-%m-%d")
                zip_name = f"{today}_{tw}x{th}.zip"; zip_buf = io.BytesIO()
                p_bar = st.progress(0)
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for idx, itm in enumerate(final_list):
                        data, ext = process_engine(itm, conf)
                        raw_name = getattr(itm, 'filename', itm.name)
                        zf.writestr(f"{raw_name.rsplit('.', 1)[0]}.{ext.lower()}", data)
                        p_bar.progress((idx+1)/len(final_list))
                st.download_button("📦 下载 ZIP", zip_buf.getvalue(), zip_name, use_container_width=True)
