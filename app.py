import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import fitz  # PyMuPDF 库，用于解析 PDF
import gc    # 主动清理内存
import cv2
import numpy as np

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide")

if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 辅助函数：智能主体视觉重心检测算法（防爆低内存版） ---
def detect_subject_center(pil_img):
    try:
        # 生成 400px 极小缩略图再识别，大幅节省内存，防止崩溃
        img_small = pil_img.copy()
        img_small.thumbnail((400, 400), Image.Resampling.LANCZOS)
        
        cv_img = cv2.cvtColor(np.array(img_small.convert("RGB")), cv2.COLOR_RGB2BGR)
        h, w = cv_img.shape[:2]
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        
        edges = cv2.Canny(gray, 40, 120)
        kernel = np.ones((15, 15), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)
        
        M = cv2.moments(dilated)
        if M["m00"] > 0:
            cx = (M["m10"] / M["m00"]) / w
            cy = (M["m01"] / M["m00"]) / h
            return (max(0.15, min(0.85, cx)), max(0.15, min(0.85, cy)))
    except Exception:
        pass
    return (0.5, 0.5)

# --- 辅助函数：生成马赛克（棋盘格）背景 ---
def create_checkerboard_bg(width, height, square_size=20):
    bg = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(bg)
    color_gray = (220, 220, 220, 255)
    
    for y in range(0, height, square_size):
        for x in range(0, width, square_size):
            if ((x // square_size) + (y // square_size)) % 2 == 1:
                draw.rectangle([x, y, x + square_size, y + square_size], fill=color_gray)
    return bg

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

# --- PDF 低清小图智能高清重构算法 ---
def super_resolve_and_sharpen(img_obj):
    w, h = img_obj.size
    if w < 1000 or h < 1000:
        scale_factor = 2 if max(w, h) > 500 else 3
        new_w, new_h = int(w * scale_factor), int(h * scale_factor)
        img_obj = img_obj.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
    img_obj = img_obj.filter(ImageFilter.EDGE_ENHANCE)
    img_obj = ImageEnhance.Sharpness(img_obj).enhance(1.4)
    return img_obj

# --- 3. 高性能核心引擎 ---
def process_engine(img_input, config, is_preview=False):
    img = None
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            img = Image.open(io.BytesIO(img_input if isinstance(img_input, bytes) else img_input.getvalue()))
        elif hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue()))
        else:
            img = img_input

        img = img.convert("RGBA")
        target_w, target_h = config['size']
        
        is_transparent_out = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            crop_focus = config.get('crop_focus', '智能识别主体')
            if crop_focus == "智能识别主体":
                cx, cy = detect_subject_center(img)
            elif crop_focus == "自定义偏移":
                cx = config.get('crop_x', 0.5)
                cy = config.get('crop_y', 0.5)
            else:
                cx, cy = 0.5, 0.5
            
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS, centering=(cx, cy))
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            if config['bg_mode'] == "深度高斯模糊" and not is_transparent_out:
                mask = Image.new("L", new_size, 255)
                draw = ImageDraw.Draw(mask)
                draw.rectangle([0, 0, new_size[0], new_size[1]], outline=0, width=2)
                mask = mask.filter(ImageFilter.GaussianBlur(radius=3)) 
                img_resized.putalpha(mask)

            if is_transparent_out:
                bg = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            elif config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4))
                bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                if config['pure_color'] == "马赛克":
                    bg = create_checkerboard_bg(target_w, target_h, square_size=24)
                else:
                    color_map = {"白色": (255, 255, 255, 255), "黑色": (0, 0, 0, 255), "灰色": (200, 200, 200, 255)}
                    c = color_map.get(config['pure_color'], (255, 255, 255, 255))
                    bg = Image.new("RGBA", (target_w, target_h), c)
            else:
                bg = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 255))
            
            bg.alpha_composite(img_resized, ((target_w - img_resized.size[0]) // 2, (target_h - img_resized.size[1]) // 2))
            res_img = bg
            del img_resized

        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        
        if is_transparent_out:
            res_img.save(out_io, format="PNG")
            val = out_io.getvalue()
            return val, "png"
        else:
            final_rgb = res_img.convert("RGB")
            del res_img
            if not is_preview and config['limit_kb'] > 0:
                for q in [95, 85, 70, 50, 30]:
                    out_io = io.BytesIO()
                    final_rgb.save(out_io, format="JPEG", quality=q, optimize=True)
                    if out_io.tell() <= config['limit_kb'] * 1024:
                        break
            else:
                final_rgb.save(out_io, format="JPEG", quality=95, optimize=True)
            val = out_io.getvalue()
            return val, "jpg"
    except Exception as e:
        return None, "Error"
    finally:
        if 'img' in locals(): del img
        if 'res_img' in locals(): del res_img
        if 'final_rgb' in locals(): del final_rgb

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

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
                    
                    img_bytes = base_image["image"]
                    img_ext = base_image["ext"]
                    
                    raw_pil = Image.open(io.BytesIO(img_bytes))
                    hd_pil = super_resolve_and_sharpen(raw_pil)
                    
                    hd_io = io.BytesIO()
                    hd_pil.save(hd_io, format="PNG" if img_ext.lower() == "png" else "JPEG")
                    
                    fake_name = f"pdf_img_{img_idx}.{img_ext}"
                    processed_list.append({"name": fake_name, "content": hd_io.getvalue()})
                    img_idx += 1
                    
                    del raw_pil, hd_pil
            doc.close()
        else:
            zip_prefix = datetime.now().strftime("%m%d")
            for f in raw_uploads:
                processed_list.append({"name": f.name, "content": f.getvalue()})

    with st.container():
        # 1. 规格设置 (默认展开)
        with st.expander("规格设置", expanded=True):
            res_map = {
                "请选择...": "none", 
                "聚合标准 (1920*1080)": "1920*1080", 
                "Kiosk/Emenu标准 (5:3)": "1000*600", 
                "封面图 (1080*1250)": "1080*1250",
                "屏保 (1080*1920)": "1080*1920",
                "自定义尺寸": "custom"
            }
            res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"res_{st.session_state.settings_key}")
            
            vol_default_idx = 1 if res_label != "请选择..." else 0
            
            if res_label == "自定义尺寸":
                col_w, col_h = st.columns(2)
                with col_w:
                    tw = st.number_input("宽 (px)", 100, 4000, 1920, key=f"tw_{st.session_state.settings_key}")
                with col_h:
                    th = st.number_input("高 (px)", 100, 4000, 1080, key=f"th_{st.session_state.settings_key}")
                dim_name = f"{tw}-{th}"
            else:
                raw_val = res_map[res_label]
                tw, th = (1920, 1080) if raw_val == "none" else map(int, raw_val.split('*'))
                dim_name = "5-3" if "5:3" in res_label else raw_val.replace("*", "-")

            vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"], index=vol_default_idx, key=f"vol_{st.session_state.settings_key}")
            if vol_opt == "自定义":
                kb = st.number_input("最大体积限制 (KB)", 10, 10240, 800, key=f"custom_kb_{st.session_state.settings_key}")
            else:
                kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
                
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0, key=f"sm_{st.session_state.settings_key}")

            crop_focus = "智能识别主体"
            crop_x, crop_y = 0.5, 0.5
            if scale_mode == "居中裁剪铺满 (大图感)":
                crop_focus = st.selectbox("裁剪重心焦点", ["智能识别主体", "绝对几何居中", "自定义偏移"], key=f"cf_{st.session_state.settings_key}")
                if crop_focus == "自定义偏移":
                    col_cx, col_cy = st.columns(2)
                    with col_cx:
                        crop_x = st.slider("横向焦点 (左← →右)", 0.0, 1.0, 0.4, 0.05, key=f"cx_{st.session_state.settings_key}")
                    with col_cy:
                        crop_y = st.slider("纵向焦点 (上← →下)", 0.0, 1.0, 0.5, 0.05, key=f"cy_{st.session_state.settings_key}")

        # 2. 视觉设置 (设置 expanded=True，默认展开)
        with st.expander("视觉设置", expanded=True):
            bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色"], key=f"bgm_{st.session_state.settings_key}")
            p_color = "白色"
            if bg_m == "特定颜色":
                p_color = st.selectbox("底色选择", ["白色", "透明", "黑色", "马赛克", "灰色"], key=f"pcol_{st.session_state.settings_key}")
            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"brad_{st.session_state.settings_key}")
            flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"], key=f"flt_{st.session_state.settings_key}")
            br = st.slider("亮度", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化", 1.0, 4.0, 1.5, key=f"sh_{st.session_state.settings_key}")

    st.write("---")
    if st.button("重置所有设置", use_container_width=True):
        reset_all_settings()

with right_col:
    st.subheader("实时预览与导出")
    if processed_list:
        conf = {
            'size': (tw, th), 
            'limit_kb': kb, 
            'bg_mode': bg_m, 
            'pure_color': p_color, 
            'blur_radius': b_radius, 
            'filter': flt, 
            'bright': br, 
            'sharp': sh, 
            'scale_mode': scale_mode,
            'crop_focus': crop_focus,
            'crop_x': crop_x,
            'crop_y': crop_y
        }
        
        final_outputs = []
        with st.spinner("图像处理中..."):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(process_engine, item["content"], conf, is_preview=False) for item in processed_list]
                final_outputs = [f.result() for f in futures]
        
        gc.collect()

        # 1. 实时预览展示与文件名重命名框
        edited_names = []
        with st.container(height=480):
            cols = st.columns(3)
            for idx, item in enumerate(processed_list):
                with cols[idx % 3]:
                    p_bytes, _ = final_outputs[idx]
                    if p_bytes: 
                        st.image(p_bytes, use_container_width=True)
                        name_stem, _ = os.path.splitext(item["name"])
                        user_edited_stem = st.text_input(
                            label="图片名称", 
                            value=name_stem, 
                            key=f"rename_{idx}_{st.session_state.settings_key}", 
                            label_visibility="collapsed"
                        )
                        edited_names.append(user_edited_stem)

        st.write("---")

        # 2. 导出下载逻辑（含文件名重构、重名自动加编号与 .jpg 后缀）
        if len(processed_list) == 1:
            data, ext = final_outputs[0]
            if data:
                raw_stem = edited_names[0].strip() if edited_names and edited_names[0].strip() else os.path.splitext(processed_list[0]["name"])[0]
                final_filename = f"{raw_stem}.{ext.lower()}"
                st.download_button(f"下载处理后的图片: {final_filename}", data=data, file_name=final_filename, type="primary", use_container_width=True)
        else:
            final_zip_name = f"{zip_prefix}-{dim_name}.zip"
            zip_buf = io.BytesIO()
            
            filename_counts = {}
            success_count = 0
            
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, item in enumerate(processed_list):
                    data, ext = final_outputs[idx]
                    if data:
                        raw_stem = edited_names[idx].strip() if idx < len(edited_names) and edited_names[idx].strip() else os.path.splitext(item["name"])[0]
                        
                        # 重名检测：如果文件名重复，自动补齐 _1, _2 后缀，保证 40 张图全部完整导出
                        if raw_stem in filename_counts:
                            filename_counts[raw_stem] += 1
                            final_stem = f"{raw_stem}_{filename_counts[raw_stem]}"
                        else:
                            filename_counts[raw_stem] = 0
                            final_stem = raw_stem
                        
                        final_filename = f"{final_stem}.{ext.lower()}"
                        zf.writestr(final_filename, data)
                        success_count += 1
            
            st.download_button(
                label=f"立即打包下载 ({success_count}张)", 
                data=zip_buf.getvalue(), 
                file_name=final_zip_name, 
                type="primary", 
                use_container_width=True
            )
            
            del final_outputs
            gc.collect()
    else:
        st.info("请在左侧上传区域开始工作。")
