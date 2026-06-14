import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import io
import zipfile
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

def reset_all_settings():
    st.session_state.settings_key += 1
    st.rerun()

# --- 2. 样式注入 (新增棋盘格保护，防止网页把透明预览渲染成黑色) ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    
    /* 为预览图区域注入棋盘格背景，一眼识别透明底 */
    .stImage > img { 
        border-radius: 4px; 
        object-fit: contain; 
        background-image:决 color-mix(in srgb, transparent, #fff) !important;
        background-color: #ffffff;
        background-image: linear-gradient(45deg, #efefef 25%, transparent 25%, transparent 75%, #efefef 75%, #efefef), 
                          linear-gradient(45deg, #efefef 25%, transparent 25%, transparent 75%, #efefef 75%, #efefef) !important;
        background-size: 16px 16px !important;
        background-position: 0 0, 8px 8px !important;
    }
    .stDownloadButton, .stButton { margin-bottom: -10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心引擎 (完美维持 Alpha 透明通道) ---
def process_engine(img_input, config, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)):
            img = Image.open(io.BytesIO(img_input if isinstance(img_input, bytes) else img_input.getvalue()))
        elif hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue()))
        else:
            img = img_input

        # 检查原图是否自带透明通道 (RGBA 或 P 模式带透明度)
        has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
        img = img.convert("RGBA")
            
        target_w, target_h = config['size']
        
        # 判定最终是否需要保留透明底：用户显式选了透明，或者原图是透明且用户没开模糊/特定底色
        is_transparent_out = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 边界羽化融合 (只有不导出透明底时才做羽化，防止破坏透明边缘)
            if config['bg_mode'] in ["深度高斯模糊", "提取原色"] and not is_transparent_out:
                mask = Image.new("L", new_size, 255)
                draw = ImageDraw.Draw(mask)
                draw.rectangle([0, 0, new_size[0], new_size[1]], outline=0, width=2)
                mask = mask.filter(ImageFilter.GaussianBlur(radius=3)) 
                img_resized.putalpha(mask)

            # 根据配置生成画布
            if is_transparent_out:
                # 严格创建完全透明的纯净清澈底色画布
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
                # 提取原色
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            # 使用 alpha_composite 完美贴合覆盖，保留全部源半透明度
            bg.alpha_composite(img_resized, ((target_w - img_resized.size[0]) // 2, (target_h - img_resized.size[1]) // 2))
            res_img = bg

        # 调节亮度与锐度
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        
        # 【全流程透明底保护逻辑】
        if is_transparent_out:
            # 只要是透明底输出，100% 锁死 PNG 格式，不转 RGB 
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            # 普通实体颜色底，转 RGB 存成小体积的高保真 JPG 
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
    st.subheader("📁 导入中心")
    raw_uploads = st.file_uploader("支持拖入文件夹、ZIP包或多选图片", type=['jpg','jpeg','png','pdf','zip'], accept_multiple_files=True)
    
    processed_list = []
    zip_prefix = ""

    if raw_uploads:
        zip_files = [f for f in raw_uploads if f.name.lower().endswith('.zip')]
        if zip_files:
            zip_prefix = os.path.splitext(zip_files[0].name)[0]
            with zipfile.ZipFile(zip_files[0]) as z:
                for filename in z.namelist():
                    if filename.lower().endswith(('.png', '.jpg', '.jpeg')) and not filename.startswith('__MACOSX'):
                        with z.open(filename) as img_f:
                            processed_list.append({"name": os.path.basename(filename), "content": img_f.read()})
        else:
            zip_prefix = datetime.now().strftime("%m%d")
            for f in raw_uploads:
                processed_list.append({"name": f.name, "content": f.getvalue()})

    with st.container():
        with st.expander("🛠️ 规格设置", expanded=True):
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

        with st.expander("🎨 视觉设置", expanded=False):
            bg_m = st.selectbox("背景模式", ["特定颜色", "深度高斯模糊", "提取原色"], key=f"bgm_{st.session_state.settings_key}")
            p_color = "白色"
            if bg_m == "特定颜色":
                p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"], key=f"pcol_{st.session_state.settings_key}")
            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"brad_{st.session_state.settings_key}")
            flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"], key=f"flt_{st.session_state.settings_key}")
            br = st.slider("亮度", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化", 1.0, 4.0, 1.5, key=f"sh_{st.session_state.settings_key}")

    st.write("---")
    if st.button("🔄 重置所有设置", use_container_width=True):
        reset_all_settings()

with right_col:
    st.subheader("🔍 实时预览与导出")
    if processed_list:
        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'scale_mode': scale_mode}
        
        final_outputs = []
        with st.spinner("🚀 极速转码中..."):
            with ThreadPoolExecutor() as executor:
                futures = [executor.submit(process_engine, item["content"], conf, is_preview=False) for item in processed_list]
                final_outputs = [f.result() for f in futures]
        
        # 预览展现区域（此时透明图背部将呈现灰白棋盘格，不会再是一团死黑）
        with st.container(height=450):
            cols = st.columns(3)
            for idx, item in enumerate(processed_list):
                with cols[idx % 3]:
                    p_bytes, _ = final_outputs[idx]
                    if p_bytes: 
                        st.image(p_bytes, use_container_width=True, caption=item["name"])

        st.write("---")

        # 统一打包/单选秒开下载
        if len(processed_list) == 1:
            data, ext = final_outputs[0]
            if data:
                orig_name = os.path.splitext(processed_list[0]["name"])[0]
                st.download_button(f"🚀 下载处理后的图片: {processed_list[0]['name']}", data=data, file_name=f"{orig_name}.{ext.lower()}", type="primary", use_container_width=True)
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
                label=f"🚀 立即打包下载 ({len(processed_list)}张)", 
                data=zip_buf.getvalue(), 
                file_name=final_zip_name, 
                type="primary", 
                use_container_width=True
            )
    else:
        st.info("💡 请在左侧上传区域开始工作。")
