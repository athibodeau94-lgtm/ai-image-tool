import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 视觉风格配置 ---
st.set_page_config(page_title="高级菜品美化站", layout="wide", page_icon="🥗")
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

# --- 2. 侧边栏 ---
with st.sidebar:
    st.title("🥗 配置面板")
    size_preset = st.selectbox("1. 目标分辨率", ["1920*1080", "1000*600", "自定义"])
    tw, th = (1920, 1080) if "1920" in size_preset else (1000, 600)

    bg_mode = st.radio("2. 背景模式", ["原图高斯模糊 (推荐)", "原图直接拉伸"])
    blur_r = st.slider("模糊程度", 20, 150, 80) if "模糊" in bg_mode else 0

    st.header("3. 效果调节")
    sharp_v = st.slider("去糊 (锐化)", 1.0, 3.0, 1.7)
    bright_v = st.slider("提亮", 1.0, 2.0, 1.25)
    filter_v = st.slider("暖色滤镜", 0.0, 1.0, 0.6)

    max_kb = st.selectbox("4. 体积控制", ["不限制", "500KB", "1MB"])
    
    if st.button("🗑️ 清空所有预览"):
        st.session_state.processed_files = []
        st.rerun()

# --- 3. 核心修复逻辑：确保无黑边 ---
def process_safe_logic(bytes_data):
    # 使用 PIL 确保处理稳定性
    raw_pil = Image.open(io.BytesIO(bytes_data)).convert("RGB")
    w, h = raw_pil.size

    # A. 彻底解决黑边：强制将背景拉伸到全屏，铺满每一寸画布
    bg = raw_pil.resize((tw, th), Image.Resampling.LANCZOS)
    if "模糊" in bg_mode:
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_r))
    
    # B. 主体保持比例居中
    scale = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale), int(h * scale)
    main_img = raw_pil.resize((nw, nh), Image.Resampling.LANCZOS)

    # C. 主体效果美化
    main_img = ImageEnhance.Sharpness(main_img).enhance(sharp_v)
    main_img = ImageEnhance.Brightness(main_img).enhance(bright_v)
    if filter_v > 0:
        r, g, b = main_img.split()
        r = r.point(lambda i: i * (1 + 0.1 * filter_v))
        g = g.point(lambda i: i * (1 + 0.05 * filter_v))
        main_img = Image.merge("RGB", (r, g, b))
        main_img = ImageEnhance.Color(main_img).enhance(1.0 + 0.2 * filter_v)

    # D. 合成：贴在已经铺满的背景上，绝无黑条
    offset = ((tw - nw) // 2, (th - nh) // 2)
    bg.paste(main_img, offset)

    # E. 导出与体积控制
    limit = 500 * 1024 if max_kb == "500KB" else (1024 * 1024 if max_kb == "1MB" else 0)
    q = 95
    out = io.BytesIO()
    while q > 15:
        out = io.BytesIO()
        bg.save(out, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out.tell() < limit: break
        q -= 5
    return out.getvalue()

# --- 4. 界面交互 ---
st.title("🍳 菜品工作站 (终极无黑边版)")
files = st.file_uploader("📥 批量上传图片", accept_multiple_files=True, type=['jpg','png','jpeg'])

if files:
    for f in files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在美化: {f.name}'):
                res = process_safe_logic(f.read())
                if res:
                    save_name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                    st.session_state.processed_files.append({"name": save_name, "data": res})

if st.session_state.processed_files:
    st.divider()
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button("🟢 下载全部美化图 (打包)", zip_io.getvalue(), f"food_ready_{int(time.time())}.zip", "application/zip")

    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
