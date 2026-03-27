import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 页面配置与清新视觉风格 ---
st.set_page_config(page_title="菜品图像高级处理站", layout="wide", page_icon="🥗")

st.markdown("""
    <style>
    /* 清新薄荷绿配色 */
    .stApp { background-color: #F7FAF9; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #76C893; color: white; border: none; }
    .stButton>button:hover { background-color: #52B69A; color: white; }
    .stDownloadButton>button { width: 100%; background-color: #34A0A4; color: white; border-radius: 8px; }
    div[data-testid="stExpander"] { background-color: white; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 初始化缓存管理 ---
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 3. 侧边栏：参数控制中心 ---
with st.sidebar:
    st.title("🎨 处理设置")
    
    # 尺寸设置
    st.header("1. 尺寸与分辨率")
    size_preset = st.selectbox("选择预设尺寸", ["1920*1080", "1000*600", "自定义"])
    if size_preset == "1920*1080": tw, th = 1920, 1080
    elif size_preset == "1000*600": tw, th = 1000, 600
    else:
        tw = st.number_input("宽度 (px)", value=1920)
        th = st.number_input("高度 (px)", value=1080)

    # 背景处理
    st.header("2. 背景填充模式")
    bg_mode = st.radio("填充方式", ["深度高斯模糊", "提取边缘原色"])
    blur_radius = st.slider("模糊程度", 10, 100, 50) if bg_mode == "深度高斯模糊" else 0

    # 效果增强
    st.header("3. 效果增强")
    with st.expander("点击展开增强选项"):
        sharp_val = st.slider("去糊增强", 1.0, 3.0, 1.5)
        bright_val = st.slider("提亮程度", 1.0, 2.0, 1.2)
        filter_val = st.slider("暖色滤镜程度", 0.0, 1.0, 0.4)

    # 体积控制
    st.header("4. 输出限制")
    max_kb = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
    
    st.divider()
    if st.button("🗑️ 一键清空所有文件"):
        st.session_state.processed_files = []
        st.rerun()

# --- 4. 核心图像处理函数 ---
def process_full_logic(bytes_data, filename):
    img_arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if img is None: return None
    
    h, w = img.shape[:2]

    # A. 背景生成
    if bg_mode == "深度高斯模糊":
        bg = cv2.resize(img, (tw, th))
        bg_pil = Image.fromarray(cv2.cvtColor(bg, cv2.COLOR_BGR2RGB))
        bg_pil = bg_pil.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    else:
        edge_color = np.mean([img[0,0], img[0,w-1], img[h-1,0], img[h-1,w-1]], axis=0).astype(int)
        bg_pil = Image.new("RGB", (tw, th), tuple(edge_color[::-1]))

    # B. 主体处理：垂直居中，不缩放
    # 如果原图大于画布，则进行等比缩小以适应，否则保持原样居中
    scale = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale), int(h * scale)
    main_img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    main_pil = Image.fromarray(cv2.cvtColor(main_img, cv2.COLOR_BGR2RGB))

    # C. 效果增强 (仅针对主体菜品)
    main_pil = ImageEnhance.Sharpness(main_pil).enhance(sharp_val)
    main_pil = ImageEnhance.Brightness(main_pil).enhance(bright_val)
    
    # 滤镜处理
    if filter_val > 0:
        d = main_pil.getdata()
        new_d = [(int(r*(1+0.1*filter_val)), int(g*(1+0.05*filter_val)), int(b*(1-0.05*filter_val))) for r,g,b in d]
        main_pil.putdata(new_d)
        main_pil = ImageEnhance.Color(main_pil).enhance(1.0 + 0.2*filter_val)

    # D. 合成
    offset = ((tw - nw) // 2, (th - nh) // 2)
    bg_pil.paste(main_pil, offset)

    # E. 体积递归压缩
    limit = 0
    if max_kb == "500KB": limit = 500 * 1024
    elif max_kb == "1MB": limit = 1024 * 1024
    
    q = 95
    out_buf = io.BytesIO()
    while q > 10:
        out_buf = io.BytesIO()
        bg_pil.save(out_buf, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out_buf.tell() < limit: break
        q -= 5
    return out_buf.getvalue()

# --- 5. 网页主体交互 ---
st.title("🍳 菜品图专业处理工作站")
uploaded_files = st.file_uploader("📥 拖入菜品原图（支持批量，保留原文件名下载）", accept_multiple_files=True, type=['jpg','png','jpeg'])

if uploaded_files:
    for f in uploaded_files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在处理: {f.name}'):
                res_data = process_full_logic(f.read(), f.name)
                if res_data:
                    # 保留原文件名主体
                    new_name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                    st.session_state.processed_files.append({"name": new_name, "data": res_data})

# --- 6. 结果预览与一键下载 ---
if st.session_state.processed_files:
    st.divider()
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button(
        label=f"🟢 一键打包下载 {len(st.session_state.processed_files)} 张处理完成的图片",
        data=zip_io.getvalue(),
        file_name=f"processed_images_{int(time.time())}.zip",
        mime="application/zip"
    )

    st.subheader("🖼️ 处理预览窗口")
    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
