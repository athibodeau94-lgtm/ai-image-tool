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

# --- 3. 核心处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    try:
        # 1. 统一加载图片
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        target_w, target_h = config['size']
        if is_preview:
            # 预览时按比例缩小以提升界面性能，但不改变缩放逻辑
            target_w, target_h = target_w // 2, target_h // 2

        # 2. 核心修复：处理缩放模式
        if config.get('scale_mode') == "居中裁剪铺满 (大图感，推荐)":
            # 【重要】完全移除 thumbnail。直接使用 fit 方法，强行铺满画布
            res_img = ImageOps.fit(img, (target_w, target_h), Image.Resampling.LANCZOS)
        else:
            # 等比完整展示 (留背景) 
            # 只有在此模式下才允许图片缩小和背景填充
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

        # 3. 滤镜、亮度与锐化 (全程在 RGBA 下处理，确保预览/下载一致)
        if config['filter'] != "原色":
            r, g, b, a = res_img.split()
            if config['filter'] == "暖色调":
                r = ImageEnhance.Brightness(r).enhance(1.1)
            elif config['filter'] == "清爽调":
                b = ImageEnhance.Brightness(b).enhance(1.1)
            res_img = Image.merge("RGBA", (r, g, b, a))
            
        # 亮度与锐化
        br_enhancer = ImageEnhance.Brightness(res_img)
        res_img = br_enhancer.enhance(config['bright'])
        sh_enhancer = ImageEnhance.Sharpness(res_img)
        res_img = sh_enhancer.enhance(config['sharp'])

        # 4. 准备导出
        out_io = io.BytesIO()
        is_transparent = (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明")
        
        if is_transparent:
            # 预览和下载都保存为 PNG 以展示透明底
            res_img.save(out_io, format="PNG")
            return out_io.getvalue(), "PNG"
        else:
            # 预览和下载都转换为 RGB 后保存为 JPEG，确保体积控制
            final_rgb = res_img.convert("RGB")
            
            # 只有最终下载时才进行严格的体积压缩，预览时使用高速 JPEG
            q = 85 if is_preview else 95
            if not is_preview and config['limit_kb'] > 0:
                while q > 30:
                    out_io = io.BytesIO()
                    final_rgb.save(out_io, format="JPEG", quality=q, optimize=True)
                    if out_io.tell() <= config['limit_kb'] * 1024:
                        break
                    q -= 5
            else:
                final_rgb.save(out_io, format="JPEG", quality=q, optimize=True)
            
            return out_io.getvalue(), "JPEG"
            
    except Exception as e:
        return None, f"Error: {e}"

# --- 4. 界面布局 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    with st.expander("🛠️ 规格设置", expanded=True):
        # 恢复之前的规格设置逻辑
        res_map = {
            "聚合标准 (1920*1080)": "1920*1080",
            "Kiosk/Emenu标准 (5:3)": "1000*600",
            "自定义": "custom",
            "海报标准 (1:1)": "1200*1200",
            "小红书 (3:4)": "900*1200"
        }
        res_label = st.selectbox("比例预设", list(res_map.keys()))
        if res_label == "自定义":
            tw = st.number_input("宽", 100, 4000, 1920)
            th = st.number_input("高", 100, 4000, 1080)
        else:
            tw, th = map(int, res_map[res_label].split('*'))
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"])
        kb = 0
        if vol_opt == "自定义":
            c1, c2 = st.columns([2, 1])
            with c1: val = st.number_input("数值", 1, 10240, 500)
            with c2: unit = st.selectbox("单位", ["KB", "MB"])
            kb = val if unit == "KB" else val * 1024
        else: kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)

        # 【重点修复】填充模式优化：默认设为居中裁剪铺满，对齐图1效果
        scale_mode = st.radio("画面填充模式", ["居中裁剪铺满 (大图感，推荐)", "等比完整展示 (留背景)"], index=0)

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
                'scale_mode': scale_mode}

        # 核心修复：确保预览和下载使用完全相同的 conf 和逻辑
        with st.container(height=500):
            cols = st.columns(3)
            for idx, f in enumerate(files):
                with cols[idx % 3]:
                    # 调用 process_engine 生成 1:1 对应的预览图
                    p_bytes, p_ext = process_engine(f, conf, is_preview=True)
                    if p_bytes: 
                        st.image(p_bytes, caption=f.name, use_container_width=True)

        st.write("---")
        
        # 区分单张下载和批量打包
        if len(files) == 1:
            # 单图模式：直接调用同一引擎生成下载图
            with st.spinner("准备下载..."):
                data, ext = process_engine(files[0], conf, is_preview=False)
            if data:
                base_name = os.path.splitext(files[0].name)[0]
                st.download_button(
                    label=f"📥 下载处理后的图片 ({ext})",
                    data=data,
                    file_name=f"{base_name}_2.0Pro.{ext.lower()}",
                    mime=f"image/{ext.lower()}",
                    type="primary",
                    use_container_width=True
                )
        else:
            # 多图模式：批量打包逻辑
            if st.button(f"🚀 开始打包下载 ({len(files)}张)", type="primary", use_container_width=True):
                zip_buf = io.BytesIO()
                success_count = 0
                with st.status("正在准备压缩包...", expanded=True) as status:
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for i, f in enumerate(files):
                            status.write(f"正在处理: {f.name}")
                            data, ext = process_engine(f, conf, is_preview=False)
                            if data:
                                base_name = os.path.splitext(f.name)[0]
                                zf.writestr(f"{base_name}.{ext.lower()}", data)
                                success_count += 1
                    status.update(label=f"✅ 处理完成！(成功:{success_count}/{len(files)})", state="complete")
                
                if success_count > 0:
                    st.download_button(label="📥 点击获取 ZIP 压缩包", data=zip_buf.getvalue(), 
                                       file_name=f"Batch_{datetime.now().strftime('%H%M')}.zip", 
                                       mime="application/zip", use_container_width=True)
    else:
        st.info("💡 请在左侧上传图片开始工作。")
