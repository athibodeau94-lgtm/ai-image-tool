import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import fitz

# --- AI 抠图库云端平滑降级检测 ---
try:
    from rembg import remove, new_session
    # 在云端使用最轻量的 u2netp 模型，防爆内存
    bg_session = new_session("u2netp") 
    HAS_REMBG = True
except Exception as e:
    HAS_REMBG = False

# --- 1. 页面配置 ---
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
    
    /* 为预览图区域注入标准的电商透明棋盘格 */
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

# --- AI 智能精准抠图引擎 ---
def ai_extract_foreground(img_obj):
    if not HAS_REMBG:
        return img_obj
    try:
        w, h = img_obj.size
        # 云端严格限宽 800，防止免费服务器算力不足卡死
        max_ai_dim = 800
        if max(w, h) > max_ai_dim:
            scale = max_ai_dim / max(w, h)
            img_for_ai = img_obj.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
        else:
            img_for_ai = img_obj

        # 执行主体分离
        output_rgba = remove(img_for_ai, session=bg_session)
        
        # 还原至原图分辨率
        if max(w, h) > max_ai_dim:
            output_rgba = output_rgba.resize((w, h), Image.Resampling.LANCZOS)
            
        return output_rgba
    except:
        return img_obj

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
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            img = Image.open(io.BytesIO(img_input if isinstance(img_input, bytes) else img_input.getvalue()))
        elif hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue()))
        else:
            img = img_input

        img = img.convert("RGBA")
        
        if config.get('auto_crop', False):
            img = ai_extract_foreground(img)
            
        target_w, target_h = config['size']
        is_transparent_out = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            if config['bg_mode'] in ["深度高斯模糊", "提取原色"] and not is_transparent_out:
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
            if not is_preview and config['limit_kb'] > 0:
                for q in [95, 85, 70, 50, 30]:
                    out_io = io.BytesIO()
                    final_rgb.save(out_io, format="JPEG", quality=q, optimize=True)
                    if out_io.tell() <= config['limit_kb'] * 1024:
                        break
            else:
                final_rgb.save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

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
                "屏保 (1080*1920)": "1080*1920",
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

            vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"], index=vol_default_idx, key=f"vol_{st.session_state.settings_key}")
            kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0, key=f"sm_{st.session_state.settings_key}")

        with st.expander("视觉设置", expanded=False):
            if not HAS_REMBG:
                st.warning("提示：正在等待云端依赖库编译加载，稍后刷新即可解锁 AI 抠图。")
            auto_crop_mode = st.checkbox("开启智能自动抠图 (智能提取菜品)", value=False, disabled=not HAS_REMBG, key=f"acrop_{st.session_state.settings_key}")
            
            bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"], key=f"bgm_{st.session_state.settings_key}")
            p_color = "白色"
            if bg_m == "特定颜色":
                p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"], key=f"pcol_{st.session_state.settings_key}")
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
            'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 
            'scale_mode': scale_mode, 'auto_crop': auto_crop_mode
        }
        
        final_outputs = []
        with st.spinner("多线程图像并行洗图转码中..."):
            with ThreadPoolExecutor() as executor:
                futures = [executor.submit(process_engine, item["content"], conf, is_preview=False) for item in processed_list]
                final_outputs = [f.result() for f in futures]
        
        with st.container(height=450):
            cols = st.columns(3)
            for idx, item in enumerate(processed_list):
                with cols[idx % 3]:
                    p_bytes, _ = final_outputs[idx]
                    if p_bytes: 
                        st.image(p_bytes, use_container_width=True, caption=item["name"])

        st.write("---")

        if len(processed_list) == 1:
            data, ext = final_outputs[0]
            if data:
                orig_name = os.path.splitext(processed_list[0]["name"])[0]
                st.download_button(f"下载处理后的图片: {processed_list[0]['name']}", data=data, file_name=f"{orig_name}.{ext.lower()}", type="primary", use_container_width=True)
        else:
            final_zip_name = f"{zip_prefix}-{dim_name}.zip"
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, item in enumerate(processed_list):
                    data, ext = final_outputs[idx]
                    if data:
                        name_only = os.path.splitext(item["name"])[0]
                        zf.writestr(f"{name_only}.{ext.lower()}", data)
            
            st.download_button(
                label=f"立即打包下载 ({len(processed_list)}张)", 
                data=zip_buf.getvalue(), 
                file_name=final_zip_name, 
                type="primary", 
                use_container_width=True
            )
    else:
        st.info("请在左侧上传区域开始工作。")
