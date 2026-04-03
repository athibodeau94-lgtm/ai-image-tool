import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
import os
import numpy as np
import cv2
from datetime import datetime

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

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
    [data-testid="stSidebar"] {display: none;}
    .block-container {padding-top: 2rem !important; padding-bottom: 0rem !important;}
    .stImage { border-radius: 4px; border: 1px solid #eee; margin-bottom: 10px; }
    div.stExpander { border: none !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心引擎：修复缩放逻辑与文件名处理 ---
def process_engine(img_input, config, is_preview=False):
    try:
        # 加载图片
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        target_w, target_h = config['size']
        if is_preview:
            # 预览时按比例缩小以提升速度
            target_w, target_h = target_w // 2, target_h // 2

        # 问题 3 修复：缩放模式逻辑
        if config.get('scale_mode') == "居中裁剪铺满":
            # 像图1一样铺满整个画布，多余部分裁掉
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            # 等比缩放（留白/背景）
            img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            # 生成背景底板
            if config['bg_mode'] == "深度高斯模糊":
                bg = img.convert("RGB").resize((target_w, target_h)).filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
                bg = Image.new("RGBA", (target_w, target_h), color_map.get(config['pure_color'], (255,255,255,255)))
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (target_w, target_h), sample + (255,))
            # 居中合成
            bg.alpha_composite(img, ((target_w - img.size[0]) // 2, (target_h - img.size[1]) // 2))
            res_img = bg

        # 增强处理
        if config['filter'] != "原色":
            r, g, b, a = res_img.split()
            if config['filter'] == "暖色调": r = ImageEnhance.Brightness(r).enhance(1.1)
            elif config['filter'] == "清爽调": b = ImageEnhance.Brightness(b).enhance(1.1)
            res_img = Image.merge("RGBA", (r, g, b, a))

        is_transparent = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        out_io = io.BytesIO()
        
        if is_transparent:
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            final_rgb = res_img.convert("RGB")
            final_rgb = ImageEnhance.Brightness(final_rgb).enhance(config['bright'])
            final_rgb = ImageEnhance.Sharpness(final_rgb).enhance(config['sharp'])
            # 质量压缩
            q = 90 if is_preview else 95
            while q > 30:
                out_io = io.BytesIO()
                final_rgb.save(out_io, format="JPEG", quality=q, optimize=True)
                if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
                q -= 5
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
        # 问题 3 修复：新增缩放模式开关
        scale_mode = st.radio("画面填充模式", ["居中裁剪铺满 (大图感)", "等比完整展示 (留背景)"], index=0)
        res_map = {"美团标准 (4:3)": "1200*900", "饿了么标准 (1:1)": "800*800", "小红书 (3:4)": "900*1200", "自定义": "custom"}
        res_label = st.selectbox("平台预设", list(res_map.keys()))
        tw, th = (st.number_input("宽", 100, 4000, 1200), st.number_input("高", 100, 4000, 900)) if res_label == "自定义" else map(int, res_map[res_label].split('*'))
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
        kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)

    with st.expander("🎨 视觉设置", expanded=False):
        auto_crop = st.toggle("多主体识别拆分", value=False)
        bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = st.selectbox("底色", ["白色", "黑色", "灰色", "透明"]) if bg_m == "特定颜色" else "白色"
        b_radius = st.slider("模糊强度", 10, 100, 40)
        flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"])
        br, sh = st.slider("亮度", 0.5, 1.5, 1.0), st.slider("锐化", 1.0, 4.0, 1.5)

    if st.button("🗑️ 清空列表", use_container_width=True): reset_uploader()

with right_col:
    st.subheader("🔍 实时预览区")
    if files:
        conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
                'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 
                'scale_mode': scale_mode.split(" ")[0]} # 提取关键字

        with st.container(height=500):
            cols = st.columns(3)
            for idx, f in enumerate(files):
                with cols[idx % 3]:
                    p_bytes, _ = process_engine(f, conf, is_preview=True)
                    if p_bytes: st.image(p_bytes, use_container_width=True)

        st.write("---")
        # 问题 1, 2, 4 修复：带进度条的打包逻辑
        if st.button(f"🚀 开始打包下载 ({len(files)}张)", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            success_count = 0
            
            with st.status("正在准备压缩包...", expanded=True) as status:
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for i, f in enumerate(files):
                        status.write(f"正在处理第 {i+1}/{len(files)} 张: {f.name}")
                        data, ext = process_engine(f, conf)
                        if data:
                            # 问题 2 修复：使用 os.path.splitext 保留完整长菜名
                            base_name = os.path.splitext(f.name)[0]
                            zf.writestr(f"{base_name}.{ext.lower()}", data)
                            success_count += 1
                
                # 问题 1 校验：确保数量一致
                if success_count == len(files):
                    status.update(label="✅ 全部处理完成！", state="complete")
                else:
                    status.update(label=f"⚠️ 处理完成，但有 {len(files)-success_count} 张失败", state="error")
            
            if success_count > 0:
                st.download_button(label="📥 点击获取 ZIP 压缩包", data=zip_buf.getvalue(), 
                                   file_name=f"Batch_{datetime.now().strftime('%H%M')}.zip", 
                                   mime="application/zip", use_container_width=True)
    else:
        st.info("💡 请在左侧上传图片开始工作。")
