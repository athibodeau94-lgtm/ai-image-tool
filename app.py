import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# --- 2. 注入 CSS：实现单屏锁定与UI美化 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    [data-testid="stSidebar"] {display: none;}
    .block-container {padding-top: 2rem !important; padding-bottom: 0rem !important;}
    .stImage { border-radius: 4px; border: 1px solid #eee; margin-bottom: 10px; }
    div.stExpander { border: none !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 ---
def smart_extract_multiple_subjects(pil_img):
    try:
        open_cv_image = np.array(pil_img.convert('RGB'))
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15,15))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        extracted_images = []
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for c in contours:
            area = cv2.contourArea(c)
            x, y, w, h = cv2.boundingRect(c)
            if area < 8000 or w > img.shape[1] * 0.95 or h > img.shape[0] * 0.95: continue
            crop_img = img[y:y+h, x:x+w]
            extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))
        return extracted_images if extracted_images else [pil_img]
    except: return [pil_img]

def process_engine(img_input, config, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        tw, th = config['size']
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        img.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
        
        is_transparent = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config['bg_mode'] == "深度高斯模糊":
            bg = img.convert("RGB").resize((render_w, render_h)).filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
        elif config['bg_mode'] == "特定颜色":
            color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
            bg = Image.new("RGBA", (render_w, render_h), color_map.get(config['pure_color'], (255,255,255,255)))
        else:
            sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
            bg = Image.new("RGBA", (render_w, render_h), sample + (255,))
        
        bg.alpha_composite(img, ((render_w - img.size[0]) // 2, (render_h - img.size[1]) // 2))
        
        if is_transparent:
            res = bg
        else:
            res = bg.convert("RGB")
            res = ImageEnhance.Brightness(res).enhance(config['bright'])
            res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
        
        out_io = io.BytesIO()
        if is_transparent:
            res.save(out_io, format="PNG")
            ext = "PNG"
        else:
            ext = "JPEG"
            q = 90 if is_preview else 95
            while q > 30:
                out_io = io.BytesIO()
                res.save(out_io, format="JPEG", quality=q, optimize=True)
                if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
                q -= 5
        return out_io.getvalue(), ext
    except Exception as e:
        return None, f"err: {str(e)}"

# --- 4. 界面重构 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], 
                             accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    with st.expander("🛠️ 规格设置", expanded=True):
        res_map = {
            "聚合标准 (1920*1080)": "1920*1080",
            "Kiosk/Emenu标准 (5:3)": "1000*600",
            "自定义": "custom",
            "海报标准 (1:1)": "1200*1200",
            "小红书 (3:4)": "900*1200",
            "高清 (16:9)": "1920*1080"
        }
        res_label = st.selectbox("比例预设", list(res_map.keys()))
        if res_label == "自定义":
            tw = st.number_input("宽", 100, 4000, 1920)
            th = st.number_input("高", 100, 4000, 1080)
        else:
            tw, th = map(int, res_map[res_label].split('*'))
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
        kb = 0
        if vol_opt == "自定义":
            c1, c2 = st.columns([2, 1])
            with c1: val = st.number_input("数值", 1, 10240, 500)
            with c2: unit = st.selectbox("单位", ["KB", "MB"])
            kb = val if unit == "KB" else val * 1024
        else: kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)

    with st.expander("🎨 视觉设置", expanded=False):
        # 此处已改为默认关闭 (value=False)
        auto_crop = st.toggle("多主体识别拆分", value=False)
        bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = "白色"
        if bg_m == "特定颜色": p_color = st.selectbox("底色", ["白色", "黑色", "灰色", "透明"])
        b_radius = st.slider("模糊强度", 10, 100, 40) if bg_m == "深度高斯模糊" else 40
        br = st.slider("亮度", 0.5, 1.5, 1.05)
        sh = st.slider("锐化", 1.0, 4.0, 1.5)
    
    if st.button("🗑️ 清空所有数据", use_container_width=True): reset_uploader()

with right_col:
    st.subheader("🔍 实时预览区")
    if files:
        final_list = []
        with st.spinner("处理中..."):
            for f in files:
                try:
                    if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                        pages = convert_from_bytes(f.read(), dpi=120)
                        for i, p in enumerate(pages):
                            if auto_crop:
                                for idx, dish in enumerate(smart_extract_multiple_subjects(p)):
                                    dish.filename = f"{f.name}_P{i+1}_{idx+1}.jpg"; final_list.append(dish)
                            else: p.filename = f"{f.name}_P{i+1}.jpg"; final_list.append(p)
                    else:
                        img_obj = Image.open(f)
                        if auto_crop:
                            for idx, dish in enumerate(smart_extract_multiple_subjects(img_obj)):
                                dish.filename = f"{f.name.split('.')[0]}_{idx+1}.jpg"; final_list.append(dish)
                        else: final_list.append(f)
                except: continue

        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
                'blur_radius': b_radius, 'bright': br, 'sharp': sh}

        with st.container(height=520):
            cols = st.columns(3)
            for idx, item in enumerate(final_list):
                with cols[idx % 3]:
                    p_bytes, _ = process_engine(item, conf, is_preview=True)
                    if p_bytes: st.image(p_bytes, width="stretch")

        st.write("---")
        if len(final_list) == 1:
            data, ext = process_engine(final_list[0], conf)
            if data:
                orig_name = getattr(final_list[0], 'filename', getattr(final_list[0], 'name', "output.jpg"))
                st.download_button(label="📥 下载处理后的图片", data=data, 
                                   file_name=f"{orig_name.split('.')[0]}.{ext.lower()}", 
                                   mime=f"image/{ext.lower()}", type="primary", use_container_width=True)
        elif len(final_list) > 1:
            if st.button("🚀 准备批量下载 (打包 ZIP)", type="primary", use_container_width=True):
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w') as zf:
                    with ThreadPoolExecutor() as executor:
                        futures = {executor.submit(process_engine, itm, conf): itm for itm in final_list}
                        for i, future in enumerate(futures):
                            data, ext = future.result()
                            if data:
                                itm = futures[future]
                                name = getattr(itm, 'filename', getattr(itm, 'name', f"img_{i}.jpg"))
                                zf.writestr(f"{name.split('.')[0]}.{ext.lower()}", data)
                st.download_button(label="📥 点击获取 ZIP 压缩包", data=zip_buf.getvalue(), 
                                   file_name=f"Batch_{datetime.now().strftime('%H%M')}.zip", 
                                   mime="application/zip", use_container_width=True)
    else:
        st.info("上传文件后，预览和下载按钮将在此处显示。")
