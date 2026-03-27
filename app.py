import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime
# 需要安装: pip install pdf2image
from pdf2image import convert_from_bytes

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 Pro Max", layout="wide", page_icon="🍽️")

# 初始化 Session State 用于一键清空
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
    .stButton>button {{ height: 2.2em !important; font-size: 0.85rem !important; border-radius: 4px; }}
    /* 重点：清空按钮的红色样式 */
    .stButton>button:contains("一键清空") {{ background-color: #ff4b4b; color: white; border: none; }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法：激进裁切 ---
def smart_crop_dish_aggressive(pil_img):
    open_cv_image = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        if w > 80 and h > 80:
            crop_img = img[y:y+h, x:x+w]
            return Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
    return pil_img

# --- 3. 处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    # 如果输入是字节，转为PIL；如果是PIL对象（PDF转换来的），直接使用
    if isinstance(img_input, bytes) or hasattr(img_input, 'getvalue'):
        img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
    else:
        img = img_input.convert("RGBA")

    if config.get('auto_crop', True):
        img = smart_crop_dish_aggressive(img).convert("RGBA")
    
    tw, th = config['size']
    ratio = min(tw / img.size[0], th / img.size[1])
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
    img_fit = img.resize(new_size, Image.Resampling.LANCZOS)

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
    
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    if ext == "JPEG":
        res.save(out_io, format="JPEG", quality=95, optimize=True)
    else:
        bg.save(out_io, format="PNG")
    return out_io.getvalue(), ext

# --- 4. 侧边栏 UI ---
with st.sidebar:
    st.title("⚙️ 处理参数")
    
    # 【功能2：一键清空】
    st.button("🗑️ 一键清空处理列表", on_click=reset_uploader, use_container_width=True)
    st.markdown("---")

    res_opt = st.selectbox("分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
    if res_opt == "自定义":
        tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)
    else:
        tw, th = map(int, res_opt.split('*'))

    auto_crop = st.toggle("激进版自动裁切脏边", value=True)
    bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色":
        p_color = st.selectbox("颜色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊":
        b_radius = st.slider("模糊度", 0, 100, 40)

    flt = st.selectbox("滤镜", ["原色", "暖色调 (食欲)", "清爽调"])
    br = st.slider("亮度", 0.5, 1.5, 1.05)
    sh = st.slider("清晰度", 1.0, 4.0, 1.8)

# --- 5. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 Pro Max")
st.caption("支持图片/文件夹/PDF自动解析 • 实时预览 • 定向裁切")

# 使用动态 key 实现清空
uploaded_files = st.file_uploader("支持多张图片或单份PDF文件", 
                                  type=['jpg','jpeg','png','pdf'], 
                                  accept_multiple_files=True,
                                  key=f"uploader_{st.session_state.upload_key}")

if uploaded_files:
    # --- 【功能3：PDF 解析逻辑】 ---
    final_image_list = []
    with st.spinner("正在解析文件..."):
        for f in uploaded_files:
            if f.name.lower().endswith('.pdf'):
                # PDF 转图片 (300 DPI 保证清晰度)
                pdf_pages = convert_from_bytes(f.read(), dpi=300)
                for i, page in enumerate(pdf_pages):
                    # 伪装成文件对象名
                    page.filename = f"{f.name.rsplit('.', 1)[0]}_page_{i+1}.jpg"
                    final_image_list.append(page)
            else:
                final_image_list.append(f)

    current_conf = {'size': (tw, th), 'bg_mode': bg_m, 'pure_color': p_color, 
                    'blur_radius': b_radius, 'filter': flt, 'bright': br, 
                    'sharp': sh, 'auto_crop': auto_crop}

    st.subheader("👀 实时效果预览")
    # 预览第一张（不论是原图还是PDF转出来的第一页）
    sample_img = final_image_list[0]
    preview_bytes, preview_ext = process_engine(sample_img, current_conf, is_preview=True)
    
    c1, c2 = st.columns([3, 1])
    with c1:
        st.image(preview_bytes, use_container_width=True)
    with c2:
        st.success(f"解析成功: {len(final_image_list)} 张素材")
        
        if len(final_image_list) == 1:
            data, ext = process_engine(final_image_list[0], current_conf)
            fname = getattr(final_image_list[0], 'filename', final_image_list[0].name).rsplit('.', 1)[0]
            st.download_button("📥 下载图片", data, f"{fname}_{tw}x{th}.{ext.lower()}", use_container_width=True)
        else:
            if st.button("🚀 批量合成全部", use_container_width=True):
                today = datetime.now().strftime("%Y-%m-%d")
                zip_name = f"{today}_{tw}x{th}.zip"
                zip_buf = io.BytesIO()
                p_bar = st.progress(0)
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    for idx, img_obj in enumerate(final_image_list):
                        data, ext = process_engine(img_obj, current_conf)
                        # 获取正确的文件名
                        raw_name = getattr(img_obj, 'filename', getattr(img_obj, 'name', f"image_{idx}"))
                        clean_name = f"{raw_name.rsplit('.', 1)[0]}.{ext.lower()}"
                        zf.writestr(clean_name, data)
                        p_bar.progress((idx + 1) / len(final_image_list))
                st.download_button("📦 下载 ZIP 包", zip_buf.getvalue(), zip_name, use_container_width=True)

else:
    st.info("💡 提示：上传 PDF 会自动将每一页提取为图片并应用当前的'激进裁切'配置。")

st.divider()
st.caption("PDF to Image & Aggressive Crop Engine Ready.")
