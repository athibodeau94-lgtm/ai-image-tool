import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 网页可爱风配置 ---
st.set_page_config(page_title="高级菜品美化站", layout="wide", page_icon="🍱")
st.markdown("""
    <style>
    .stApp { background-color: #FFF9FB; } 
    .stSidebar { background-color: #FFFFFF; border-right: 2px solid #FFE4E1; }
    .stButton>button { width: 100%; border-radius: 25px; background-color: #FFB6C1; color: white; border: none; font-weight: bold; }
    .stDownloadButton>button { width: 100%; background-color: #87CEEB; color: white; border-radius: 25px; font-weight: bold; }
    h1, h2, h3 { color: #FF69B4; font-family: 'Comic Sans MS', cursive; }
    </style>
    """, unsafe_allow_html=True)

if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 2. 功能面板 ---
with st.sidebar:
    st.title("🍓 调料盒")
    size_preset = st.selectbox("1. 尺寸预设", ["1920*1080 (HD)", "1000*600 (Web)", "自定义"])
    tw, th = (1920, 1080) if "1920" in size_preset else (1000, 600)

    st.header("2. 背景深度模糊")
    blur_r = st.slider("模糊程度 (图二质感)", 20, 150, 85)

    st.header("3. 效果调优")
    sharp_v = st.slider("去糊 (锐化)", 1.0, 3.0, 1.7)
    bright_v = st.slider("提亮", 1.0, 2.0, 1.25)
    filter_v = st.slider("暖色程度", 0.0, 1.0, 0.6)

    st.header("4. 导出设置")
    max_kb = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
    
    if st.button("🧼 一键清空"):
        st.session_state.processed_files = []
        st.rerun()

# --- 3. 核心修复：物理级覆盖背景 ---
def process_ultimate_logic(bytes_data):
    raw = Image.open(io.BytesIO(bytes_data)).convert("RGB")
    w, h = raw.size

    # 【关键修复】生成一张纯白的、规定尺寸的画布，作为最底层
    final_canvas = Image.new("RGB", (tw, th), (255, 255, 255))

    # 【核心修复】强制拉伸原图铺满整个 tw*th 区域作为背景，绝不留白/黑缝
    bg = raw.resize((tw, th), Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_r))
    
    # 将模糊背景贴满画布
    final_canvas.paste(bg, (0, 0))

    # 主体处理：垂直居中，不拉伸
    scale = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale), int(h * scale)
    main_img = raw.resize((nw, nh), Image.Resampling.LANCZOS)

    # 主体美化
    main_img = ImageEnhance.Sharpness(main_img).enhance(sharp_v)
    main_img = ImageEnhance.Brightness(main_img).enhance(bright_v)
    if filter_v > 0:
        r, g, b = main_img.split()
        r = r.point(lambda i: i * (1 + 0.1 * filter_v))
        g = g.point(lambda i: i * (1 + 0.05 * filter_v))
        main_img = Image.merge("RGB", (r, g, b))
        main_img = ImageEnhance.Color(main_img).enhance(1.0 + 0.25 * filter_v)

    # 贴主体
    offset = ((tw - nw) // 2, (th - nh) // 2)
    final_canvas.paste(main_img, offset)

    # 体积控制
    limit = 500 * 1024 if max_kb == "500KB" else (1024 * 1024 if max_kb == "1MB" else 0)
    q = 95
    out = io.BytesIO()
    while q > 15:
        out = io.BytesIO()
        final_canvas.save(out, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out.tell() < limit: break
        q -= 5
    return out.getvalue()

# --- 4. 界面展示 ---
st.title("💖 萌萌菜品美化屋")
files = st.file_uploader("✨ 拖入图片", accept_multiple_files=True, type=['jpg','png','jpeg'])

if files:
    for f in files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            res = process_ultimate_logic(f.read())
            if res:
                save_name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                st.session_state.processed_files.append({"name": save_name, "data": res})

if st.session_state.processed_files:
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button("📦 打包下载", zip_io.getvalue(), f"ready_{int(time.time())}.zip", "application/zip")

    st.subheader("📸 成果预览 (已物理除黑)")
    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
