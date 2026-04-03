import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
import os
from datetime import datetime

# --- 1. 页面配置 ---
st.set_title_config = st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 初始化上传状态索引
if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

# 清空逻辑：通过改变 file_uploader 的 key 来强制重置
def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# --- 2. 样式注入 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage > img { object-fit: contain; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心引擎 ---
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
            # 修复后的等比铺满逻辑
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            new_size = (int(original_w * ratio), int(original_h * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 背景生成
            if config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w, target_h)).filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
                bg = Image.new("RGBA", (target_w, target_h), color_map.get(config['pure_color'], (255,255,255,255)))
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            bg.alpha_composite(img, ((target_w - img.size[0]) // 2, (target_h - img.size[1]) // 2))
            res_img = bg

        # 图像增强
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])

        out_io = io.BytesIO()
        if config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明":
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            final_rgb = res_img.convert("RGB")
            final_rgb.save(out_io, format="JPEG", quality=95, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

# --- 4. 界面布局 ---
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    # 使用动态 key 绑定上传器
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    with st.expander("🛠️ 规格设置", expanded=True):
        res_map = {"聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "自定义尺寸": "custom", "海报标准 (1:1)": "1200*1200"}
        res_label = st.selectbox("比例预设", list(res_map.keys()))
        if res_label == "自定义尺寸":
            tw = st.number_input("宽", 100, 4000, 1920)
            th = st.number_input("高", 100, 4000, 1080)
        else:
            tw, th = map(int, res_map[res_label].split('*'))
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
        kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)
        scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0)

    with st.expander("🎨 视觉设置", expanded=False):
        bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = st.selectbox("底色", ["白色", "黑色", "灰色", "透明"])
        b_radius = st.slider("模糊强度", 10, 100, 40)
        flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"])
        br, sh = st.slider("亮度", 0.5, 1.5, 1.0), st.slider("锐化", 1.0, 4.0, 1.5)

    # 【修复】找回一键清空功能
    st.write("---")
    if st.button("🗑️ 一键清空列表", use_container_width=True):
        reset_uploader()

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
        if len(files) == 1:
            data, ext = process_engine(files[0], conf)
            if data:
                orig_name = os.path.splitext(files[0].name)[0]
                st.download_button(f"📥 下载: {files[0].name}", data=data, file_name=f"{orig_name}.{ext.lower()}", type="primary", use_container_width=True)
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
                st.download_button("📥 点击获取 ZIP 压缩包", data=zip_buf.getvalue(), file_name=f"Batch_{datetime.now().strftime('%H%M')}.zip", use_container_width=True)
