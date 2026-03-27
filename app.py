import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 1. 页面配置 (极致简约 & 加宽侧边栏) ---
st.set_page_config(page_title="餐影工坊 Pro", layout="wide", page_icon="🍽️")

st.markdown("""
    <style>
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    [data-testid="stSidebar"] { min-width: 28% !important; max-width: 28% !important; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.3rem !important; padding-top: 0.5rem !important; }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 { font-size: 1.1rem !important; margin-bottom: 0.1rem !important; }
    header {visibility: hidden;}
    .stButton>button { height: 2.2em !important; font-size: 0.85rem !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：【激进优化版】定向去除脏边 ---
def smart_crop_dish_aggressive(pil_img):
    """
    针对浅色/白色不干净边缘进行高精度、激进的识别与裁切。
    彻底解决原图剪裁不干净留下的死角白边问题。
    """
    # 转换 PIL 为 OpenCV 格式
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    
    # 灰度化 + 高斯模糊 (噪点控制)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0) # 稍微增加模糊度以更好识别边缘
    
    # --- 【优化核心 1：激进二值化】 ---
    # 我们认为，凡是接近白色的 (亮度>220)，都是需要被裁切掉的背景。
    # 阈值设置更激进 (原 240 -> 现 220)，让算法更“狠”地识别边缘。
    _, thresh = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
    
    # 寻找轮廓
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # 找到面积最大的轮廓 (通常是黑碗主体)
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        
        # --- 【优化核心 2：去除缓冲空间】 ---
        # 原 5 像素 Padding -> 现 0 Padding。
        # 既然你觉得别扭，我们就直接把边界对齐到碗边，不留任何余地。
        padding = 0 
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(img.shape[1] - x, w + padding * 2)
        h = min(img.shape[0] - y, h + padding * 2)
        
        # --- 【优化核心 3：增加最小面积限制】 ---
        # 防止误识别过小的噪点为碗。
        if w > 100 and h > 100:
            crop_img = img[y:y+h, x:x+w]
            # 转回 PIL
            return Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
    
    return pil_img # 识别失败则返回原图

# --- 3. 核心处理引擎 ---
def process_engine(file, config, is_preview=False):
    if file is None: return None
    # 读取原始图片 (保持RGBA以处理透明)
    raw_img = Image.open(io.BytesIO(file.getvalue() if hasattr(file, 'getvalue') else file)).convert("RGBA")
    
    # --- 【智能修边步骤】 ---
    # 根据开关应用激进裁切
    if config.get('auto_crop', True):
        img = smart_crop_dish_aggressive(raw_img).convert("RGBA")
    else:
        img = raw_img
    
    orig_w, orig_h = img.size
    tw, th = config['size']

    # 计算等比例不切边缩放 (Contain模式)
    ratio = min(tw / orig_w, th / orig_h)
    new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
    img_fit = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 背景填充
    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
    else:
        sample = img.convert("RGB").getpixel((orig_w//2, orig_h//2))
        bg = Image.new("RGBA", (tw, th), sample + (255,))

    # 垂直居中合成
    bg.paste(img_fit, ((tw - new_w) // 2, (th - new_h) // 2), img_fit)

    # 增强处理
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    # 输出体积控制 ( JPEG 专用 )
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

# --- 4. UI 布局 ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    
    # 尺寸与体积
    res_opt = st.selectbox("目标分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽度", 100, 4000, 1920)
        th = st.number_input("高度", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))
    vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
    kb = 0 if vol_opt == "不限制" else (500 if vol_opt == "500KB" else 1024)

    st.markdown("---")
    # 智能修边
    auto_crop = st.toggle("主动裁切脏白边 (激进版)", value=True, help="采用激进的边缘识别算法，彻底切掉白色脏边，确保画面只有干净的主体碗。")

    st.markdown("---")
    # 背景处理
    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色":
        p_color = st.selectbox("选择颜色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊":
        b_radius = st.slider("模糊程度", 0, 100, 40)

    st.markdown("---")
    # 效果增强
    flt = st.selectbox("滤镜风格", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("清晰度(去糊)", 1.0, 4.0, 1.8)

    st.markdown("---")
    if st.button("🗑️ 一键重置", on_click=lambda: st.rerun(), use_container_width=True) : pass

# --- 5. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 Pro")
st.caption("实时预览模式 • 等比例Contain模式 • 定向脏边裁切")

files = st.file_uploader("点击上传或拖拽文件夹", type=['jpg','jpeg','png'], accept_multiple_files=True)

if files:
    current_conf = {
        'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 
        'pure_color': p_color, 'blur_radius': b_radius,
        'filter': flt, 'bright': br, 'sharp': sh,
        'auto_crop': auto_crop
    }

    # 实时预览 (以第一张图为准)
    st.subheader("👀 实时效果预览")
    # preview模式下忽略体积限制
    preview_bytes, preview_ext = process_engine(files[0], current_conf, is_preview=True)
    
    col_img, col_act = st.columns([3, 1])
    with col_img:
        st.image(preview_bytes, use_container_width=True)
    
    with col_act:
        st.success("✨ 参数同步成功")
        file_count = len(files)
        st.write(f"**待处理数量**: {file_count}")

        if file_count == 1:
            # 单张下载
            final_data, final_ext = process_engine(files[0], current_conf)
            orig_name = files[0].name.rsplit('.', 1)[0]
            download_name = f"{orig_name}_{tw}x{th}.{final_ext.lower()}"
            st.download_button(
                label="📥 点击下载图片",
                data=final_data,
                file_name=download_name,
                mime=f"image/{final_ext.lower()}",
                use_container_width=True
            )
        else:
            # 多张ZIP下载
            if st.button("🚀 开始批量合成", use_container_width=True):
                today = datetime.now().strftime("%Y-%m-%d")
                zip_name = f"{today}_{tw}x{th}.zip"
                zip_buf = io.BytesIO()
                
                p_bar = st.progress(0, text="批量定向裁切中...")
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for idx, f in enumerate(files):
                        data, ext = process_engine(f, current_conf)
                        final_fname = f"{f.name.rsplit('.', 1)[0]}.{ext.lower()}"
                        zf.writestr(final_fname, data)
                        p_bar.progress((idx + 1) / len(files))
                
                st.download_button(
                    label="📦 下载 ZIP",
                    data=zip_buf.getvalue(),
                    file_name=zip_name,
                    mime="application/zip",
                    use_container_width=True
                )
else:
    st.info("💡 请在上方上传图片。系统默认开启'激进版'主动裁切脏白边，确保预览主体干净、垂直居中。")

st.divider()
st.caption(f"餐影工坊 Pro | 定向脏边裁切已就绪 | Minimalist Design")
