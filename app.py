import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
import os
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 初始化状态
if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0
if 'settings_key' not in st.session_state:
    st.session_state.settings_key = 0

# 清空函数
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
    .stImage > img { object-fit: contain; }
    /* 优化按钮间距 */
    .stDownloadButton, .stButton { margin-bottom: -10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心引擎 (保持之前所有优化逻辑) ---
def process_engine(img_input, config, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        target_w, target_h = config['size']
        
        if config.get('scale_mode') == "居中裁剪铺满 (大图感)":
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            # 保持 100% 贴边的等比铺满逻辑
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            
            if config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w//4, target_h//4))
                bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius']))
                bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
                bg = Image.new("RGBA", (target_w, target_h), color_map.get(config['pure_color'], (255,255,255,255)))
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
            # 体积控制逻辑
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
    except:
        return None, "Error"

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    # 使用 settings_key 实现设置重置
    with st.container():
        with st.expander("🛠️ 规格设置", expanded=True):
            res_map = {
                "请选择...": "none",
                "聚合标准 (1920*1080)": "1920*1080", 
                "Kiosk/Emenu标准 (5:3)": "1000*600", 
                "海报标准 (1:1)": "1200*1200",
                "自定义尺寸": "custom"
            }
            res_label = st.selectbox("比例预设", list(res_map.keys()), key=f"res_{st.session_state.settings_key}")
            
            # 自动关联逻辑：只要不是空白且不是自定义，默认500KB
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
            kb = 0
            if vol_opt == "自定义":
                c1, c2 = st.columns([2, 1])
                with c1: val = st.number_input("数值", 1, 10240, 500, key=f"vval_{st.session_state.settings_key}")
                with c2: unit = st.selectbox("单位", ["KB", "MB"], key=f"vunit_{st.session_state.settings_key}")
                kb = val if unit == "KB" else val * 1024
            else:
                kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
                
            scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0, key=f"sm_{st.session_state.settings_key}")

        with st.expander("🎨 视觉设置", expanded=False):
            bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"], key=f"bgm_{st.session_state.settings_key}")
            p_color = st.selectbox("底色", ["白色", "黑色", "灰色", "透明"], key=f"pcol_{st.session_state.settings_key}")
            b_radius = st.slider("模糊强度", 0, 200, 70, key=f"brad_{st.session_state.settings_key}")
            flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"], key=f"flt_{st.session_state.settings_key}")
            br = st.slider("亮度", 0.5, 1.5, 1.0, key=f"br_{st.session_state.settings_key}")
            sh = st.slider("锐化", 1.0, 4.0, 1.5, key=f"sh_{st.session_state.settings_key}")

    st.write("---")
    if st.button("🔄 重置所有设置", use_container_width=True):
        reset_all_settings()

with right_col:
    st.subheader("🔍 实时预览区")
    if files:
        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'scale_mode': scale_mode}
        
        with st.container(height=500):
            cols = st.columns(3)
            for idx, f in enumerate(files):
                with cols[idx % 3]:
                    p_bytes, _ = process_engine(f, conf, is_preview=True)
                    if p_bytes: st.image(p_bytes, use_container_width=True, caption=f.name)

        st.write("---")
        
        # 将清空列表移至右侧下载上方
        if st.button("🗑️ 一键清空预览列表", use_container_width=True):
            reset_all_files()
        
        # 动态命名准备
        date_str = datetime.now().strftime("%m%d")
        final_zip_name = f"{date_str}-{name_part}.zip"

        if len(files) == 1:
            data, ext = process_engine(files[0], conf)
            if data:
                orig_name = os.path.splitext(files[0].name)[0]
                st.download_button(f"🚀 下载: {files[0].name}", data=data, file_name=f"{orig_name}.{ext.lower()}", type="primary", use_container_width=True)
        else:
            if st.button(f"🚀 开始打包下载 ({len(files)}张)", type="primary", use_container_width=True):
                zip_buf = io.BytesIO()
                with st.status("正在处理...", expanded=True) as status:
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for i, f in enumerate(files):
                            data, ext = process_engine(f, conf)
                            if data:
                                orig_name = os.path.splitext(f.name)[0]
                                zf.writestr(f"{orig_name}.{ext.lower()}", data)
                    status.update(label="✅ 处理完成！", state="complete")
                st.download_button("📥 点击获取 ZIP 压缩包", data=zip_buf.getvalue(), file_name=final_zip_name, use_container_width=True)
    else:
        st.info("💡 请在左侧上传图片开始工作。")
