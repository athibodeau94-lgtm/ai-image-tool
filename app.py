import streamlit as st
import cv2
import numpy as np
from PIL import Image
import io
import zipfile
import time

# --- 页面基本配置 ---
st.set_page_config(page_title="菜品背景自动延展工具", layout="wide", page_icon="🍳")

# 自定义 CSS 样式
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    .stDownloadButton>button { width: 100%; background-color: #4CAF50; color: white; }
    </style>
    """, unsafe_allow_html=True)

st.title("👨‍🍳 菜品图原色填充工具 (无 AI 干扰版)")
st.caption("功能：提取原图边缘色填充尺寸 + 保留原名 + 一键清空缓存。")

# --- 初始化 Session State 用于管理文件列表 ---
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("1. 尺寸设置")
    tw = st.number_input("目标宽度 (px)", value=1920, step=10)
    th = st.number_input("目标高度 (px)", value=1080, step=10)

    st.header("2. 导出设置")
    max_kb_limit = st.selectbox("单张体积限制", ["500KB", "1MB", "不限制"])
    
    st.divider()
    # 一键清空按钮
    if st.button("🗑️ 一键清空处理记录"):
        st.session_state.processed_files = []
        st.rerun()

# --- 核心图像处理：边缘色填充 ---
def extend_image_with_edge_color(bytes_data):
    img_arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if img is None: return None
    
    h, w = img.shape[:2]

    # 1. 提取边缘的主导颜色 (取四角的平均值)
    top_left = img[0, 0]
    top_right = img[0, w-1]
    bottom_left = img[h-1, 0]
    bottom_right = img[h-1, w-1]
    avg_color = np.mean([top_left, top_right, bottom_left, bottom_right], axis=0).astype(int)
    
    # 2. 创建纯色画布
    canvas = np.full((th, tw, 3), avg_color, dtype=np.uint8)

    # 3. 按照高度比例缩放原图，使其居中
    scale = th / h
    nw, nh = int(w * scale), th
    
    # 如果缩放后宽度超过画布，则按宽度缩放
    if nw > tw:
        scale = tw / w
        nw, nh = tw, int(h * scale)
        
    resized_img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    
    # 4. 将缩放后的图贴到画布中心
    y_off = (th - nh) // 2
    x_off = (tw - nw) // 2
    canvas[y_off:y_off+nh, x_off:x_off+nw] = resized_img

    # 5. 转换为 PIL 进行保存
    res_pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    
    # 6. 体积控制
    limit_bytes = 0
    if max_kb_limit == "500KB": limit_bytes = 500 * 1024
    elif max_kb_limit == "1MB": limit_bytes = 1024 * 1024
    
    q = 95
    out_buf = io.BytesIO()
    while q > 10:
        out_buf = io.BytesIO()
        res_pil.save(out_buf, format="JPEG", quality=q, optimize=True)
        if limit_bytes == 0 or out_buf.tell() < limit_bytes:
            break
        q -= 5
        
    return out_buf.getvalue()

# --- 文件上传逻辑 ---
uploaded_files = st.file_uploader(
    "👉 请拖入需要处理的菜品图片", 
    accept_multiple_files=True, 
    type=['jpg','png','jpeg'],
    key="file_uploader"
)

if uploaded_files:
    # 仅处理新上传的文件
    for f in uploaded_files:
        # 检查是否已经在 session 中（防止重复处理）
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在处理: {f.name}'):
                result_data = extend_image_with_edge_color(f.read())
                if result_data:
                    st.session_state.processed_files.append({
                        "name": f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg",
                        "data": result_data
                    })

# --- 显示结果与下载 ---
if st.session_state.processed_files:
    st.success(f"当前共有 {len(st.session_state.processed_files)} 张待下载图片")
    
    # 打包下载
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button(
        label="📦 一键打包下载全部处理后的文件",
        data=zip_io.getvalue(),
        file_name=f"batch_processed_{int(time.time())}.zip",
        mime="application/zip"
    )

    # 预览区域
    st.divider()
    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
