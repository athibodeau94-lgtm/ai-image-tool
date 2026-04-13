import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0
if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_files():
    st.session_state.upload_key += 1
    st.rerun()

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 2. 样式注入 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage > img { border-radius: 4px; object-fit: contain; }
    .stDownloadButton, .stButton { margin-bottom: -10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心引擎 (保持羽化融合与深度模糊) ---
def process_engine(img_input, config, is_preview=False):
    try:
        # 兼容 BytesIO 或原始 PIL 对象
        if isinstance(img_input, (bytes, io.BytesIO)):
            img = Image.open(io.BytesIO(img_input if isinstance(img_input, bytes) else img_input.getvalue())).convert("RGBA")
        elif hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue())).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        target_w, target_h = config['size']
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 边界羽化融合 (维持之前解决生硬边界的逻辑)
            mask = Image.new("L", new_size, 255)
            if config['bg_mode'] in ["深度高斯模糊", "提取原色"]:
                draw = ImageDraw.Draw(mask)
                draw.rectangle([0, 0, new_size[0], new_size[1]], outline=0, width=2)
                mask = mask.filter(ImageFilter.GaussianBlur(radius=3)) 
            img_resized.putalpha(mask)

            if config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4))
                bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
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
        if config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明":
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            final_rgb = res_img.convert("RGB")
            q = 95
            if not is_preview and config['limit_kb'] > 0:
                while q > 30:
                    out_io = io.BytesIO()
                    final_rgb.save(out_io, format="JPEG", quality=q, optimize=True)
                    if out_io.tell() <= config['limit_kb'] * 1024: break
                    q -= 5
            else:
                final_rgb.save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except Exception as e:
        return None, str(e)

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 批量导入")
    # 支持多图片上传，且现在支持上传整个 ZIP 文件夹
    raw_uploads = st.file_uploader("直接拖入整个文件夹或其 ZIP 包", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    processed_files = []
    folder_name_hint = "Result"

    if raw_uploads:
        for f in raw_uploads:
            if f.name.lower().endswith('.zip'):
                # 核心：如果是解压包，自动提取内容
                folder_name_hint = os.path.splitext(f.name)[0]
                with zipfile.ZipFile(f) as z:
                    for filename in z.namelist():
                        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                            with z.open(filename) as img_file:
                                img_data = img_file.read()
                                # 模拟文件对象
                                processed_files.append({"name": os.path.basename(filename), "content": img_data})
            else:
                processed_files.append({"name": f.name, "content": f})
                if len(raw_uploads) > 1: folder_name_hint = "Batch"

    with st.container():
        with st.expander("🛠️ 规格设置", expanded=True):
            res_map = {"请选择...": "none", "聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "海报标准 (1:1)": "1200*1200", "自定义尺寸": "custom"}
            res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"res_{st.session_state.settings_key}")
            
            vol_default_idx = 1 if res_label != "请选择..." else 0
            
            if res_label == "自定义尺寸":
                tw = st.number_input("宽", 100, 4000, 1920, key=f"tw_{st.session_state.settings_key}")
                th = st.number_input("高", 100, 4000, 1080, key=f"th_{st.session_state.settings_key}")
                name_part = f"{tw}-{th}"
            else:
                raw_val = res_map[res_label]
                tw, th = (1920, 1080) if raw_val == "none" else map(int, raw_val.split('*'))
                name_part = "5-3" if "5:3" in res_label else raw_val.replace("*", "-")

            vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"], index=vol_default_idx, key=f"vol_{st.session_state.settings_key}")
            kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0, key=f"sm_{st.session_state.settings_key}")

        with st.expander("🎨 视觉设置", expanded=False):
            bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"], key=f"bgm_{st.session_state.settings_key}")
            p_color = "白色"
            if bg_m == "特定颜色":
                p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"], key=f"pcol_{st.session_state.settings_key}")
            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"brad_{st.session_state.settings_key}")
            flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"], key=f"flt_{st.session_state.settings_key}")
            br = st.slider("亮度调节", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化调节", 1.0, 4.0, 1.5, key=f"sh_{st.session_state.settings_key}")

    st.write("---")
    if st.button("🔄 重置所有参数", use_container_width=True):
        reset_all_settings()

with right_col:
    st.subheader("🔍 预览与一键处理")
    if processed_files:
        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'scale_mode': scale_mode}
        
        with st.container(height=450):
            cols = st.columns(3)
            for idx, f_item in enumerate(processed_files):
                with cols[idx % 3]:
                    p_bytes, _ = process_engine(f_item["content"], conf, is_preview=True)
                    if p_bytes: st.image(p_bytes, use_container_width=True, caption=f_item["name"])

        st.write("---")
        if st.button("🗑️ 清空列表", use_container_width=True):
            reset_all_files()
        
        final_zip_name = f"{folder_name_hint}-{name_part}.zip"

        if st.button(f"🚀 导出该文件夹 (共 {len(processed_files)} 张)", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            with st.status("正在极速加工...", expanded=True) as status:
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f_item in processed_files:
                        data, ext = process_engine(f_item["content"], conf)
                        if data:
                            out_name = os.path.splitext(f_item["name"])[0]
                            zf.writestr(f"{out_name}.{ext.lower()}", data)
                status.update(label="✅ 处理完毕！", state="complete")
            st.download_button(f"📥 下载处理后的文件夹: {final_zip_name}", data=zip_buf.getvalue(), file_name=final_zip_name, use_container_width=True)
    else:
        st.info("💡 请直接将文件夹（压缩后）或多张图片拖入左侧。")
