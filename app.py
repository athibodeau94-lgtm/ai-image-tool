import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
import os
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import fitz

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
        border-radius: 4px; 
        object-fit: contain; 
        background-color: #ffffff;
        background-image: linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0), 
                          linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 75%, #f0f0f0 75%, #f0f0f0) !important;
        background-size: 16px 16px !important;
        background-position: 0 0, 8px 8px !important;
    }
    .stDownloadButton, .stButton { margin-bottom: -10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心：四点透视餐盘提取算法 ---
def perspective_crop_plate(img_obj, pts_pct):
    try:
        src = np.array(img_obj)
        if src.shape[2] < 4:
            src = cv2.cvtColor(src, cv2.COLOR_RGB2RGBA)
        h, w = src.shape[:2]
        
        # 将百分比坐标还原为真实像素坐标
        src_pts = np.array([
            [pts_pct[0][0] * w / 100.0, pts_pct[0][1] * h / 100.0],
            [pts_pct[1][0] * w / 100.0, pts_pct[1][1] * h / 100.0],
            [pts_pct[2][0] * w / 100.0, pts_pct[2][1] * h / 100.0],
            [pts_pct[3][0] * w / 100.0, pts_pct[3][1] * h / 100.0]
        ], dtype=np.float32)
        
        # 计算餐盘目标摆正后的新宽高
        width_a = np.sqrt(((src_pts[2][0] - src_pts[3][0]) ** 2) + ((src_pts[2][1] - src_pts[3][1]) ** 2))
        width_b = np.sqrt(((src_pts[1][0] - src_pts[0][0]) ** 2) + ((src_pts[1][1] - src_pts[0][1]) ** 2))
        max_width = max(int(width_a), int(width_b))

        height_a = np.sqrt(((src_pts[1][0] - src_pts[3][0]) ** 2) + ((src_pts[1][1] - src_pts[3][1]) ** 2))
        height_b = np.sqrt(((src_pts[0][0] - src_pts[2][0]) ** 2) + ((src_pts[0][1] - src_pts[2][1]) ** 2))
        max_height = max(int(height_a), int(height_b))
        
        dst_pts = np.array([
            [0, 0],
            [max_width - 1, 0],
            [0, max_height - 1],
            [max_width - 1, max_height - 1]
        ], dtype=np.float32)
        
        # 进行透视变换
        m = cv2.getPerspectiveTransform(src_pts, dst_pts)
        warped = cv2.warpPerspective(src, m, (max_width, max_height))
        
        return Image.fromarray(warped)
    except:
        return img_obj

def super_resolve_and_sharpen(img_obj):
    w, h = img_obj.size
    if w < 1000 or h < 1000:
        scale_factor = 2 if max(w, h) > 500 else 3
        new_w, new_h = int(w * scale_factor), int(h * scale_factor)
        img_obj = img_obj.resize((new_w, new_h), Image.Resampling.LANCZOS)
    img_obj = img_obj.filter(ImageFilter.EDGE_ENHANCE)
    return ImageEnhance.Sharpness(img_obj).enhance(1.4)

# --- 4. 转码渲染引擎 ---
def process_engine(img_input, config, pts_pct=None):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            img = Image.open(io.BytesIO(img_input if isinstance(bytes, bytes) else img_input.getvalue()))
        elif hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue()))
        else:
            img = img_input

        img = img.convert("RGBA")
        
        # 核心改动：如果开启自动抠图且有4点坐标，直接执行餐盘精准切边
        if config.get('auto_crop', False) and pts_pct is not None:
            img = perspective_crop_plate(img, pts_pct)
            
        target_w, target_h = config['size']
        is_transparent_out = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            if is_transparent_out:
                bg = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            elif config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4))
                bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255)}
                c = color_map.get(config['pure_color'], (255,255,255,255))
                bg = Image.new("RGBA", (target_w, target_h), c)
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            bg.alpha_composite(img_resized, ((target_w - img_resized.size[0]) // 2, (target_h - img_resized.size[1]) // 2))
            res_img = bg

        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        if is_transparent_out:
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            final_rgb = res_img.convert("RGB")
            final_rgb.save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

# --- 5. Streamlit 主交互界面 ---
left_col, right_col = st.columns([1.2, 2.4], gap="large")

with left_col:
    st.subheader("导入中心")
    raw_uploads = st.file_uploader("支持拖入文件夹、ZIP包、PDF文档或多选图片", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True)
    
    processed_list = []
    zip_prefix = ""

    if raw_uploads:
        zip_files = [f for f in raw_uploads if f.name.lower().endswith('.zip')]
        pdf_files = [f for f in raw_uploads if f.name.lower().endswith('.pdf')]
        
        if zip_files:
            zip_prefix = os.path.splitext(zip_files[0].name)[0]
            with zipfile.ZipFile(zip_files[0]) as z:
                for filename in z.namelist():
                    if filename.lower().endswith(('.png', '.jpg', '.jpeg')) and not filename.startswith('__MACOSX'):
                        with z.open(filename) as img_f:
                            processed_list.append({"name": os.path.basename(filename), "content": img_f.read()})
        elif pdf_files:
            pdf_file = pdf_files[0]
            zip_prefix = os.path.splitext(pdf_file.name)[0]
            doc = fitz.open(stream=pdf_file.getvalue(), filetype="pdf")
            img_idx = 1
            for page_num in range(len(doc)):
                page = doc[page_num]
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    base_image = doc.extract_image(xref)
                    raw_pil = Image.open(io.BytesIO(base_image["image"]))
                    hd_pil = super_resolve_and_sharpen(raw_pil)
                    hd_io = io.BytesIO()
                    hd_pil.save(hd_io, format="JPEG")
                    processed_list.append({"name": f"pdf_img_{img_idx}.jpg", "content": hd_io.getvalue()})
                    img_idx += 1
        else:
            zip_prefix = datetime.now().strftime("%m%d")
            for f in raw_uploads:
                processed_list.append({"name": f.name, "content": f.getvalue()})

    with st.container():
        with st.expander("规格设置", expanded=True):
            res_map = {
                "请选择...": "none", 
                "聚合标准 (1920*1080)": "1920*1080", 
                "Kiosk/Emenu标准 (5:3)": "1000*600", 
                "封面图 (1080*1250)": "1080*1250",
                "自定义尺寸": "custom"
            }
            res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"res_{st.session_state.settings_key}")
            vol_default_idx = 1 if res_label != "请选择..." else 0
            
            if res_label == "自定义尺寸":
                tw = st.number_input("宽", 100, 4000, 1920, key=f"tw_{st.session_state.settings_key}")
                th = st.number_input("高", 100, 4000, 1080, key=f"th_{st.session_state.settings_key}")
                dim_name = f"{tw}-{th}"
            else:
                raw_val = res_map[res_label]
                tw, th = (1920, 1080) if raw_val == "none" else map(int, raw_val.split('*'))
                dim_name = "5-3" if "5:3" in res_label else raw_val.replace("*", "-")

            vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"], index=vol_default_idx, key=f"vol_{st.session_state.settings_key}")
            kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0, key=f"sm_{st.session_state.settings_key}")

        with st.expander("视觉设置", expanded=True):
            auto_crop_mode = st.checkbox("开启智能自动抠图 (智能提取菜品)", value=False, key=f"acrop_{st.session_state.settings_key}")
            
            # 当开启智能抠图时，允许用户直接通过百分比滑块定义餐盘的 4 个顶角
            if auto_crop_mode:
                st.markdown("**📌 请微调下方滑块，使选择框完美锁定制餐盘的四个角：**")
                col_pt1, col_pt2 = st.columns(2)
                with col_pt1:
                    p1_x = st.slider("左上角 X (%)", 0, 50, 2, key="p1x")
                    p1_y = st.slider("左上角 Y (%)", 0, 50, 5, key="p1y")
                    p3_x = st.slider("左下角 X (%)", 0, 50, 2, key="p3x")
                    p3_y = st.slider("左下角 Y (%)", 50, 100, 95, key="p3y")
                with col_pt2:
                    p2_x = st.slider("右上角 X (%)", 50, 100, 98, key="p2x")
                    p2_y = st.slider("右上角 Y (%)", 0, 50, 2, key="p2y")
                    p4_x = st.slider("右下角 X (%)", 50, 100, 98, key="p4x")
                    p4_y = st.slider("右下角 Y (%)", 50, 100, 80, key="p4y")
                current_pts = [(p1_x, p1_y), (p2_x, p2_y), (p3_x, p3_y), (p4_x, p4_y)]
            else:
                current_pts = None

            bg_m = st.selectbox("背景模式", ["特定颜色", "深度高斯模糊", "提取原色"], key=f"bgm_{st.session_state.settings_key}")
            p_color = "白色"
            if bg_m == "特定颜色":
                p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"], key=f"pcol_{st.session_state.settings_key}")
            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"brad_{st.session_state.settings_key}")
            br = st.slider("亮度", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化", 1.0, 4.0, 1.3, key=f"sh_{st.session_state.settings_key}")

    st.write("---")
    if st.button("重置所有设置", use_container_width=True):
        reset_all_settings()

with right_col:
    st.subheader("实时预览与导出")
    if processed_list:
        conf = {
            'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'bright': br, 'sharp': sh, 
            'scale_mode': scale_mode, 'auto_crop': auto_crop_mode
        }
        
        final_outputs = []
        with st.spinner("并行洗图转码中..."):
            with ThreadPoolExecutor() as executor:
                futures = [executor.submit(process_engine, item["content"], conf, current_pts) for item in processed_list]
                final_outputs = [f.result() for f in futures]
        
        with st.container(height=480):
            cols = st.columns(2)
            for idx, item in enumerate(processed_list):
                with cols[idx % 2]:
                    p_bytes, _ = final_outputs[idx]
                    if p_bytes: 
                        st.image(p_bytes, use_container_width=True, caption=item["name"])

        st.write("---")
        if len(processed_list) == 1:
            data, ext = final_outputs[0]
            if data:
                orig_name = os.path.splitext(processed_list[0]["name"])[0]
                st.download_button(f"下载处理后的图片", data=data, file_name=f"{orig_name}.{ext.lower()}", type="primary", use_container_width=True)
        else:
            final_zip_name = f"{zip_prefix}-{dim_name}.zip"
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, item in enumerate(processed_list):
                    data, ext = final_outputs[idx]
                    if data:
                        name_only = os.path.splitext(item["name"])[0]
                        zf.writestr(f"{name_only}.{ext.lower()}", data)
            st.download_button(label=f"立即打包下载 ({len(processed_list)}张)", data=zip_buf.getvalue(), file_name=final_zip_name, type="primary", use_container_width=True)
    else:
        st.info("请在左侧上传区域开始工作。")
