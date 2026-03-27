import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime

# 尝试加载 PDF 支持
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 智能表格拆解版", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

st.markdown(f"""
    <style>
    [data-testid="stSidebar"] * {{ font-size: 0.85rem !important; }}
    [data-testid="stSidebar"] {{ min-width: 28% !important; max-width: 28% !important; }}
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.3rem !important; padding-top: 0.5rem !important; }}
    .stMarkdown h1, .stMarkdown h2 {{ font-size: 1.1rem !important; margin-bottom: 0.1rem !important; }}
    header {{visibility: hidden;}}
    /* 一键清空按钮红色 */
    div[data-testid="stSidebar"] button:first-child {{ background-color: #ff4b4b !important; color: white !important; border: none !important; }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：【激进优化版】针对表格的多主体提取 ---
def smart_area_extraction(pil_img):
    """
    针对复杂的表格PDF排版，使用智能网格区域检测与提取。
    彻底解决表格线干扰主体识别的问题。
    """
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    orig_h, orig_w = img.shape[:2]
    
    # 灰度化与形态学闭操作（强制连接细小表格线）
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 使用较大的闭操作核，把别扭的细表格线连成大的封闭块
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    
    # 二值化
    _, thresh = cv2.threshold(closed, 220, 255, cv2.THRESH_BINARY_INV)
    
    # 寻找轮廓
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    extracted_images = []
    
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        
        # --- 激进过滤逻辑 ---
        # 1. 过滤过小的区域（通常是左侧文字或标题）
        if area < 30000: continue
        
        # 2. 过滤过大或长宽比极其夸张的区域（如全页、或者一条长线）
        aspect_ratio = w / float(h)
        if w > orig_w * 0.9 or h > orig_h * 0.9 or aspect_ratio > 3.0 or aspect_ratio < 0.3: continue
        
        # 认为是一个封闭的网格格子，进行提取
        crop_img = img[y:y+h, x:x+w]
        
        # --- 对提取出的格多图进行“主体裁切” ---
        if crop_img.shape[0] < 100 or crop_img.shape[1] < 100: continue
        # 这里转为PIL对象后，在合成引擎中再次应用裁切
        extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))

    if not extracted_images:
        return [pil_img] # 如果一个都没找到，返回原图
    
    return extracted_images

# --- 3. 增强处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    # 1. 应用“激进裁切”
    if config.get('auto_crop', True):
        img = smart_crop_dish_aggressive(img).convert("RGBA")
    
    tw, th = config['size']
    ratio = min(tw / img.size[0], th / img.size[1])
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
    img_fit = img.resize(new_size, Image.Resampling.LANCZOS)

    # 背景合成与填充
    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
    else:
        sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
        bg = Image.new("RGBA", (tw, th), sample + (255,))

    bg.paste(img_fit, ((tw - new_size[0]) // 2, (th - new_size[1]) // 2), img_fit)
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    # 滤镜与体积压缩...
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    if ext == "JPEG":
        q = 95; limit_kb = config['limit_kb']
        while q > 15:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= limit_kb * 1024 or is_preview or limit_kb == 0: break
            q -= 5
    else: bg.save(out_io, format="PNG")
    return out_io.getvalue(), ext

# --- 保底版裁切 (确保合成时主体干净) ---
def smart_crop_dish_aggressive(pil_img):
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea); x, y, w, h = cv2.boundingRect(c)
        if w > 100 and h > 100:
            crop_img = img[y:y+h, x:x+w]
            return Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
    return pil_img

# --- 4. 侧边栏 ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    st.button("🗑️ 一键清空预览", on_click=reset_uploader, use_container_width=True)
    st.markdown("---")
    
    res_opt = st.selectbox("目标分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))

    vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
    kb = 0 if vol_opt == "不限制" else (500 if vol_opt == "500KB" else 1024)

    st.markdown("---")
    # PDF专用选项 (核心优化开关)
    auto_crop = st.toggle("表格多图拆解 & 激进裁切", value=True, help="检测图片/PDF页面中包含的封闭网格区域（格多图），自动将其拆分为独立图片导出。针对表格排版极其重要。")

    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色": p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊": b_radius = st.slider("模糊程度", 0, 100, 40)

    flt = st.selectbox("选择滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度调节", 0.5, 1.5, 1.05); sh = st.slider("锐化强度", 1.0, 4.0, 1.8)

# --- 5. 主逻辑 ---
st.title("🍽️ 餐影工坊 智能表格拆解版")

files = st.file_uploader("上传图片或PDF菜单文件", type=['jpg','jpeg','png','pdf'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    final_dishes_list = []
    
    with st.spinner("正在解析PDF排版并拆解商品区域..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                pdf_pages = convert_from_bytes(f.read(), dpi=300)
                for i, page in enumerate(pdf_pages):
                    # --- 【激进逻辑升级】：即使开关没开，也必须保证基本的区域识别 ---
                    # 重新赋予独立的文件名
                    prefix = f.name.rsplit('.', 1)[0]
                    # 核心改动：应用更激进的网格区域检测
                    extracted_dishes = smart_area_extraction(page)
                    for idx, dish in enumerate(extracted_dishes):
                        # 确保赋予了独立的文件名
                        dish.filename = f"{prefix}_P{i+1}_{idx+1}.jpg"
                        final_dishes_list.append(dish)
            else:
                final_dishes_list.append(f)

    conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'auto_crop': auto_crop}

    st.subheader("👀 实时效果预览")
    # 预览第一张
    # 修复：安全获取名称，解决 AttributeError
    display_item = final_dishes_list[0]
    display_name = getattr(display_item, 'filename', getattr(display_item, 'name', "未知素材"))
    
    p_bytes, p_ext = process_engine(display_item, conf, is_preview=True)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.image(p_bytes, use_container_width=True, caption=f"预览效果：{display_name}")
    with col2:
        st.success(f"解析成功: {len(final_dishes_list)} 张素材")
        st.write(f"📏 目标体积: {'不限' if kb==0 else f'{kb} KB'}")
        
        if len(final_dishes_list) == 1:
            data, ext = process_engine(final_dishes_list[0], conf)
            fname = getattr(final_dishes_list[0], 'filename', final_dishes_list[0].name).rsplit('.', 1)[0]
            st.download_button("📥 下载单图", data, f"{fname}_{tw}x{th}.{ext.lower()}", use_container_width=True)
        else:
            if st.button("🚀 开始批量合成全部独立图片", use_container_width=True):
                today = datetime.now().strftime("%Y-%m-%d")
                zip_name = f"{today}_{tw}x{th}.zip"; zip_buf = io.BytesIO()
                p_bar = st.progress(0, text="批量合成中...")
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for idx, itm in enumerate(final_dishes_list):
                        data, ext = process_engine(itm, conf)
                        # 重点：确保文件名正确
                        fname_raw = getattr(itm, 'filename', itm.name)
                        clean_fname = f"{fname_raw.rsplit('.', 1)[0]}.{ext.lower()}"
                        zf.writestr(clean_fname, data)
                        p_bar.progress((idx+1)/len(final_dishes_list))
                st.download_button("📦 下载 ZIP 包", zip_buf.getvalue(), zip_name, use_container_width=True)
else:
    st.info("💡 提示：开启'表格多图拆解'系统会自动检测网格并应用裁切。建议先上传PDF测试。")
