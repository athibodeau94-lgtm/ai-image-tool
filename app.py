import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 Pro", layout="wide", page_icon="🍽️")

st.markdown("""
    <style>
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    [data-testid="stSidebar"] { min-width: 25% !important; max-width: 25% !important; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.4rem !important; padding-top: 0.5rem !important; }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 { font-size: 1.1rem !important; margin-bottom: 0.2rem !important; }
    header {visibility: hidden;}
    .stButton>button { height: 2.2em !important; font-size: 0.85rem !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：智能去除脏边 ---
def smart_crop_dish(pil_img):
    """使用 OpenCV 自动识别主体并裁切掉多余白边/背景"""
    # 转换 PIL 为 OpenCV 格式
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    
    # 灰度化 + 高斯模糊（减少噪点）
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # 使用 Canny 边缘检测或阈值处理
    # 针对白色/浅色背景效果极佳
    _, thresh = cv2.threshold(blurred, 240, 255, cv2.THRESH_BINARY_INV)
    
    # 寻找轮廓
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # 找到面积最大的轮廓（通常是菜品主体）
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        
        # 稍微增加一点缓冲空间(5像素)，避免切得太死
        padding = 5
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(img.shape[1] - x, w + padding * 2)
        h = min(img.shape[0] - y, h + padding * 2)
        
        # 只有当识别出的主体面积合理时才裁切
        if w > 50 and h > 50:
            crop_img = img[y:y+h, x:x+w]
            # 转回 PIL
            return Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
    
    return pil_img # 如果识别失败，返回原图

# --- 3. 核心处理引擎 ---
def process_engine(file, config, is_preview=False):
    if file is None: return None
    # 初始读取
    raw_img = Image.open(io.BytesIO(file.getvalue() if hasattr(file, 'getvalue') else file)).convert("RGBA")
    
    # --- 【新增步骤】智能裁切脏边 ---
    if config.get('auto_crop', True):
        img = smart_crop_dish(raw_img).convert("RGBA")
    else:
        img = raw_img
    
    orig_w, orig_h = img.size
    tw, th = config['size']

    # 等比例缩放
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

    bg.paste(img_fit, ((tw - new_w) // 2, (th - new_h) // 2), img_fit)

    # 增强处理
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

# --- 4. UI 布局 ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    
    st.subheader("1. 尺寸与体积")
    res_opt = st.selectbox("分辨率预设", ["1920*1080", "1000*600", "800*800", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽度", 100, 4000, 1920)
        th = st.number_input("高度", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))
    vol_opt = st.selectbox("体积限制", ["不限制", "500KB", "1MB"])
    kb = 0 if vol_opt == "不限制" else (500 if vol_opt == "500KB" else 1024)

    st.subheader("2. 自动修边 (新)")
    auto_crop = st.toggle("自动裁切脏白边/背景", value=True, help="检测图片中的菜品主体并自动剔除周围杂色边缘")

    st.subheader("3. 背景处理")
    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色":
        p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊":
        b_radius = st.slider("模糊程度", 0, 100, 40)

    st.subheader("4. 效果增强")
    flt = st.selectbox("滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("清晰度", 1.0, 4.0, 1.8)

    st.markdown("---")
    st.button("🗑️ 一键重置", on_click=lambda: st.rerun(), use_container_width=True)

# --- 5. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 Pro")

files = st.file_uploader("上传图片或拖拽文件夹", type=['jpg','jpeg','png'], accept_multiple_files=True)

if files:
    current_conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 
                    'pure_color': p_color, 'blur_radius': b_radius,
                    'filter': flt, 'bright': br, 'sharp': sh,
                    'auto_crop': auto_crop}

    st.subheader("👀 实时预览")
    preview_bytes, preview_ext = process_engine(files[0], current_conf, is_preview=True)
    
    col_img, col_act = st.columns([3, 1])
    with col_img:
        st.image(preview_bytes, use_container_width=True)
    
    with col_act:
        st.success("✨ 参数已同步")
        file_count = len(files)
        st.write(f"**待处理数量**: {file_count}")

        if file_count == 1:
            final_data, final_ext = process_engine(files[0], current_conf)
            orig_name = files[0].name.rsplit('.', 1)[0]
            st.download_button("📥 下载图片", final_data, f"{orig_name}_{tw}x{th}.{final_ext.lower()}", f"image/{final_ext.lower()}", use_container_width=True)
        else:
            if st.button("🚀 开始批量处理", use_container_width=True):
                today = datetime.now().strftime("%Y-%m-%d")
                zip_name = f"{today}_{tw}x{th}.zip"
                zip_buf = io.BytesIO()
                p_bar = st.progress(0, text="批量修边中...")
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for idx, f in enumerate(files):
                        data, ext = process_engine(f, current_conf)
                        f_name = f"{f.name.rsplit('.', 1)[0]}.{ext.lower()}"
                        zf.writestr(f_name, data)
                        p_bar.progress((idx + 1) / len(files))
                st.download_button("📦 下载 ZIP", zip_buf.getvalue(), zip_name, "application/zip", use_container_width=True)
else:
    st.info("💡 提示：开启'自动裁切脏白边'可智能识别菜品并重新构图。")

st.divider()
st.caption(f"餐影工坊 Pro | {datetime.now().year} | OpenCV 智能裁切已就绪")
