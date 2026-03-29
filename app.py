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
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem !important; padding-top: 0rem !important; }
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    [data-testid="stSidebar"] { min-width: 25% !important; }
    header {visibility: hidden;}
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; border: none !important; height: 2rem !important;}
    .stImage { border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
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
        crop_img =
