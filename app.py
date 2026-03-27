import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 页面高级感配置 (极简紧凑版) ---
st.set_page_config(page_title="餐影工坊 Pro", layout="wide", page_icon="🍽️")

st.markdown("""
    <style>
    /* 侧边栏宽度与间距优化 */
    [data-testid="stSidebar"] {
        min-width: 22% !important;
        max-width: 22% !important;
        background-color: #f8f9fa;
    }
    /* 极致压缩组件间距 */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.3rem !important;
        padding-top: 1rem !important;
    }
    /* 缩小标题字体 */
    h1 { font-size: 1.5rem !important; margin-bottom: 0.5rem !important; }
    h2 { font-size: 1.1rem !important; margin-top: 0.5rem !important; }
    /* 隐藏顶部冗余 */
    header {visibility: hidden;}
    /* 优化按钮 */
    .stButton>button {
        border-radius: 4px;
        background-color: #1a1a1a;
        color: white;
        height: 2.2em;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心处理逻辑 (支持透明度) ---
def process_engine(file, config, is_preview=False):
    if file is None: return None
    img = Image.open(io.BytesIO(file.getvalue() if hasattr(file, 'getvalue') else file)).convert("RGBA")
    orig_w, orig_h = img.size
    tw, th = config['size']

    ratio = min(tw / orig_w, th / orig_h)
    new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
    img_fit = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
    else:
        sample = img.convert("RGB").getpixel((orig_w//2, orig_h//2))
        bg = Image.new("RGBA", (tw, th), sample + (255,))

    offset_x, offset_y = (tw - new_w) // 2, (th - new_h) // 2
    bg.paste(img_fit, (offset_x, offset_y), img_fit)

    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    if config['filter'] == "暖色调":
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

# --- 3. 侧边栏 UI (压缩高度版) ---
with st.sidebar:
    st.title("⚙️ 配置")
    
    # 将参数整合进紧凑的 Expander，减少纵向占用
    with st.expander("📏 尺寸与体积", expanded=True):
        res_opt = st.selectbox("分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
        tw, th = (1920, 1080)
        if res_opt == "自定义":
            col_w, col_h = st.columns(2)
            tw = col_w.number_input("W", 100, 4000, 1920)
            th = col_h.number_input("H", 100, 4000, 1080)
        else:
            tw, th = map(int, res_opt.split('*'))
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
        kb = 0 if vol_opt == "不限制" else (500 if vol_opt == "500KB" else 1024)

    with st.expander("🖼️ 背景与色彩", expanded=True):
        bg_m = st.radio("模式", ["模糊", "定色", "原色"], horizontal=True)
        p_color, b_radius = "白色", 40
        if bg_m == "定色":
            p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"])
        elif bg_m == "模糊":
            b_radius = st.slider("强度", 0, 100, 40)
        
        flt = st.selectbox("滤镜", ["原色", "暖色调", "清爽调"])

    with st.expander("✨ 微调增强", expanded=False): # 默认折叠最不常用的
        br = st.slider("亮度", 0.5, 1.5, 1.05, step=0.05)
        sh = st.slider("锐度", 1.0, 4.0, 1.8, step=0.1)

    st.button("🗑️ 重置", on_click=lambda: st.rerun())

# --- 4. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 Pro")

files = st.file_uploader("上传图片/文件夹", type=['jpg','jpeg','png'], accept_multiple_files=True)

if files:
    current_conf = {
        'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m.replace("模糊","深度高斯模糊").replace("定色","特定颜色").replace("原色","提取原色"), 
        'pure_color': p_color, 'blur_radius': b_radius,
        'filter': flt, 'bright': br, 'sharp': sh
    }

    # 实时预览
    st.subheader("👀 实时效果")
    preview_bytes, preview_ext = process_engine(files[0], current_conf, is_preview=True)
    
    col_pre, col_info = st.columns([3, 1])
    with col_pre:
        st.image(preview_bytes, use_container_width=True)
    with col_info:
        st.caption(f"**文件名**: {files[0].name}")
        st.caption(f"**格式**: {preview_ext}")
        
        if st.button("🚀 导出全部", use_container_width=True):
            # 获取第一个文件的名称作为前缀
            prefix = files[0].name.split('.')[0]
            zip_name = f"{prefix}_{tw}x{th}.zip"
            zip_buf = io.BytesIO()
            
            p_bar = st.progress(0)
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for idx, f in enumerate(files):
                    data, ext = process_engine(f, current_conf)
                    zf.writestr(f"{f.name.rsplit('.', 1)[0]}.{ext.lower()}", data)
                    p_bar.progress((idx + 1) / len(files))
            
            st.download_button("📥 点击下载", zip_buf.getvalue(), zip_name, "application/zip", use_container_width=True)
else:
    st.info("💡 提示：调整左侧参数，右侧预览会实时更新。")

st.divider()
st.caption("Minimalist Design • High Efficiency")
