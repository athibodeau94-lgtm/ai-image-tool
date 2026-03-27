import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 网页可爱风视觉配置 ---
st.set_page_config(page_title="高级菜品美化站", layout="wide", page_icon="🍱")
st.markdown("""
    <style>
    .stApp { background-color: #FFF9FB; } /* 浅粉白底色 */
    .stSidebar { background-color: #FFFFFF; border-right: 2px solid #FFE4E1; }
    .stButton>button { width: 100%; border-radius: 25px; background-color: #FFB6C1; color: white; border: none; font-weight: bold; }
    .stButton>button:hover { background-color: #FF8C94; transform: scale(1.02); }
    .stDownloadButton>button { width: 100%; background-color: #87CEEB; color: white; border-radius: 25px; font-weight: bold; }
    div[data-testid="stExpander"] { background: white; border-radius: 15px; border: 1px solid #FFE4E1; }
    h1, h2, h3 { color: #FF69B4; font-family: 'Comic Sans MS', cursive; }
    </style>
    """, unsafe_allow_html=True)

if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

# --- 2. 侧边栏：功能控制面板 ---
with st.sidebar:
    st.title("🍓 调料盒")
    
    st.header("1. 尺寸预设")
    size_preset = st.selectbox("选择分辨率", ["1920*1080 (HD)", "1000*600 (Web)", "自定义"])
    if "1920" in size_preset: tw, th = 1920, 1080
    elif "1000" in size_preset: tw, th = 1000, 600
    else:
        tw = st.number_input("宽", value=1920)
        th = st.number_input("高", value=1080)

    st.header("2. 背景魔法 (彻底除黑)")
    bg_mode = st.radio("填充逻辑", ["深度高斯模糊 (推荐)", "原图拉伸填充"])
    blur_r = st.slider("模糊程度", 10, 150, 80) if "模糊" in bg_mode else 0

    st.header("3. 效果调优")
    with st.expander("更多细节调节"):
        sharp_v = st.slider("去糊 (锐化)", 1.0, 3.0, 1.7)
        bright_v = st.slider("提亮", 1.0, 2.0, 1.25)
        filter_v = st.slider("暖色滤镜程度", 0.0, 1.0, 0.6)

    st.header("4. 导出设置")
    max_kb = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
    
    st.divider()
    if st.button("🧼 一键清空所有数据"):
        st.session_state.processed_files = []
        st.rerun()

# --- 3. 核心算法：100% 覆盖逻辑 ---
def process_perfect_logic(bytes_data):
    # 使用 PIL 保证最稳健的背景覆盖
    raw_img = Image.open(io.BytesIO(bytes_data)).convert("RGB")
    w, h = raw_img.size

    # A. 核心修复：背景先行，强制铺满全屏，绝不留黑边
    # 不管原图比例，强制 resize 到目标尺寸作为底图
    bg = raw_img.resize((tw, th), Image.Resampling.LANCZOS)
    
    if "模糊" in bg_mode:
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_r))
    
    # B. 主体处理：垂直居中，不缩放 (除非图片比画布还大)
    scale = min(tw/w, th/h) if (w > tw or h > th) else 1.0
    nw, nh = int(w * scale), int(h * scale)
    main_img = raw_img.resize((nw, nh), Image.Resampling.LANCZOS)

    # C. 效果增强
    main_img = ImageEnhance.Sharpness(main_img).enhance(sharp_v)
    main_img = ImageEnhance.Brightness(main_img).enhance(bright_v)
    if filter_v > 0:
        r, g, b = main_img.split()
        r = r.point(lambda i: i * (1 + 0.1 * filter_v))
        g = g.point(lambda i: i * (1 + 0.05 * filter_v))
        main_img = Image.merge("RGB", (r, g, b))
        main_img = ImageEnhance.Color(main_img).enhance(1.0 + 0.25 * filter_v)

    # D. 合成：将主体贴在已完全覆盖的背景中央
    offset = ((tw - nw) // 2, (th - nh) // 2)
    bg.paste(main_img, offset)

    # E. 体积控制
    limit = 500 * 1024 if max_kb == "500KB" else (1024 * 1024 if max_kb == "1MB" else 0)
    q = 95
    out = io.BytesIO()
    while q > 15:
        out = io.BytesIO()
        bg.save(out, format="JPEG", quality=q, optimize=True)
        if limit == 0 or out.tell() < limit: break
        q -= 5
    return out.getvalue()

# --- 4. 界面展示 ---
st.title("💖 萌萌菜品美化屋")
files = st.file_uploader("✨ 把你的美食图片丢进来吧~", accept_multiple_files=True, type=['jpg','png','jpeg'])

if files:
    for f in files:
        if not any(item['name'] == f.name for item in st.session_state.processed_files):
            with st.spinner(f'正在变美: {f.name}'):
                res_data = process_perfect_logic(f.read())
                if res_data:
                    # 保留原名
                    save_name = f.name if f.name.lower().endswith('.jpg') else f.name.rsplit('.', 1)[0] + ".jpg"
                    st.session_state.processed_files.append({"name": save_name, "data": res_data})

if st.session_state.processed_files:
    st.divider()
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in st.session_state.processed_files:
            zf.writestr(item['name'], item['data'])
    
    st.download_button(
        label=f"🎀 一键打包下载全部 {len(st.session_state.processed_files)} 张纯净美照",
        data=zip_io.getvalue(),
        file_name=f"yummy_food_{int(time.time())}.zip",
        mime="application/zip",
        use_container_width=True
    )

    st.subheader("📸 成果预览 (物理除黑版)")
    cols = st.columns(4)
    for i, item in enumerate(st.session_state.processed_files):
        with cols[i % 4]:
            st.image(item['data'], caption=item['name'], use_container_width=True)
