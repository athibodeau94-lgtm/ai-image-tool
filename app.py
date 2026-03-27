import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 页面配置与高级感视觉 ---
st.set_page_config(page_title="高级菜品处理站", layout="wide", page_icon="🍱")

st.markdown("""
    <style>
    .stApp { background-color: #F0F4F2; }
    .stSidebar { background-color: #FFFFFF; border-right: 1px solid #E0E0E0; }
    .stButton>button { width: 100%; border-radius: 20px; background-color: #4A7C59; color: white; transition: 0.3s; }
    .stButton>button:hover { background-color: #2F5233; transform: scale(1.02); }
    .stDownloadButton>button { width: 100%; background-color: #68A357; color: white; border-radius: 20px; }
    div[data-testid="stExpander"] { border: none; background: white; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 缓存管理 ---
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 3. 侧边栏：精准控制 ---
with st.sidebar:
    st.title("🥗 处理面板")
    
    st.header("1. 分辨率预设")
    size_preset = st.selectbox("目标尺寸", ["1920*1080", "1000*600", "自定义"])
    if size_preset == "1920*1080": tw, th = 1920, 1080
    elif size_preset == "1000*600": tw, th = 1000, 600
    else:
        tw = st.number_input("宽", value=1920)
        th = st.number_input("高", value=1080)

    st.header("2. 背景模式 (原图填充)")
    bg_mode = st.radio("填充逻辑", ["深度高斯模糊背景", "原图直接延伸背景"])
    blur_radius = st.slider("模糊强度", 10, 150, 80) if bg_mode == "深度高斯模糊背景" else 0

    st.header("3. 效果调节")
    with st.expander("美化细节"):
        sharp_val = st.slider("去糊 (锐化)", 1.0, 3.0, 1.6)
        bright_val = st.slider("提亮", 1.0, 2.0, 1.2)
        filter_val = st.slider("暖色滤镜", 0.0, 1.0, 0.5)

    st.header("4. 导出控制")
    max_kb = st.selectbox("体积限制", ["不限制", "500KB", "1MB"])
    
    st.divider()
    if st.button("🗑️ 清空所有记录"):
        st.session_state.processed_files = []
        st.rerun()

# --- 4. 核心逻辑：修复背景填充 ---
def process_full_logic(bytes_data):
    img_arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if img is None: return None
    
    h, w = img.shape[:2]
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    raw_pil = Image.fromarray(img_rgb)

    # A. 生成背景：无论是哪种模式，都先用原图铺满全屏
    # 采用补全模式缩放原图作为背景
    bg_pil = raw_pil.resize((tw, th), Image.Resampling.LANCZOS)
    
    if bg_mode == "深度高斯模糊背景":
        bg_pil = bg_pil.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    # 如果是"原图直接延伸背景"，则保持 resize 后的原样，不做模糊

    # B. 主体处理：垂直居中，不缩放 (除非原图比画布还大)
    scale = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale), int(h * scale)
    main_img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_CUBIC)
    main_pil = Image.fromarray(cv2.cvtColor(main_img, cv2.COLOR_BGR2RGB))

    # C. 效果增强
    main_pil = ImageEnhance.Sharpness(main_pil).enhance(sharp_val)
    main_pil = ImageEnhance.Brightness(main_pil).enhance(bright_val)
    if filter_val > 0:
        enhancer = ImageEnhance.Color(main_pil)
        main_pil = enhancer.enhance(1.0 + 0.3 * filter_val)
        # 增加暖调
        r, g, b = main_pil.split()
        r = r.point(lambda i: i * (1 + 0.05 * filter_val))
        main_pil = Image.merge("RGB", (r, g, b))

    # D. 合成：主体置于背景之上
    offset = ((tw - nw) // 2, (th - nh) // 2)
    bg_pil.paste(main_pil, offset)

    # E. 体积控制
    limit = 0
    if max_kb == "500KB": limit = 500 * 1024
    elif max_kb == "1MB": limit = 1024 * 1024
    
    q = 95
    out_buf = io.BytesIO()
    while q > 15:
        out_buf = io.BytesIO()
        bg_pil.save(out_buf, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out_buf.tell() < limit: break
        q -= 5
    return out_buf.getvalue()

# --- 5. 交互界面 ---
st.title("👨‍🍳 菜品图专业处理站 (V2.0 纯净版)")
uploaded_files = st.file_uploader("📥 上传菜品图片 (支持批量，保留原名下载)", accept_multiple_files=True, type=['jpg','png','jpeg'])

if uploaded_files:
    for f in uploaded_files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在美化: {f.name}'):
                res_data = process_full_logic(f.read())
                if res_data:
                    save_name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                    st.session_state.processed_files.append({"name": save_name, "data": res_data})

# --- 6. 结果预览与下载 ---
if st.session_state.processed_files:
    st.divider()
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button(
        label=f"🟢 下载全部 {len(st.session_state.processed_files)} 张纯净菜品图",
        data=zip_io.getvalue(),
        file_name=f"food_export_{int(time.time())}.zip",
        mime="application/zip"
    )

    st.subheader("🖼️ 处理结果预览")
    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
