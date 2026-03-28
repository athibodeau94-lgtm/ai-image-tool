import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except:
    PDF_SUPPORT = False

# 采用缓存机制加载 OCR，防止重复下载模型
@st.cache_resource
def load_ocr_reader():
    try:
        import easyocr
        # 初始化 Reader (中英文)
        return easyocr.Reader(['ch_sim', 'en'], gpu=False)
    except Exception as e:
        print(f"OCR 加载失败: {e}")
        return None

# 静默加载，不影响主程序运行
READER = load_ocr_reader()

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.1.2", layout="wide", page_icon="🍽️")

# 初始化上传 Key
if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# 极致紧凑 UI 样式
st.markdown("""
    <style>
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem !important; padding-top: 0rem !important; }
    [data-testid="stSidebar"] * { font-size: 0.85rem !important; }
    header {visibility: hidden;}
    div[data-testid="stSidebar"] button:first-child { background-color: #ff4b4b !important; color: white !important; }
    .stImage { border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心功能：抹除文字 ---
def erase_text(pil_img):
    if READER is None:
        return pil_img
    
    # 转换图像
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    
    # 识别文字
    try:
        results = READER.readtext(cv_img)
    except:
        return pil_img
        
    if not results:
        return pil_img

    # 创建掩膜
    mask = np.zeros(cv_img.shape[:2], dtype="uint8")
    for (bbox, text, prob) in results:
        pts = np.array(bbox, dtype="int32")
        cv2.fillPoly(mask, [pts], 255)
    
    # 膨胀处理，确保文字边缘也抹干净
    mask = cv2.dilate(mask, np.ones((5,5), np.uint8), iterations=1)
    
    # 执行修补
    clean_cv = cv2.inpaint(cv_img, mask, 3, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(clean_cv, cv2.COLOR_BGR2RGB))

# --- 3. 核心功能：主体拆解 ---
def extract_subjects(pil_img):
    img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
    
    contours, _ = cv2.findContours(cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15,15))), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    extracted = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(c) < 5000: continue
        x, y, w, h = cv2.boundingRect(c)
        if w > img.shape[1] * 0.9 or h > img.shape[0] * 0.9: continue
        crop = img[y:y+h, x:x+w]
        extracted.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
    
    return extracted if extracted else [pil_img]

# --- 4. 处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    # 1. 统一加载
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    # 2. 预览模式不抹除文字以加速，导出模式按需抹除
    if config.get('do_erase') and not is_preview:
        img = erase_text(img).convert("RGBA")

    # 3. 尺寸处理
    tw, th = config['size']
    render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
    img.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
    
    # 4. 背景填充
    if config['bg_mode'] == "高斯模糊":
        bg = img.convert("RGB").resize((render_w, render_h)).filter(ImageFilter.GaussianBlur(40)).convert("RGBA")
    elif config['bg_mode'] == "纯色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (render_w, render_h), color_map.get(config['color'], (255,255,255,255)))
    else:
        # 提取原色
        sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        bg = Image.new("RGBA", (render_w, render_h), sample + (255,))

    # 5. 合成与增强
    bg.paste(img, ((render_w - img.size[0]) // 2, (render_h - img.size[1]) // 2), img)
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    # 6. 导出
    out_io = io.BytesIO()
    ext = "PNG" if config.get('color') == "透明" else "JPEG"
    res.save(out_io, format=ext, quality=85)
    return out_io.getvalue(), ext

# --- 5. 侧边栏 UI ---
with st.sidebar:
    st.button("🗑️ 清空所有", on_click=reset_uploader, use_container_width=True)
    st.markdown("---")
    res_opt = st.selectbox("导出分辨率", ["1920*1080", "1000*600", "800*800"])
    tw, th = map(int, res_opt.split('*'))
    
    do_erase = st.toggle("智能抹除文字", value=True)
    auto_crop = st.toggle("自动拆解主体", value=True)
    
    st.markdown("---")
    bg_mode = st.radio("背景模式", ["纯色", "高斯模糊", "提取原色"])
    color = st.selectbox("背景颜色", ["白色", "黑色", "透明"]) if bg_mode == "纯色" else "白色"
    
    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("锐化调节", 1.0, 4.0, 1.8)

# --- 6. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 1.1.2")
uploaded_files = st.file_uploader("支持多图片或 PDF", type=['jpg','png','jpeg','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if uploaded_files:
    # 统一转换成待处理列表
    process_list = []
    with st.spinner("正在解析素材..."):
        for f in uploaded_files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                # PDF 转换
                pages = convert_from_bytes(f.read(), dpi=150)
                for i, p in enumerate(pages):
                    if auto_crop:
                        # 如果开启了拆解，对 PDF 页面进行拆解
                        for idx, dish in enumerate(extract_subjects(p)):
                            dish.filename = f"{f.name.rsplit('.', 1)[0]}_P{i+1}_{idx+1}.jpg"
                            process_list.append(dish)
                    else:
                        p.filename = f"{f.name.rsplit('.', 1)[0]}_P{i+1}.jpg"
                        process_list.append(p)
            else:
                # 普通图片
                if auto_crop:
                    # 读取图片并拆解
                    img_raw = Image.open(f)
                    for idx, dish in enumerate(extract_subjects(img_raw)):
                        dish.filename = f"{f.name.rsplit('.', 1)[0]}_{idx+1}.jpg"
                        process_list.append(dish)
                else:
                    process_list.append(f)

    # 全局配置
    config = {'size': (tw, th), 'bg_mode': bg_mode, 'color': color, 'bright': br, 'sharp': sh, 'do_erase': do_erase}

    # 实时预览
    st.subheader(f"👀 实时预览 ({len(process_list)} 张)")
    with st.container(height=550, border=True):
        cols = st.columns(3)
        for i, item in enumerate(process_list):
            with cols[i % 3]:
                p_bytes, _ = process_engine(item, config, is_preview=True)
                name = getattr(item, 'filename', getattr(item, 'name', f"Image_{i}"))
                st.image(p_bytes, use_container_width=True, caption=name)

    # 导出区域
    with st.sidebar:
        st.markdown("---")
        st.success(f"准备就绪: {len(process_list)} 张")
        if len(process_list) == 1:
            # 单张下载
            data, ext = process_engine(process_list[0], config)
            st.download_button("📥 下载图片", data, f"output.{ext.lower()}", use_container_width=True)
        else:
            # 批量下载
            if st.button("🚀 导出 ZIP 压缩包", use_container_width=True):
                zip_io = io.BytesIO()
                with zipfile.ZipFile(zip_io, 'w') as zf:
                    for i, itm in enumerate(process_list):
                        data, ext = process_engine(itm, config)
                        fname = getattr(itm, 'filename', getattr(itm, 'name', f"{i}.jpg"))
                        zf.writestr(f"{fname.rsplit('.', 1)[0]}.{ext.lower()}", data)
                st.download_button("📦 点击下载 ZIP", zip_io.getvalue(), "batch_images.zip", use_container_width=True)
else:
    st.info("💡 请在上方上传图片或 PDF 开始操作。")
