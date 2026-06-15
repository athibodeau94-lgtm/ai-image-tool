import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import fitz

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="餐影工坊 2.0 Pro", 
    page_icon="🔴", 
    layout="wide"
)

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

# --- 智能菜品提取算法 ---
def advanced_extract_foreground(img_obj):
    try:
        src = np.array(img_obj)
        if src.shape[2] < 4:
            src = cv2.cvtColor(src, cv2.COLOR_RGB2RGBA)
            
        h, w = src.shape[:2]
        if min(h, w) < 50:
            return img_obj
            
        max_dim = 600
        scale = max_dim / max(h, w) if max(h, w) > max_dim else 1.0
        img_proc = cv2.resize(src, (int(w * scale), int(h * scale))) if scale != 1.0 else src.copy()
        
        proc_h, proc_w = img_proc.shape[:2]
        gray = cv2.cvtColor(img_proc[:, :, :3], cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 20, 120)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        
        pts = np.argwhere(closed_edges > 0)
        if len(pts) > 100:
            min_y, min_x = pts.min(axis=0)
            max_y, max_x = pts.max(axis=0)
            margin_x, margin_y = int(proc_w * 0.04) + 1, int(proc_h * 0.04) + 1
            bx = max(2, min_x - margin_x)
            by = max(2, min_y - margin_y)
            bw = min(proc_w - bx - 2, (max_x - min_x) + margin_x * 2)
            bh = min(proc_h - by - 2, (max_y - min_y) + margin_y * 2)
            rect = (int(bx/scale), int(by/scale), int(bw/scale), int(bh/scale))
        else:
            rect = (int(w*0.05), int(h*0.05), int(w*0.9), int(h*0.9))
        
        mask = np.zeros((h, w), np.uint8)
        bgdModel = np.zeros((1, 65), np.float64)
        fgdModel = np.zeros((1, 65), np.float64)
        
        rect = (max(0, rect[0]), max(0, rect[1]), min(w - rect[0], rect[2]), min(h - rect[1], rect[3]))
        if rect[2] > 0 and rect[3] > 0:
            cv2.grabCut(src[:, :, :3], mask, rect, bgdModel, fgdModel, 5, cv2.GC_INIT_WITH_RECT)
            bin_mask = np.where((mask == cv2.GC_PR_BGD) | (mask == cv2.GC_BGD), 0, 1).astype('uint8')
            bin_mask_cv = (bin_mask * 255).astype(np.uint8)
            bin_mask_cv = cv2.GaussianBlur(bin_mask_cv, (11, 11), 0)
            
            out_rgba = src.copy()
            out_rgba[:, :, 3] = np.minimum(out_rgba[:, :, 3], bin_mask_cv)
            return Image.fromarray(out_rgba)
    except:
        pass
    return img_obj

