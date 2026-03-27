import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 页面清新风格 ---
st.set_page_config(page_title="菜品图像美化站", layout="wide", page_icon="🥗")
st.markdown("""
    <style>
    .stApp { background-color: #F8FBFA; }
    .stSidebar { background-color: #FFFFFF; }
    .stButton>button { width: 100%; border-radius: 20px; background-color: #588157; color: white; }
    .stDownloadButton>button { width: 100%; background-color: #3A5A40; color: white; border-radius: 20px; }
    </style>
    """, unsafe_allow_html=True)

if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 侧边栏 ---
with st.sidebar:
    st.title("🥗 配置面板")
    size_preset = st.selectbox("1. 目标尺寸", ["1920*1080", "1000*600", "自定义"])
    if size_preset == "1920*1080": tw, th = 1920, 1080
    elif size_preset == "1000*600": tw, th = 1000, 600
    else:
        tw = st.number_input("宽", value=1920)
        th = st.number_input("高", value=1080)

    bg_mode = st.radio("2. 背景处理", ["原图深度模糊", "原图拉伸填充"])
    blur_r = st.slider("模糊半径", 20, 150, 80) if bg_mode == "原图深度模糊" else 0

    st.header("3. 效果增强")
    sharp_v = st.slider("去糊 (锐化)", 1.0, 3.0, 1.6)
    bright_v = st.slider("提亮", 1.0, 2.0, 1.2)
    filter_v = st.slider("暖色滤镜", 0.0, 1.0, 0.5)

    max_kb = st.selectbox("4. 体积控制", ["不限制", "500KB", "1MB"])
    
    st.divider()
    if st.button("🗑️ 一键清空预览"):
        st.session_state.processed_files = []
        st.rerun()

# --- 核心逻辑：确保无黑边 ---
def process_final_clean(bytes_data):
    # 1. 加载原图
    raw_img = Image.open(io.BytesIO(bytes_data)).convert("RGB")
    w, h = raw_img.size

    # 2. 生成背景：强制拉伸铺满全屏，彻底杜绝黑边
    bg = raw_img.resize((tw, th), Image.Resampling.LANCZOS)
    if bg_mode == "原图深度模糊":
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_r))
    
    # 3. 处理主体：垂直居中，不缩放（除非太大）
    scale = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale), int(h * scale)
    main_img = raw_img.resize((nw, nh), Image.Resampling.LANCZOS)

    # 4. 效果增强
    main_img = ImageEnhance.Sharpness(main_img).enhance(sharp_v)
    main_img = ImageEnhance.Brightness(main_img).enhance(bright_v)
    if filter_v > 0:
        # 暖调滤镜逻辑
        r, g, b = main_img.split()
        r = r.point(lambda i: i * (1 + 0.1 * filter_v))
        g = g.point(lambda i: i * (1 + 0.05 * filter_v))
        main_img = Image.merge("RGB", (r, g, b))
        main_img = ImageEnhance.Color(main_img).enhance(1.0 + 0.2 * filter_v)

    # 5. 合成：将纯净主体贴在已经铺满的背景上
    offset = ((tw - nw) // 2, (th - nh) // 2)
    bg.paste(main_img, offset)

    # 6. 体积控制
    limit = 0
    if max_kb == "500KB": limit = 500 * 1024
    elif max_kb == "1MB": limit = 1024 * 1024
    
    q = 95
    out = io.BytesIO()
    while q > 15:
        out = io.BytesIO()
        bg.save(out, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out.tell() < limit: break
        q -= 5
    return out.getvalue()

# --- 界面交互 ---
st.title("🍳 菜品工作站 (无黑边·纯净版)")
files = st.file_uploader("📥 批量上传图片", accept_multiple_files=True, type=['jpg','png','jpeg'])

if files:
    for f in files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在美化: {f.name}'):
                data = process_final_clean(f.read())
                if data:
                    name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                    st.session_state.processed_files.append({"name": name, "data": data})

if st.session_state.processed_files:
    st.divider()
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button("🟢 一键打包下载全部纯净图", zip_io.getvalue(), f"food_ready_{int(time.time())}.zip", "application/zip")

    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
