import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io, zipfile, numpy as np, cv2

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 1.1", layout="wide", page_icon="🍽️")

# 隐藏冗余 UI
st.markdown("<style>header {visibility: hidden;} .stButton>button {width:100%;}</style>", unsafe_allow_html=True)

# --- 2. 自动裁剪算法 ---
def extract_subjects(pil_img):
    cv_img = cv2.cvtColor(np.array(pil_img.convert('RGB')), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
    cnts, _ = cv2.findContours(cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15,15))), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    res = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        x, y, w, h = cv2.boundingRect(c)
        if cv2.contourArea(c) < 5000: continue
        res.append(Image.fromarray(cv2.cvtColor(cv_img[y:y+h, x:x+w], cv2.COLOR_BGR2RGB)))
    return res if res else [pil_img]

# --- 3. 核心处理引擎 (包含体积控制) ---
def engine(item, cfg, is_preview=False):
    # 转换为 PIL 对象
    if hasattr(item, 'getvalue'):
        img = Image.open(io.BytesIO(item.getvalue())).convert("RGBA")
    else:
        img = item.convert("RGBA")
        
    tw, th = cfg['size']
    rw, rh = (tw//2, th//2) if is_preview else (tw, th)
    img.thumbnail((rw, rh), Image.Resampling.LANCZOS)
    
    # 背景生成
    if cfg['bg'] == "深度高斯模糊":
        canvas = img.convert("RGB").resize((rw, rh)).filter(ImageFilter.GaussianBlur(30)).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (rw, rh), cfg['color'])

    # 居中合成
    canvas.paste(img, ((rw - img.size[0])//2, (rh - img.size[1])//2), img)
    final = ImageEnhance.Sharpness(ImageEnhance.Brightness(canvas.convert("RGB")).enhance(1.05)).enhance(1.8)
    
    # 体积压缩逻辑 (针对 JPEG)
    out_io = io.BytesIO()
    ext = "PNG" if cfg['color'] == (0,0,0,0) else "JPEG"
    if ext == "JPEG":
        q = 95
        while q > 10:
            out_io = io.BytesIO()
            final.save(out_io, format="JPEG", quality=q, optimize=True)
            if is_preview or cfg['limit'] == 0 or out_io.tell() <= cfg['limit'] * 1024:
                break
            q -= 5
    else:
        canvas.save(out_io, format="PNG")
    return out_io.getvalue(), ext

# --- 4. 侧边栏控制台 ---
with st.sidebar:
    st.header("⚙️ 参数设置")
    res_sel = st.selectbox("目标分辨率", ["1920*1080", "1000*600", "800*800"])
    tw, th = map(int, res_sel.split('*'))
    
    vol_sel = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
    limit_kb = {"不限制":0, "500KB":500, "1MB":1024}.get(vol_sel)
    
    do_crop = st.toggle("多主体自动拆解", value=True)
    bg_mode = st.selectbox("背景样式", ["深度高斯模糊", "白色背景", "透明背景"])
    
    c_val = (255,255,255,255)
    if bg_mode == "透明背景": c_val = (0,0,0,0)
    elif bg_mode == "白色背景": c_val = (255,255,255,255)

# --- 5. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 1.1")
files = st.file_uploader("上传图片或 PDF", type=['jpg','png','pdf'], accept_multiple_files=True)

if files:
    final_list = []
    with st.spinner("正在解析素材..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pages = convert_from_bytes(f.read(), dpi=150)
                for i, p in enumerate(pages):
                    if do_crop:
                        for idx, dish in enumerate(extract_subjects(p)):
                            final_list.append(dish)
                    else:
                        final_list.append(p)
            else:
                raw = Image.open(f)
                if do_crop:
                    for dish in extract_subjects(raw):
                        final_list.append(dish)
                else:
                    final_list.append(raw)

    cfg = {'size':(tw,th), 'limit':limit_kb, 'bg':bg_mode, 'color':c_val}
    
    st.subheader(f"预览区 ({len(final_list)} 张)")
    cols = st.columns(3)
    for i, itm in enumerate(final_list):
        with cols[i % 3]:
            p_data, _ = engine(itm, cfg, is_preview=True)
            st.image(p_data, use_container_width=True)

    if st.sidebar.button("🚀 导出全部 (ZIP)"):
        z_buf = io.BytesIO()
        with zipfile.ZipFile(z_buf, 'w') as zf:
            for i, itm in enumerate(final_list):
                d, e = engine(itm, cfg)
                zf.writestr(f"processed_{i+1}.{e.lower()}", d)
        st.sidebar.download_button("📥 点击下载 ZIP", z_buf.getvalue(), "batch_output.zip")
else:
    st.info("💡 请在上方上传图片或 PDF 开始。")
