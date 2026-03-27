import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 页面高级感配置 (极致紧凑版 CSS) ---
st.set_page_config(page_title="餐影工坊 Pro", layout="wide", page_icon="🍽️")

st.markdown("""
    <style>
    /* 缩小左侧边栏全局字体 */
    [data-testid="stSidebar"] * {
        font-size: 0.85rem !important;
    }
    /* 侧边栏宽度锁定 */
    [data-testid="stSidebar"] {
        min-width: 25% !important;
        max-width: 25% !important;
    }
    /* 极致压缩组件之间的垂直间距 */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.5rem !important;
        padding-top: 0.5rem !important;
    }
    /* 缩小标题尺寸 */
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        font-size: 1.1rem !important;
        margin-bottom: 0.2rem !important;
    }
    /* 缩小 Selectbox, Slider 等组件的高度 */
    div[data-baseweb="select"] > div {
        min-height: 30px !important;
    }
    .stSlider {
        margin-bottom: -10px !important;
    }
    /* 隐藏顶部冗余条 */
    header {visibility: hidden;}
    /* 按钮紧凑化 */
    .stButton>button {
        height: 2.2em !important;
        font-size: 0.85rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心处理逻辑 (Contain 模式) ---
def process_engine(file, config, is_preview=False):
    if file is None: return None
    img = Image.open(io.BytesIO(file.getvalue() if hasattr(file, 'getvalue') else file)).convert("RGBA")
    orig_w, orig_h = img.size
    tw, th = config['size']

    # 等比例缩放至完全装入 (不裁切)
    ratio = min(tw / orig_w, th / orig_h)
    new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
    img_fit = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 背景逻辑
    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
    else: # 提取原色
        sample = img.convert("RGB").getpixel((orig_w//2, orig_h//2))
        bg = Image.new("RGBA", (tw, th), sample + (255,))

    # 垂直居中合成
    offset_x, offset_y = (tw - new_w) // 2, (th - new_h) // 2
    bg.paste(img_fit, (offset_x, offset_y), img_fit)

    # 效果增强
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    
    if ext == "JPEG":
        q = 95
        limit = config['limit_kb'] * 1024 if config['limit_kb'] > 0 else 999999999
        while q > 15:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= limit or is_preview: break
            q -= 5
    else:
        bg.save(out_io, format="PNG")
        
    return out_io.getvalue(), ext

# --- 3. 侧边栏 UI ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    
    st.subheader("1. 尺寸与体积")
    res_opt = st.selectbox("分辨率预设", ["1920*1080", "1000*600", "800*800", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽度", 100, 4000, 1920)
        th = st.number_input("高度", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))
    vol_opt = st.selectbox("文件体积限制", ["不限制", "500KB", "1MB"])
    kb = 0 if vol_opt == "不限制" else (500 if vol_opt == "500KB" else 1024)

    st.subheader("2. 背景处理")
    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色":
        p_color = st.selectbox("颜色选择", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊":
        b_radius = st.slider("模糊程度", 0, 100, 40)

    st.subheader("3. 效果增强")
    flt = st.selectbox("选择滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("清晰度(去糊)", 1.0, 4.0, 1.8)

    st.markdown("---")
    if st.button("🗑️ 一键清空", use_container_width=True):
        st.rerun()

# --- 4. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 Pro")
st.caption("实时预览模式 • 等比例不切边 • 原文件名导出")

files = st.file_uploader("点击上传或拖拽文件夹至此", type=['jpg','jpeg','png'], accept_multiple_files=True)

if files:
    current_conf = {
        'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 
        'pure_color': p_color, 'blur_radius': b_radius,
        'filter': flt, 'bright': br, 'sharp': sh
    }

    # 实时预览
    st.subheader("👀 实时效果预览")
    preview_bytes, preview_ext = process_engine(files[0], current_conf, is_preview=True)
    
    col_img, col_act = st.columns([3, 1])
    with col_img:
        st.image(preview_bytes, use_container_width=True)
    with col_act:
        st.success("✅ 参数已实时应用")
        st.write(f"**预览文件**: {files[0].name}")
        st.write(f"**输出尺寸**: {tw}x{th}")
        
        if st.button("🚀 开始批量导出", use_container_width=True):
            # 以第一张图的名字 + 尺寸 命名
            zip_name = f"{files[0].name.split('.')[0]}_{tw}x{th}.zip"
            zip_buf = io.BytesIO()
            
            p_bar = st.progress(0, text="批量处理中...")
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for idx, f in enumerate(files):
                    data, ext = process_engine(f, current_conf)
                    final_name = f"{f.name.rsplit('.', 1)[0]}.{ext.lower()}"
                    zf.writestr(final_name, data)
                    p_bar.progress((idx + 1) / len(files))
            
            st.download_button(
                label="📥 点击下载 ZIP 压缩包",
                data=zip_buf.getvalue(),
                file_name=zip_name,
                mime="application/zip",
                use_container_width=True
            )
else:
    st.info("请在上方上传图片。系统将自动保持原图比例垂直居中，并在两侧填充背景。")

st.divider()
st.caption("Minimalist Design • High Fidelity Processing")
