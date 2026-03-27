import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 页面高级感配置 ---
st.set_page_config(page_title="餐影工坊 | 菜品图像高级处理", layout="wide", page_icon="🍳")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 8px; height: 3.5em; background-color: #ff4b4b; color: white; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #28a745; color: white; }
    div[data-testid="stExpander"] { border: none; box-shadow: 0px 4px 12px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 初始化状态 ---
if 'file_key' not in st.session_state:
    st.session_state.file_key = 0
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []

def reset_app():
    st.session_state.file_key += 1
    st.session_state.processed_files = []
    st.rerun()

# --- 核心引擎：不裁切 + 垂直居中 ---
def process_core(image_bytes, config):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size
    tw, th = config['size']

    # 1. 计算【不裁切】的等比例缩放因子 (Contain 模式)
    ratio = min(tw / orig_w, th / orig_h)
    new_w = int(orig_w * ratio)
    new_h = int(orig_h * ratio)
    img_fit = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 2. 背景生成
    if config['bg_mode'] == "深度高斯模糊":
        # 拉伸原图铺满画布作为底色
        bg = img.resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius']))
    else:
        # 提取原图中心像素色作为底色（比纯黑高级）
        sample_pixel = img.getpixel((orig_w//2, orig_h//2))
        bg = Image.new("RGB", (tw, th), sample_pixel)

    # 3. 垂直居中合成 (不裁切，只放置)
    offset_x = (tw - new_w) // 2
    offset_y = (th - new_h) // 2
    bg.paste(img_fit, (offset_x, offset_y))

    # 4. 效果增强
    # 提亮 & 去糊
    bg = ImageEnhance.Brightness(bg).enhance(config['bright'])
    bg = ImageEnhance.Sharpness(bg).enhance(config['sharp'])
    
    # 滤镜
    if config['filter'] == "暖色调 (诱人)":
        r, g, b = bg.split()
        r = ImageEnhance.Brightness(r).enhance(1.15)
        bg = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = bg.split()
        b = ImageEnhance.Brightness(b).enhance(1.1)
        bg = Image.merge("RGB", (r, g, b))

    # 5. 体积递归压缩
    q = 95
    out_io = io.BytesIO()
    limit = config['limit_kb'] * 1024 if config['limit_kb'] > 0 else 99999999
    
    while q > 15:
        out_io = io.BytesIO()
        bg.save(out_io, format="JPEG", quality=q, optimize=True)
        if out_io.tell() <= limit:
            break
        q -= 5
    
    return out_io.getvalue()

# --- UI 界面 ---
st.title("🍳 餐影工坊 · 菜品图自动美化")
st.caption("核心逻辑：等比例缩放展示全貌，垂直居中，绝不裁切原图内容。")

with st.sidebar:
    st.header("🎨 处理参数")
    
    # 尺寸
    res_opt = st.selectbox("分辨率目标", ["1920*1080", "1000*600", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽", 100, 4000, 1920)
        th = st.number_input("高", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))

    # 体积
    vol_opt = st.selectbox("文件体积限制", ["500KB", "1MB", "不限制"])
    kb = 500 if vol_opt == "500KB" else 1024 if vol_opt == "1MB" else 0

    # 背景
    bg_m = st.radio("背景填充方式", ["深度高斯模糊", "提取原色填充"])
    blur_val = st.slider("模糊半径", 0, 100, 40) if bg_m == "深度高斯模糊" else 0

    # 增强
    st.subheader("滤镜增强")
    flt = st.selectbox("色彩风格", ["原色", "暖色调 (诱人)", "清爽调"])
    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("清晰度(去糊)", 1.0, 4.0, 1.8)

    st.markdown("---")
    st.button("🗑️ 一键清空", on_click=reset_app)

# --- 操作区 ---
files = st.file_uploader("拖拽图片到此处 (支持多选)", type=['jpg','jpeg','png'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.file_key}")

if files:
    conf = {'size':(tw, th), 'limit_kb':kb, 'bg_mode':bg_m, 'blur_radius':blur_val, 
            'filter':flt, 'bright':br, 'sharp':sh}

    if st.button("🚀 开始批量处理"):
        results = []
        p_bar = st.progress(0)
        for i, f in enumerate(files):
            processed_bytes = process_core(f.read(), conf)
            results.append({"name": f.name, "data": processed_bytes})
            p_bar.progress((i + 1) / len(files))
        st.session_state.processed_files = results
        st.success("处理完成！")

    if st.session_state.processed_files:
        # 预览区
        st.subheader("🖼️ 处理效果预览")
        cols = st.columns(3)
        for i, item in enumerate(st.session_state.processed_files[:3]):
            cols[i % 3].image(item['data'], caption=f"预览: {item['name']}", use_container_width=True)

        # 下载区
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w') as zf:
            for item in st.session_state.processed_files:
                zf.writestr(item['name'], item['data'])
        
        st.download_button(
            label="📦 点击下载全部 (ZIP 压缩包)",
            data=zip_buf.getvalue(),
            file_name=f"dish_fixed_{int(time.time())}.zip",
            mime="application/zip"
        )
