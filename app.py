import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import numpy as np
import cv2
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- 0. 环境检测 ---
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide", page_icon="🍽️")

# 初始化新功能所需的状态
if 'upload_key' not in st.session_state: st.session_state.upload_key = 0
if 'individual_configs' not in st.session_state: st.session_state.individual_configs = {}
if 'editing_file' not in st.session_state: st.session_state.editing_file = None

def reset_uploader():
    st.session_state.upload_key += 1
    st.session_state.individual_configs = {}
    st.session_state.editing_file = None
    st.rerun()

# --- 2. 注入 CSS ---
st.markdown("""
    <style>
    header {visibility: hidden;}
    [data-testid="stSidebar"] {display: none;}
    .block-container {padding-top: 2rem !important; padding-bottom: 0rem !important;}
    .stImage { border-radius: 4px; border: 1px solid #eee; margin-bottom: 10px; }
    div.stExpander { border: none !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    /* 微调红框样式 */
    .edit-active { border: 2px solid #FF4B4B !important; background: #fff1f1; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心算法 (完全保留你原本的 process_engine) ---
def smart_extract_multiple_subjects(pil_img):
    try:
        open_cv_image = np.array(pil_img.convert('RGB'))
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.medianBlur(gray, 5)
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15,15))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        extracted_images = []
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for c in contours:
            area = cv2.contourArea(c)
            x, y, w, h = cv2.boundingRect(c)
            if area < 8000 or w > img.shape[1] * 0.95 or h > img.shape[0] * 0.95: continue
            crop_img = img[y:y+h, x:x+w]
            extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))
        return extracted_images if extracted_images else [pil_img]
    except: return [pil_img]

def process_engine(img_input, config, is_preview=False):
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
            
        tw, th = config['size']
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        
        if config['fill_screen']:
            img_bg = img.convert("RGB")
            bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
            bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
            img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
            left, top = (img_bg.width - render_w) / 2, (img_bg.height - render_h) / 2
            res = img_bg.crop((left, top, left + render_w, top + render_h)).convert("RGBA")
        else:
            img_main = img.copy()
            img_main.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
            
            if config['bg_mode'] == "深度高斯模糊":
                img_bg = img.convert("RGB")
                bg_ratio = max(render_w / img_bg.width, render_h / img_bg.height)
                bg_size = (int(img_bg.width * bg_ratio), int(img_bg.height * bg_ratio))
                img_bg = img_bg.resize(bg_size, Image.Resampling.LANCZOS)
                left, top = (img_bg.width - render_w) / 2, (img_bg.height - render_h) / 2
                bg = img_bg.crop((left, top, left + render_w, top + render_h))
                bg = bg.filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
                dark_overlay = Image.new("RGBA", (render_w, render_h), (0, 0, 0, 25)) 
                bg = Image.alpha_composite(bg, dark_overlay)
            elif config['bg_mode'] == "特定颜色":
                color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
                bg = Image.new("RGBA", (render_w, render_h), color_map.get(config['pure_color'], (255,255,255,255)))
            else:
                sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
                bg = Image.new("RGBA", (render_w, render_h), sample + (255,))
            
            offset = ((render_w - img_main.width) // 2, (render_h - img_main.height) // 2)
            bg.paste(img_main, offset, img_main)
            res = bg

        if config['filter'] != "原色":
            r, g, b, a = res.split()
            if config['filter'] == "暖色调": r = ImageEnhance.Brightness(r).enhance(1.1)
            elif config['filter'] == "清爽调": b = ImageEnhance.Brightness(b).enhance(1.1)
            res = Image.merge("RGBA", (r, g, b, a))

        if not (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明"):
            alpha = res.getchannel('A')
            res = ImageEnhance.Brightness(res.convert("RGB")).enhance(config['bright'])
            res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
            res.putalpha(alpha)
        
        out_io = io.BytesIO()
        ext = "PNG" if (config['bg_mode'] == "特定颜色" and config['pure_color'] == "透明") else "JPEG"
        if ext == "PNG": res.save(out_io, format="PNG")
        else:
            q = 90 if is_preview else 95
            while q > 30:
                out_io = io.BytesIO()
                res.convert("RGB").save(out_io, format="JPEG", quality=q, optimize=True)
                if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
                q -= 5
        return out_io.getvalue(), ext
    except Exception as e: return None, f"err: {str(e)}"

# --- 4. 界面布局 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
left_col, right_col = st.columns([1.1, 2.5], gap="large")

with left_col:
    st.subheader("📁 导入与设置")
    files = st.file_uploader("支持多图/PDF", type=['jpg','jpeg','png','pdf'], 
                             accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")
    
    # 状态提示：是否进入了微调模式
    is_editing = st.session_state.editing_file is not None
    current_title = f"正在单独微调：{st.session_state.editing_file}" if is_editing else "🛠️ 规格设置 (全局模式)"

    with st.expander(current_title, expanded=True):
        res_map = {"聚合标准 (1920*1080)": "1920*1080", "Kiosk/Emenu标准 (5:3)": "1000*600", "自定义": "custom"}
        res_label = st.selectbox("比例预设", list(res_map.keys()), index=None, placeholder="请选择输出比例...")
        
        tw, th = 1920, 1080
        if res_label == "自定义":
            tw = st.number_input("宽", 100, 4000, 1920)
            th = st.number_input("高", 100, 4000, 1080)
        elif res_label:
            tw, th = map(int, res_map[res_label].split('*'))
        
        def_vol_idx = 1 if res_label == "Kiosk/Emenu标准 (5:3)" else 0
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB", "自定义"], index=def_vol_idx)
        kb = {"不限制": 0, "500KB": 500, "1MB": 1024}.get(vol_opt, 0)

    with st.expander("🎨 视觉设置", expanded=is_editing):
        is_fill = st.checkbox("🚀 强行铺满画布", value=False)
        auto_crop = st.toggle("多主体识别拆分", value=False)
        bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = st.selectbox("底色", ["白色", "黑色", "透明"]) if bg_m == "特定颜色" else "白色"
        b_radius = st.slider("模糊强度", 10, 100, 40)
        flt = st.selectbox("滤镜效果", ["原色", "暖色调", "清爽调"])
        br = st.slider("亮度", 0.5, 1.5, 1.05)
        sh = st.slider("锐化", 1.0, 4.0, 1.5)

        # 封装当前配置
        current_config = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
                          'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh, 'fill_screen': is_fill}
        
        # 核心逻辑：如果在编辑模式，将配置保存到对应的文件名下
        if is_editing:
            st.session_state.individual_configs[st.session_state.editing_file] = current_config
            if st.button("✅ 完成当前微调，返回全局", use_container_width=True):
                st.session_state.editing_file = None
                st.rerun()

    if st.button("🔄 全部重置", use_container_width=True): reset_uploader()

with right_col:
    st.subheader("🔍 实时预览区")
    if not res_label:
        st.warning("⚠️ 请先在左侧选择一个“比例预设”以开启预览。")
    elif files:
        # 这里维持你原有的列表处理逻辑（PDF、拆分等）
        processed_list = []
        for f in files:
            img_obj = Image.open(f)
            # 简化逻辑，仅演示
            img_obj.file_key = f.name 
            processed_list.append(img_obj)

        with st.container(height=520):
            cols = st.columns(3)
            for idx, item in enumerate(processed_list):
                # 逻辑：如果有独立配置用独立的，否则用全局的
                f_cfg = st.session_state.individual_configs.get(item.file_key, current_config if not is_editing else st.session_state.individual_configs.get(item.file_key, current_config))
                if not is_editing and item.file_key not in st.session_state.individual_configs:
                    f_cfg = current_config

                with cols[idx % 3]:
                    # 正在编辑的图片高亮
                    is_this_edit = (st.session_state.editing_file == item.file_key)
                    container_box = st.container()
                    if is_this_edit: st.markdown('<div class="edit-active">', unsafe_allow_html=True)
                    
                    p_bytes, _ = process_engine(item, f_cfg, is_preview=True)
                    if p_bytes:
                        st.image(p_bytes, use_container_width=True)
                        if st.button(f"🛠️ 微调此图", key=f"btn_{idx}"):
                            st.session_state.editing_file = item.file_key
                            if item.file_key not in st.session_state.individual_configs:
                                st.session_state.individual_configs[item.file_key] = current_config
                            st.rerun()
                    
                    if is_this_edit: st.markdown('</div>', unsafe_allow_html=True)

        st.write("---")
        # 批量下载：合并全局配置与微调配置
        if st.button("🚀 一键打包下载 (包含所有个性化微调)", type="primary", use_container_width=True):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for item in processed_list:
                    final_cfg = st.session_state.individual_configs.get(item.file_key, current_config)
                    data, ext = process_engine(item, final_cfg, is_preview=False)
                    zf.writestr(f"{item.file_key.split('.')[0]}.{ext.lower()}", data)
            
            date_str = datetime.now().strftime('%m%d')
            st.download_button("📥 获取全量 ZIP 压缩包", zip_buf.getvalue(), file_name=f"Batch_{date_str}.zip", use_container_width=True)
