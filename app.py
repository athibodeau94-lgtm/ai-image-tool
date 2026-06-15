import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io, zipfile, os, cv2, fitz
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置与状态初始化 ---
st.set_page_config(page_title="餐影工坊", layout="wide")
if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 2. 样式注入 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage > img { 
        border-radius: 4px; object-fit: contain; background-color: #ffffff;
        background-image: linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0), 
                          linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0) !important;
        background-size: 16px 16px !important; background-position: 0 0, 8px 8px !important;
    }
    .stDownloadButton, .stButton { margin-bottom: -10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 四点透视餐盘提取算法 ---
def perspective_crop_plate(img_obj, pts_pct):
    try:
        src = np.array(img_obj)
        if src.shape[2] < 4:
            src = cv2.cvtColor(src, cv2.COLOR_RGB2RGBA)
        h, w = src.shape[:2]
        
        src_pts = np.array([
            [pts_pct[0][0] * w / 100.0, pts_pct[0][1] * h / 100.0],
            [pts_pct[1][0] * w / 100.0, pts_pct[1][1] * h / 100.0],
            [pts_pct[2][0] * w / 100.0, pts_pct[2][1] * h / 100.0],
            [pts_pct[3][0] * w / 100.0, pts_pct[3][1] * h / 100.0]
        ], dtype=np.float32)
        
        width_a = np.sqrt(((src_pts[1][0] - src_pts[0][0]) ** 2) + ((src_pts[1][1] - src_pts[0][1]) ** 2))
        width_b = np.sqrt(((src_pts[3][0] - src_pts[2][0]) ** 2) + ((src_pts[3][1] - src_pts[2][1]) ** 2))
        max_width = max(int(width_a), int(width_b), 50)

        height_a = np.sqrt(((src_pts[2][0] - src_pts[0][0]) ** 2) + ((src_pts[2][1] - src_pts[0][1]) ** 2))
        height_b = np.sqrt(((src_pts[3][0] - src_pts[1][0]) ** 2) + ((src_pts[3][1] - src_pts[1][1]) ** 2))
        max_height = max(int(height_a), int(height_b), 50)
        
        dst_pts = np.array([[0, 0], [max_width - 1, 0], [0, max_height - 1], [max_width - 1, max_height - 1]], dtype=np.float32)
        m = cv2.getPerspectiveTransform(src_pts, dst_pts)
        warped = cv2.warpPerspective(src, m, (max_width, max_height))
        return Image.fromarray(warped)
    except:
        return img_obj

def super_resolve_and_sharpen(img_obj):
    w, h = img_obj.size
    if w < 1000 or h < 1000:
        scale_factor = 2 if max(w, h) > 500 else 3
        img_obj = img_obj.resize((int(w * scale_factor), int(h * scale_factor)), Image.Resampling.LANCZOS)
    return ImageEnhance.Sharpness(img_obj.filter(ImageFilter.EDGE_ENHANCE)).enhance(1.4)

# --- 4. 转码渲染引擎 ---
def process_engine(img_input, config, pts_pct=None):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            raw_bytes = img_input if isinstance(img_input, bytes) else img_input.getvalue()
            img = Image.open(io.BytesIO(raw_bytes))
        else:
            img = Image.open(io.BytesIO(img_input.getvalue())) if hasattr(img_input, 'getvalue') else img_input

        img = img.convert("RGBA")
        if config.get('auto_crop', False) and pts_pct is not None:
            img = perspective_crop_plate(img, pts_pct)
            
        target_w, target_h = config['size']
        is_transparent = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            img_resized = img.resize((int(original_w * ratio), int(original_h * ratio)), Image.Resampling.LANCZOS)
            
            if is_transparent:
                bg = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            elif config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4)).filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                c = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255)}.get(config['pure_color'], (255,255,255,255))
                bg = Image.new("RGBA", (target_w, target_h), c)
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            bg.alpha_composite(img_resized, ((target_w - img_resized.size[0]) // 2, (target_h - img_resized.size[1]) // 2))
            res_img = bg

        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        if is_transparent:
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            res_img.convert("RGB").save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

# --- 5. Streamlit 主交互界面 ---
left_col, right_col = st.columns([1.3, 2.4], gap="large")

with left_col:
    st.subheader("导入中心")
    raw_uploads = st.file_uploader("支持多选图片、ZIP或PDF", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True)
    processed_list = []
    zip_prefix = ""

    if raw_uploads:
        zip_files = [f for f in raw_uploads if f.name.lower().endswith('.zip')]
        pdf_files = [f for f in raw_uploads if f.name.lower().endswith('.pdf')]
        if zip_files:
            zip_prefix = os.path.splitext(zip_files[0].name)[0]
            with zipfile.ZipFile(zip_files[0]) as z:
                for f in z.namelist():
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.startswith('__MACOSX'):
                        with z.open(f) as img_f: processed_list.append({"name": os.path.basename(f), "content": img_f.read()})
        elif pdf_files:
            zip_prefix = os.path.splitext(pdf_files[0].name)[0]
            doc = fitz.open(stream=pdf_files[0].getvalue(), filetype="pdf")
            for page in doc:
                for img_info in page.get_images(full=True):
                    raw_pil = Image.open(io.BytesIO(doc.extract_image(img_info[0])["image"]))
                    hd_io = io.BytesIO()
                    super_resolve_and_sharpen(raw_pil).save(hd_io, format="JPEG")
                    processed_list.append({"name": f"pdf_img_{len(processed_list)+1}.jpg", "content": hd_io.getvalue()})
        else:
            zip_prefix = datetime.now().strftime("%m%d")
            for f in raw_uploads: processed_list.append({"name": f.name, "content": f.getvalue()})

    with st.container():
        with st.expander("规格设置", expanded=True):
            res_map = {"请选择...": "none", "聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "封面图 (1080*1250)": "1080*1250", "自定义尺寸": "custom"}
            res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"r_{st.session_state.settings_key}")
            if res_label == "自定义尺寸":
                tw = st.number_input("宽", 100, 4000, 1920, key=f"w_{st.session_state.settings_key}")
                th = st.number_input("高", 100, 4000, 1080, key=f"h_{st.session_state.settings_key}")
                dim_name = f"{tw}-{th}"
            else:
                tw, th = (1920, 1080) if res_map[res_label] == "none" else map(int, res_map[res_label].split('*'))
                dim_name = "5-3" if "5:3" in res_label else res_map[res_label].replace("*", "-")
            vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"], index=1 if res_label != "请选择..." else 0, key=f"v_{st.session_state.settings_key}")
            kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], key=f"s_{st.session_state.settings_key}")

        with st.expander("视觉设置", expanded=True):
            auto_crop_mode = st.checkbox("开启智能自动抠图 (智能提取菜品)", value=False, key=f"ac_{st.session_state.settings_key}")
            current_pts = None
            if auto_crop_mode:
                st.markdown("**📌 调节下方滑块，让红框锁制餐盘：**")
                p1_x = st.slider("左上角 X (%)", 0, 100, 1)
                p1_y = st.slider("左上角 Y (%)", 0, 100, 9)
                p2_x = st.slider("右上角 X (%)", 0, 100, 98)
                p2_y = st.slider("右上角 Y (%)", 0, 100, 2)
                p3_x = st.slider("左下角 X (%)", 0, 100, 11)
                p3_y = st.slider("左下角 Y (%)", 0, 100, 83)
                p4_x = st.slider("右下角 X (%)", 0, 100, 99)
                p4_y = st.slider("右下角 Y (%)", 0, 100, 68)
                current_pts = [(p1_x, p1_y), (p2_x, p2_y), (p3_x, p3_y), (p4_x, p4_y)]
                
                if processed_list:
                    try:
                        ref_img = Image.open(io.BytesIO(processed_list[0]["content"])).convert("RGB")
                        rw, rh = ref_img.size
                        draw = ImageDraw.Draw(ref_img)
                        draw.polygon([(p1_x*rw/100, p1_y*rh/100), (p2_x*rw/100, p2_y*rh/100), (p4_x*rw/100, p4_y*rh/100), (p3_x*rw/100, p3_y*rh/100)], outline="red", width=4)
                        st.image(ref_img, use_container_width=True, caption="🔴 红框内为保留区域")
                    except: pass

            bg_m = st.selectbox("背景模式", ["特定颜色", "深度高斯模糊", "提取原色"], key=f"b_{st.session_state.settings_key}")
            p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"], key=f"p_{st.session_state.settings_key}") if bg_m == "特定颜色" else "白色"
            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"bl_{st.session_state.settings_key}")
            br = st.slider("亮度", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化", 1.0, 4.0, 1.3, key=f"sh_{st.session_state.settings_key}")

    st.write("---")
    if st.button("重置所有设置", use_container_width=True): reset_all_settings()

with right_col:
    st.subheader("实时预览与导出")
    if processed_list:
        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 'blur_radius': b_radius, 'bright': br, 'sharp': sh, 'scale_mode': scale_mode, 'auto_crop': auto_crop_mode}
        final_outputs = []
        with st.spinner("透视矫正与画面转码中..."):
            with ThreadPoolExecutor() as executor:
                futures = [executor.submit(process_engine, item["content"], conf, current_pts) for item in processed_list]
                final_outputs = [f.result() for f in futures]
        
        with st.container(height=480):
            cols = st.columns(2)
            for idx, item in enumerate(processed_list):
                with cols[idx % 2]:
                    p_bytes, _ = final_outputs[idx]
                    if p_bytes: st.image(p_bytes, use_container_width=True, caption=item["name"])

        st.write("---")
        if len(processed_list) == 1:
            data, ext = final_outputs[0]
            if data: st.download_button("下载处理后的图片", data=data, file_name=f"{os.path.splitext(processed_list[0]['name'])[0]}.{ext.lower()}", type="primary", use_container_width=True)
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, item in enumerate(processed_list):
                    data, ext = final_outputs[idx]
                    if data: zf.writestr(f"{os.path.splitext(item['name'])[0]}.{ext.lower()}", data)
            st.download_button(label=f"立即打包下载 ({len(processed_list)}张)", data=zip_buf.getvalue(), file_name=f"{zip_prefix}-{dim_name}.zip", type="primary", use_container_width=True)
    else:
        st.info("请在左侧上传区域开始工作。")