# --- 核心处理引擎 ---
def process_engine(img_input, config):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            img = Image.open(io.BytesIO(img_input if isinstance(img_input, bytes) else img_input.getvalue()))
        else:
            img = img_input

        img = img.convert("RGBA")
        
        if config.get('auto_crop', False):
            img = advanced_extract_foreground(img)
            
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
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255)}
                c = color_map.get(config['pure_color'], (255,255,255,255))
                bg = Image.new("RGBA", (target_w, target_h), c)
            elif config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4))
                bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            bg.alpha_composite(img_resized, ((target_w - img_resized.size[0]) // 2, (target_h - img_resized.size[1]) // 2))
            res_img = bg

        if config.get('filter') == "暖色调":
            r, g, b, a = res_img.split()
            r = ImageEnhance.Brightness(r).enhance(1.1)
            b = ImageEnhance.Brightness(b).enhance(0.9)
            res_img = Image.merge("RGBA", (r, g, b, a))
        elif config.get('filter') == "清爽调":
            r, g, b, a = res_img.split()
            b = ImageEnhance.Brightness(b).enhance(1.15)
            res_img = Image.merge("RGBA", (r, g, b, a))

        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        if is_transparent_out or config.get('pure_color') not in ["白色", "黑色", "灰色"]:
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            final_rgb = res_img.convert("RGB")
            final_rgb.save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

# --- 3. 界面布局 ---
left_col, right_col = st.columns([1.2, 2.4], gap="large")

with left_col:
    st.subheader("导入中心")
    raw_uploads = st.file_uploader("支持拖入文件夹、ZIP包、PDF文档或多选图片", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True)
    
    processed_list = []
    zip_prefix = ""

    if raw_uploads:
        zip_prefix = datetime.now().strftime("%m%d")
        for f in raw_uploads:
            if f.name.lower().endswith(('.png', '.jpg', '.jpeg')):
                processed_list.append({"name": f.name, "content": f.getvalue()})

    with st.container():
        with st.expander("规格设置", expanded=True):
            res_map = {
                "-- 请选择尺寸 --": None,
                "聚合标准 (1920*1080)": "1920*1080", 
                "Kiosk/Emenu标准 (5:3)": "1000*600", 
                "封面图 (1080*1250)": "1080*1250"
            }
            res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"res_{st.session_state.settings_key}")
            
            tw, th = (1920, 1080)
            if res_map[res_label]:
                tw, th = map(int, res_map[res_label].split('*'))
            
            vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"], key=f"vol_{st.session_state.settings_key}")
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], key=f"sm_{st.session_state.settings_key}")

        with st.expander("视觉设置 (智能抠图版)", expanded=True):
            auto_crop_mode = st.checkbox("开启智能自动抠图 (智能提取菜品)", value=False, key=f"acrop_{st.session_state.settings_key}")
            
            if auto_crop_mode:
                bg_m = "特定颜色"
                st.selectbox("背景模式", [bg_m], index=0, disabled=True, key=f"bgm_dis_{st.session_state.settings_key}")
            else:
                bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"], index=0, key=f"bgm_{st.session_state.settings_key}")
                
            p_color = "白色"
            if bg_m == "特定颜色":
                if auto_crop_mode:
                    color_options = ["-- 请选择底色 --", "白色", "黑色", "灰色", "透明"]
                else:
                    color_options = ["白色", "黑色", "灰色", "透明"]
                    
                p_color = st.selectbox("底色选择", color_options, index=0, key=f"pcol_{st.session_state.settings_key}")

            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"brad_{st.session_state.settings_key}")
            flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"], key=f"flt_{st.session_state.settings_key}")
            br = st.slider("亮度", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化", 1.0, 4.0, 1.5, key=f"sh_{st.session_state.settings_key}")

    st.markdown("---")
    if st.button("重置所有设置", use_container_width=True):
        reset_all_settings()

with right_col:
    st.subheader("实时预览与导出")
    if processed_list:
        if res_map[res_label] is None:
            st.info("请在左侧【规格设置】中选择比例预设后，即可进行处理。")
        else:
            conf = {
                'size': (tw, th), 'bg_mode': bg_m, 'pure_color': p_color, 
                'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 
                'scale_mode': scale_mode, 'auto_crop': auto_crop_mode
            }
            
            if p_color == "-- 请选择底色 --":
                st.warning("💡 请在左侧选择您需要的【底色颜色】以触发最终渲染输出")
                conf['pure_color'] = "透明"
                
            final_outputs = []
            with st.spinner("多线程并行图像高速洗图转码中..."):
                with ThreadPoolExecutor() as executor:
                    futures = [executor.submit(process_engine, item["content"], conf) for item in processed_list]
                    final_outputs = [f.result() for f in futures]
            
            with st.container(height=480):
                cols = st.columns(3)
                for idx, item in enumerate(processed_list):
                    with cols[idx % 3]:
                        p_bytes, _ = final_outputs[idx]
                        if p_bytes: 
                            st.image(p_bytes, use_container_width=True, caption=item["name"])

            st.markdown("---")
            if len(processed_list) == 1:
                data, ext = final_outputs[0]
                if data:
                    orig_name = os.path.splitext(processed_list[0]["name"])[0]
                    st.download_button(f"下载处理后的图片", data=data, file_name=f"{orig_name}_processed.{ext.lower()}", type="primary", use_container_width=True)
            else:
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for idx, item in enumerate(processed_list):
                        data, ext = final_outputs[idx]
                        if data:
                            name_only = os.path.splitext(item["name"])[0]
                            zf.writestr(f"{name_only}.{ext.lower()}", data)
                st.download_button(f"立即打包下载 ({len(processed_list)}张)", data=zip_buf.getvalue(), file_name=f"canyinggongfang_{zip_prefix}.zip", type="primary", use_container_width=True)
    else:
        st.info("请在左侧上传区域添加菜品图片开始工作。")
