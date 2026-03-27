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
st.set_page_config(page_title="餐影工坊 PDF智能拆解版", layout="wide", page_icon="🍽️")

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
    div[data-testid="stSidebar"] button:first-child {{ background-color: #ff4b4b !important; color: white !important; border: none !important; }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 【核心优化】：智能多主体提取 (针对PDF格多图) ---
def smart_extract_multiple_subjects(pil_img):
    """
    针对PDF排版（表格、格多图），自动识别并提取出所有独立的商品主体。
    返回一个PIL图片对象的列表。
    """
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 使用中值模糊减少表格线的干扰，保持主体边缘
    blurred = cv2.medianBlur(gray, 5)
    
    # 自适应阈值二值化（处理表格和背景）
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                     cv2.THRESH_BINARY_INV, 11, 2)
    
    # 闭操作：连接断开的边缘，形成闭合区域
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15,15))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    # 寻找所有外部轮廓
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    extracted_images = []
    
    # 根据面积从大到小排序（可选，保持一点顺序）
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    # 循环检查每个轮廓
    for c in contours:
        area = cv2.contourArea(c)
        x, y, w, h = cv2.boundingRect(c)
        aspect_ratio = w / float(h)
        
        # --- 核心过滤逻辑 ---
        # 1. 过滤掉过小的轮廓（可能是表格线噪点）
        if area < 5000: continue
        
        # 2. 过滤掉过大且接近全页的轮廓
        if w > img.shape[1] * 0.9 or h > img.shape[0] * 0.9: continue
        
        # 3. 过滤掉表格线（通常非常宽或非常高）
        if aspect_ratio > 3.0 or aspect_ratio < 0.3: continue
        
        # 如果通过过滤，认为是一个商品主体，进行裁切
        crop_img = img[y:y+h, x:x+w]
        
        # 如果裁切区域太小，忽略
        if crop_img.shape[0] < 50 or crop_img.shape[1] < 50: continue

        extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))

    if not extracted_images:
        return [pil_img] # 如果一个都没找到，返回原图
    
    return extracted_images # 返回识别到的所有主体

# --- 3. 增强处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    # 处理不同输入源
    if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    # 这一步已经完成了多主体识别
    if config.get('auto_crop', True) and not isinstance(img_input, Image.Image):
        # 这一步逻辑主要针对直接上传图片的情况（保持原样）
        img = smart_extract_multiple_subjects(img)[0].convert("RGBA") # 取第一个，保持单一输出逻辑

    # 尺寸调整
    tw, th = config['size']
    ratio = min(tw / img.size[0], th / img.size[1])
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
    img_fit = img.resize(new_size, Image.Resampling.LANCZOS)

    # 背景合成逻辑
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
    
    # 滤镜处理
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    # 体积压缩逻辑
    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    if ext == "JPEG":
        q = 95
        limit_kb = config['limit_kb']
        # 预览时不压缩
        while q > 15:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= limit_kb * 1024 or is_preview or limit_kb == 0: break
            q -= 5
    else:
        bg.save(out_io, format="PNG")
    return out_io.getvalue(), ext

# --- 4. 侧边栏 ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    st.button("🗑️ 一键清空处理列表", on_click=reset_uploader, use_container_width=True)
    st.markdown("---")
    
    res_opt = st.selectbox("目标分辨率预设", ["1920*1080", "1000*600", "800*800", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))

    # 体积控制
    vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
    if vol_opt == "自定义":
        kb = st.number_input("限制 (KB)", 10, 5120, 300)
    elif vol_opt == "不限制":
        kb = 0
    else:
        kb = 500 if vol_opt == "500KB" else 1024

    st.markdown("---")
    # PDF专用选项 (核心优化开关)
    auto_crop = st.toggle("激进裁切 & 多主体拆解", value=True, help="检测图片/PDF页面中的所有菜品主体并拆分为独立图片导出。针对菜单排版极其重要。")

    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色":
        p_color = st.selectbox("颜色选择", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊":
        b_radius = st.slider("模糊程度", 0, 100, 40)

    st.markdown("---")
    flt = st.selectbox("选择滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("锐化强度", 1.0, 4.0, 1.8)

# --- 5. 主逻辑 ---
st.title("🍽️ 餐影工坊 PDF智能拆解版")

files = st.file_uploader("上传图片或PDF菜单文件", type=['jpg','jpeg','png','pdf'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    # --- 【重构素材列表】 ---
    final_dishes_list = []
    
    with st.spinner("正在解析PDF排版并拆解商品主体..."):
        for f in files:
            if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                # PDF 转图片 (300 DPI 保证清晰度)
                pdf_pages = convert_from_bytes(f.read(), dpi=300)
                for i, page in enumerate(pdf_pages):
                    # --- 【新逻辑】：对每一页进行多主体提取 ---
                    page_name = f.name.rsplit('.', 1)[0]
                    # 只有开启开关才进行拆解
                    if auto_crop:
                        extracted_dishes = smart_extract_multiple_subjects(page)
                        for idx, dish in enumerate(extracted_dishes):
                            # 重新赋予独立的文件名
                            dish.filename = f"{page_name}_P{i+1}_{idx+1}.jpg"
                            final_dishes_list.append(dish)
                    else:
                        # 保持整页
                        page.filename = f"{page_name}_P{i+1}.jpg"
                        final_dishes_list.append(page)
            else:
                # 普通图片
                final_dishes_list.append(f)

    conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'auto_crop': auto_crop}

    st.subheader("👀 实时预览")
    # 预览第一张（不论是原图还是PDF拆出来的第一个品）
    p_bytes, p_ext = process_engine(final_dishes_list[0], conf, is_preview=True)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.image(p_bytes, use_container_width=True, caption=f"预览效果：{getattr(final_dishes_list[0], 'filename', final_dishes_list[0].name)}")
    with col2:
        st.success(f"就绪: {len(final_dishes_list)} 张素材")
        st.write(f"📏 目标体积: {'不限' if kb==0 else f'{kb} KB'}")
        
        if len(final_dishes_list) == 1:
            data, ext = process_engine(final_dishes_list[0], conf)
            fname = getattr(final_dishes_list[0], 'filename', final_dishes_list[0].name).rsplit('.', 1)[0]
            st.download_button("📥 下载单图", data, f"{fname}_{tw}x{th}.{ext.lower()}", use_container_width=True)
        else:
            if st.button("🚀 批量合成全部独立图片", use_container_width=True):
                today = datetime.now().strftime("%Y-%m-%d")
                zip_name = f"{today}_{tw}x{th}.zip"; zip_buf = io.BytesIO()
                p_bar = st.progress(0, text="批量合成中...")
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for idx, itm in enumerate(final_dishes_list):
                        data, ext = process_engine(itm, conf)
                        raw_name = getattr(itm, 'filename', itm.name)
                        zf.writestr(f"{raw_name.rsplit('.', 1)[0]}.{ext.lower()}", data)
                        p_bar.progress((idx+1)/len(final_dishes_list))
                st.download_button("📦 下载 ZIP 包", zip_buf.getvalue(), zip_name, use_container_width=True)
else:
    st.info("💡 提示：上传包含格多图的 PDF，开启'智能拆解'可自动提取所有菜品。")
