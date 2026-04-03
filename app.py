import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
import os
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# --- 2. 样式注入 ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    .block-container {padding-top: 2rem !important;}
    .stImage { border-radius: 4px; border: 1px solid #eee; background-color: #f9f9f9; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心引擎：深度优化留白逻辑 ---
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
            # --- 等比完整展示 (留背景) 深度优化 ---
            # 1. 计算原图比例，确保原图尽可能撑满目标区域，减少视觉缩水
            original_w, original_h = img.size
            ratio = min(target_w / original_w, target_h / original_h)
            # 稍微给一点点边距 (98% 填充)，避免贴边太死
            new_size = (int(original_w * ratio * 0.98), int(original_h * ratio * 0.98))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 2. 生成背景
            if config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w, target_h)).filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
                bg = Image.new("RGBA", (target_w, target_h), color_map.get(config['pure_color'], (255,255,255,255)))
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            
            # 3. 居中粘贴
            bg.alpha_composite(img, ((target_w - img.size[0]) // 2, (target_h - img.size[1]) // 2))
            res_img = bg

        # 增强与滤镜
        if config['filter'] != "原色":
            r, g, b, a = res_img.split()
            if config['filter'] == "暖色调": r = ImageEnhance.Brightness(r).enhance(1.1)
            elif config['filter'] == "清爽调": b = ImageEnhance.Brightness(b).enhance(1.1)
            res_img = Image.merge("RGBA", (r, g, b, a))
            
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
                final_rgb.save(out_io, format="JPEG", quality=90, optimize=True)
            return out_io.getvalue(), "JPEG"
    except:
        return None, "Error"

# --- 4. 界面布局 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    with st.expander("🛠️ 规格设置", expanded=True):
        res_map = {"聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "自定义": "custom", "海报标准 (1:1)": "1200*1200"}
        res_label = st.selectbox("比例预设", list(res_map.keys()))
        tw, th = (st.number_input("宽", 100, 4000, 1920), st.number_input("高", 100, 4000, 1080)) if res_label == "自定义" else map(int, res_map[res_label].split('*'))
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
        kb = 0
        if vol_opt == "自定义":
            c1, c2 = st.columns([2, 1])
            with c1: val = st.number_input("数值", 1, 10240, 500)
            with c2: unit = st.selectbox("单位", ["KB", "MB"])
            kb = val if unit == "KB" else val * 1024
        else: kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)

        scale_mode = st.radio("画面填充模式", ["等比完整展示 (留背景)", "居中裁剪铺满 (大图感)"], index=0)

    with st.expander("🎨 视觉设置", expanded=False):
        bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = st.selectbox("底色", ["白色", "黑色", "灰色", "透明"]) if bg_m == "特定颜色" else "白色"
        b_radius = st.slider("模糊强度", 10, 100, 40)
        flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"])
        br, sh = st.slider("亮度", 0.5, 1.5, 1.0), st.slider("锐化", 1.0, 4.0, 1.5)

with right_col:
    st.subheader("🔍 实时预览区")
    if files:
        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'scale_mode': scale_mode}
        
        with st.container(height=500):
            cols = st.columns(3)
            for idx, f in enumerate(files):
                with cols[idx % 3]:
                    p_bytes, _ = process_engine(f, conf, is_preview=True)
                    if p_bytes: st.image(p_bytes, use_container_width=True)

        st.write("---")
        if len(files) == 1:
            data, ext = process_engine(files[0], conf)
            if data:
                st.download_button("📥 下载处理后的图片", data=data, file_name=f"Result.{ext.lower()}", mime=f"image/{ext.lower()}", type="primary", use_container_width=True)
        else:
            if st.button(f"🚀 开始打包下载 ({len(files)}张)", type="primary", use_container_width=True):
                zip_buf = io.BytesIO()
                with st.status("正在处理...", expanded=True) as status:
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for i, f in enumerate(files):
                            data, ext = process_engine(f, conf)
                            if data: zf.writestr(f"{os.path.splitext(f.name)[0]}.{ext.lower()}", data)
                    status.update(label="✅ 处理完成！", state="complete")
                st.download_button("📥 点击获取 ZIP", data=zip_buf.getvalue(), file_name="Batch.zip", use_container_width=True)
