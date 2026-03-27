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
    /* 强制清空按钮红色 */
    div[data-testid="stSidebar"] button:first-child {{ background-color: #ff4b4b !important; color: white !important; border: none !important; }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：激进裁切 (已修复小括号问题) ---
def smart_crop_dish_aggressive(pil_img):
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
    # 【修复位】：确保括弧完整闭合
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        if w > 80 and h > 80:
            crop_img = img[y:y+h, x:x+w]
            return Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
    return pil_img

# --- 3. 增强引擎 (集成体积控制) ---
def process_engine(img_input, config, is_preview=False):
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_
