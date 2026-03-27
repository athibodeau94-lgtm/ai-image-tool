import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance
import io
import zipfile
import time

# --- 页面基本配置 ---
st.set_page_config(page_title="餐厅菜品美化工具", layout="wide", page_icon="🍱")

# 自定义按钮样式
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; background-color: #FF4B4B; color: white; }
    </style>
    """, unsafe_allow_html=True)

st.title("👨‍🍳 餐厅菜品专用·轻量美化系统")
st.caption("功能：菜品暖色滤镜 + 边缘色延展填充 + 原始文件名 + 一键清空。")

# --- 初始化 Session State ---
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("1. 尺寸设置")
    tw = st.number_input("目标宽度 (px)", value=1920, step=10)
    th = st.number_input("目标高度 (px)", value=1080, step=10)

    st.header("2. 菜品滤镜强度")
    filter_strength = st.slider("滤镜诱人程度", 0.0, 1.0, 0.4)
    
    st.divider()
    if st.button("🗑️ 一键清空所有文件"):
        st.session_state.processed_files = []
        st.rerun()

# --- 菜品专属滤镜算法 ---
def apply_food_filter(pil_img, strength):
    # 1. 适度提亮
    enhancer_bright = ImageEnhance.Brightness(pil_img)
    pil_img = enhancer_bright.enhance(1.0 + (0.15 * strength))
    
    # 2. 增加暖色调 (微调色彩平衡)
    data = pil_img.getdata()
    # 增加红色和黄色通道
    new_data = [
        (
            int(r * (1.0 + 0.1 * strength)), 
            int(g * (1.0 + 0.05 * strength)), 
            int(b * (1.0 - 0.05 * strength))
        ) for r, g, b in data
    ]
    pil_img.putdata(new_data)
    
    # 3. 适度增加饱和度
    enhancer_color = ImageEnhance.Color(pil_img)
    pil_img = enhancer_color.enhance(1.0 + (0.2 * strength))
    
    return pil_img

# --- 核心处理逻辑 ---
def process_with_food_style(bytes_data, strength):
    img_arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if img is None: return None
    
    h, w = img.shape[:2]

    # 1. 提取边缘主色调用于填充
    edge_color = np.mean([img[0,0], img[0,w-1], img[h-1,0], img[h-1,w-1]], axis=0).astype(int)
    canvas = np.full((th, tw, 3), edge_color, dtype=np.uint8)

    # 2. 居中缩放
    scale = min(tw/w, th/h)
    nw, nh = int(w * scale), int(h * scale)
    resized_img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    
    y_off = (th - nh) // 2
    x_off = (tw - nw) // 2
    canvas[y_off:y_off+nh, x_off:x_off+nw] = resized_img

    # 3. 应用菜品专用滤镜
    res_pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    if strength > 0:
        res_pil = apply_food_filter(res_pil, strength)
    
    # 4. 保存
    out_buf = io.BytesIO()
    res_pil.save(out_buf, format="JPEG", quality=90, optimize=True)
    return out_buf.getvalue()

# --- 交互界面 ---
uploaded_files = st.file_uploader(
    "👉 拖入需要批量处理的菜品原图", 
    accept_multiple_files=True, 
    type=['jpg','png','jpeg']
)

if uploaded_files:
    for f in uploaded_files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在美化: {f.name}'):
                result_data = process_with_food_style(f.read(), filter_strength)
                if result_data:
                    # 保留原名
                    new_name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                    st.session_state.processed_files.append({"name": new_name, "data": result_data})

if st.session_state.processed_files:
    st.divider()
    
    # 打包下载按钮
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button(
        label=f"🚀 一键打包下载 {len(st.session_state.processed_files)} 张美化后的菜品图",
        data=zip_io.getvalue(),
        file_name=f"food_ready_{int(time.time())}.zip",
        mime="application/zip"
    )

    # 预览
    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
