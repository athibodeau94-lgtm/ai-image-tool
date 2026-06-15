import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io, zipfile, os, cv2, fitz
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置与状态初始化 ---
st.set_page_config(page_title="餐影工坊", layout="wide")

# 初始化四个角点物理坐标的 session_state (百分比单位)
if 'pts' not in st.session_state:
    st.session_state.pts = [
        [5, 15],   # 左上 [x, y]
        [95, 5],   # 右上 [x, y]
        [5, 90],   # 左下 [x, y]
        [95, 80]   # 右下 [x, y]
    ]

# --- 2. 样式注入 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage > img { 
        border-radius: 4px; object-fit: contain; background-color: #ffffff;
        background-image: linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0), 
                          linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0) !important;
        background-size: 16px 16px !important; background-position: 0 0, 8px 8px !important;
    }
    .stDownloadButton, .stButton { margin-bottom: -10px; }
    /* 紧凑型按钮组样式 */
    div.stButton > button { padding: 4px 10px !important; hieght: auto !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 ---
def perspective_crop_plate(img_obj, pts_pct):
    try:
        src = np.array(img_obj)
        if src.shape[2] < 4:
            src = cv2.cvtColor(src, cv2.COLOR_RGB2RGBA)
        h, w = src.shape[:2]
        
        src_pts = np.array([
            [pts_pct[0][0] * w / 100.0, pts_pct[0][1] * h / 100.0],
            [pts_pct[1][0] * w / 100.0, pts_pct[1][1] * h / 100.0],
            [pts_pct[2][0] * w / 100.0, pts_pct[2][1] * h / 100.0],
            [pts_pct[3][0] * w / 100.0, pts_pct[3][1] * h / 100.0]
        ], dtype=np.float32)
        
        width_a = np.sqrt(((src_pts[1][0] - src_pts[0][0]) ** 2) + ((src_pts[1][1] - src_pts[0][1]) ** 2))
        width_b = np.sqrt(((src_pts[3][0] - src_pts[2][0]) ** 2) + ((src_pts[3][1] - src_pts[2][1]) ** 2))
        max_width = max(int(width_a), int(width_b), 50)

        height_a = np.sqrt(((src_pts[2][0] - src_pts[0][0]) ** 2) + ((src_pts[2][1] - src_pts[0][1]) ** 2))
        height_b = np.sqrt(((src_pts[3][3] - src_pts[1][1]) ** 2) + ((src_pts[3][0] - src_pts[1][0]) ** 2))
        max_height = max(int(height_a), int(height_b), 50)
        
        dst_pts = np.array([[0, 0], [max_width - 1, 0], [0, max_height - 1], [max_width - 1, max_height - 1]], dtype=np.float32)
        m = cv2.getPerspectiveTransform(src_pts, dst_pts)
        warped = cv2.warpPerspective(src, m, (max_width, max_height))
        return Image.fromarray(warped)
    except:
        return img_obj

def super_resolve_and_sharpen(img_obj):
    w, h = img_obj.size
    if w < 1000 or h < 1000:
        scale_factor = 2 if max(w, h) > 500 else 3
        img_obj = img_obj.resize((int(w * scale_factor), int(h * scale_factor)), Image.Resampling.LANCZOS)
    return ImageEnhance.Sharpness(img_obj.filter(ImageFilter.EDGE_ENHANCE)).enhance(1.4)

def process_engine(img_input, config, pts_pct=None):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            raw_bytes = img_input if isinstance(img_input, bytes) else img_input.getvalue()
            img = Image.open(io.BytesIO(raw_bytes))
        else:
            img = Image.open(io.BytesIO(img_input.getvalue())) if hasattr(img_input, 'getvalue') else img_input

        img = img.convert("RGBA")
        if config.get('auto_crop', False) and pts_pct is not None:
            img = perspective_crop_plate(img, pts_pct)
            
        target_w, target_h = config['size']
        is_transparent = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            img_resized = img.resize((int(original_w * ratio), int(original_h * ratio)), Image.Resampling.LANCZOS)
            
            if is_transparent:
                bg = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            elif config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4)).filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                c = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255)}.get(config['pure_color'], (255,255,255,255))
                bg = Image.new("RGBA", (target_w, target_h), c)
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            bg.alpha_composite(img_resized, ((target_w - img_resized.size[0]) // 2, (target_h - img_resized.size[1]) // 2))
            res_img = bg

        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        if is_transparent:
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            res_img.convert("RGB").save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

# --- 5. Streamlit 主交互界面 ---
left_col, right_col = st.columns([1.4, 2.3], gap="large")

with left_col:
    st.subheader("导入中心")
    raw_uploads = st.file_uploader("支持多选图片、ZIP或PDF", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True)
    processed_list = []
    zip_prefix = ""

    if raw_uploads:
        zip_files = [f for f in raw_uploads if f.name.lower().endswith('.zip')]
        pdf_files = [f for f in raw_uploads if f.name.lower().endswith('.pdf')]
        if zip_files:
            zip_prefix = os.path.splitext(zip_files[0].name)[0]
            with zipfile.ZipFile(zip_files[0]) as z:
                for f in z.namelist():
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.startswith('__MACOSX'):
                        with z.open(f) as img_f: processed_list.append({"name": os.path.basename(f), "content": img_f.read()})
        elif pdf_files:
            zip_prefix = os.path.splitext(pdf_files[0].name)[0]
            doc = fitz.open(stream=pdf_files[0].getvalue(), filetype="pdf")
            for page in doc:
                for img_info in page.get_images(full=True):
                    raw_pil = Image.open(io.BytesIO(doc.extract_image(img_info[0])["image"]))
                    hd_io = io.BytesIO()
                    super_resolve_and_sharpen(
