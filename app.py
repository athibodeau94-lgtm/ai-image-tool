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

if 'upload_key' not in st.session_state:
    st.session_state.upload_key = 0

def reset_uploader():
    st.session_state.upload_key += 1
    st.rerun()

# 界面样式优化
st.markdown("""
    <style>
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.5rem !important; }
    .stImage { border-radius: 8px; border: 1px solid #f0f2f6; }
    .stButton button { width: 100%; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心算法 ---
def smart_extract_multiple_subjects(pil_img):
    """利用OpenCV识别并拆分多个主体"""
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
            # 过滤过小或过大的噪点（需占原图一定比例）
            if area < 8000 or w > img.shape[1] * 0.95 or h > img.shape[0] * 0.95: continue
            if (w/float(h)) > 4.0 or (w/float(h)) < 0.25: continue
            crop_img = img[y:y+h, x:x+w]
            extracted_images.append(Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)))
        return extracted_images if extracted_images else [pil_img]
    except Exception:
        return [pil_img]

# --- 3. 处理引擎 ---
def process_engine(img_input, config, is_preview=False):
    """图像核心处理逻辑，增加异常保护"""
    try:
        if isinstance(img_input, (bytes, io.BytesIO)) or hasattr(img_input, 'getvalue'):
            img = Image.open(io.BytesIO(img_input.getvalue() if hasattr(img_input, 'getvalue') else img_input)).convert("RGBA")
        else:
            img = img_input.convert("RGBA")
        
        tw, th = config['size']
        # 预览时降低分辨率以节省资源
        render_w, render_h = (tw // 2, th // 2) if is_preview else (tw, th)
        
        # 1. 调整主体大小（保持比例）
        img.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
        
        # 2. 生成背景
        if config['bg_mode'] == "深度高斯模糊":
            bg = img.convert("RGB").resize((render_w, render_h)).filter(ImageFilter.GaussianBlur(config['blur_radius'])).convert("RGBA")
        elif config['bg_mode'] == "特定颜色":
            color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255), "透明": (0,0,0,0)}
            bg = Image.new("RGBA", (render_w, render_h), color_map.get(config['pure_color'], (255,255,255,255)))
        else:
            # 自动提取中心像素色
            sample = img.convert("RGB").getpixel((img.size[0]//2, img.size[1]//2))
            bg = Image.new("RGBA", (render_w, render_h), sample + (255,))
        
        # 3. 居中叠加主体
        offset = ((render_w - img.size[0]) // 2, (render_h - img.size[1]) // 2)
        bg.paste(img, offset, img)
        
        # 4. 后期滤镜
        res = bg.convert("RGB")
        res = ImageEnhance.Brightness(res).enhance(config['bright'])
        res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
        
        if config['filter'] == "暖色调":
            r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.1); res = Image.merge("RGB", (r, g, b))
        elif config['filter'] == "清爽调":
            r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.1); res = Image.merge("RGB", (r, g, b))
        
        # 5. 导出压缩
        out_io = io.BytesIO()
        ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
        if ext == "JPEG":
            q = 90 if is_preview else 95
            while q > 30:
                out_io = io.BytesIO()
                res.save(out_io, format="JPEG", quality=q, optimize=True)
                if out_io.tell() <= config['limit_kb'] * 1024 or is_preview or config['limit_kb'] == 0: break
                q -= 5
        else:
            res.save(out_io, format="PNG")
        
        return out_io.getvalue(), ext
    except Exception as e:
        return None, str(e)

# --- 4. 侧边栏交互 ---
with st.sidebar:
    st.header("⚙️ 参数设置")
    st.button("🗑️ 清空全部上传", on_click=reset_uploader)
    
    st.subheader("输出规格")
    # 增加主流平台预设
    res_map = {
        "美团标准 (4:3)": "1600*1200",
        "饿了么标准 (1:1)": "1000*1000",
        "小红书封面 (3:4)": "900*1200",
        "高清大图 (16:9)": "1920*1080",
        "自定义": "custom"
    }
    res_label = st.selectbox("平台分辨率预设", list(res_map.keys()))
    if res_label == "自定义":
        tw = st.number_input("宽度", 100, 4000, 1920)
        th = st.number_input("高度", 100, 4000, 1080)
    else:
        tw, th = map(int, res_map[res_label].split('*'))
    
    vol_opt = st.selectbox("单张体积限制", ["不限制", "500KB", "1MB", "自定义"])
    kb = 0
    if vol_opt == "自定义": kb = st.number_input("限制(KB)", 10, 5120, 500)
    elif vol_opt == "500KB": kb = 500
    elif vol_opt == "1MB": kb = 1024
    
    st.divider()
    st.subheader("智能处理")
    auto_crop = st.toggle("多主体自动识别拆分", value=True, help="一张图里有多个菜品时自动切割")
    bg_m = st.selectbox("背景填充样式", ["深度高斯模糊", "特定颜色", "提取中心色"])
    
    p_color, b_radius = "白色", 40
    if bg_m == "特定颜色": 
        p_color = st.selectbox("底色", ["白色", "黑色", "灰色", "透明"])
    elif bg_m == "深度高斯模糊": 
        b_radius = st.slider("模糊强度", 10, 100, 40)
    
    st.divider()
    st.subheader("效果精修")
    flt = st.selectbox("风格滤镜", ["原色", "暖色调", "清爽调"])
    br = st.slider("亮度调节", 0.5, 1.5, 1.05)
    sh = st.slider("锐化程度", 1.0, 4.0, 1.5)

# --- 5. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 2.0 Pro")
st.caption("外卖/电商菜品图批量处理工具 - 支持多线程并行加速")

files = st.file_uploader("点击或拖拽上传图片或 PDF", type=['jpg','jpeg','png','pdf'], 
                         accept_multiple_files=True, key=f"up_{st.session_state.upload_key}")

if files:
    final_list = []
    with st.spinner("正在解析文件..."):
        for f in files:
            try:
                if f.name.lower().endswith('.pdf') and PDF_SUPPORT:
                    pages = convert_from_bytes(f.read(), dpi=150)
                    for i, p in enumerate(pages):
                        if auto_crop:
                            for idx, dish in enumerate(smart_extract_multiple_subjects(p)):
                                dish.filename = f"{f.name}_P{i+1}_{idx+1}.jpg"
                                final_list.append(dish)
                        else:
                            p.filename = f"{f.name}_P{i+1}.jpg"
                            final_list.append(p)
                else:
                    if auto_crop:
                        # 对上传的图片也进行主体检测
                        img_obj = Image.open(f)
                        extracted = smart_extract_multiple_subjects(img_obj)
                        for idx, dish in enumerate(extracted):
                            dish.filename = f"{f.name.split('.')[0]}_{idx+1}.jpg"
                            final_list.append(dish)
                    else:
                        final_list.append(f)
            except Exception as e:
                st.error(f"无法读取文件 {f.name}: {e}")

    conf = {'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 'pure_color': p_color, 
            'blur_radius': b_radius, 'filter': flt, 'bright': br, 'sharp': sh}

    st.subheader(f"待导出预览 ({len(final_list)} 张)")
    
    # 使用容器固定高度显示预览
    with st.container(height=500):
        cols = st.columns(4)
        for idx, item in enumerate(final_list):
            with cols[idx % 4]:
                p_bytes, ext_or_err = process_engine(item, conf, is_preview=True)
                if p_bytes:
                    st.image(p_bytes, use_container_width=True)
                else:
                    st.error("处理失败")

    # 底部导出按钮
    st.divider()
    if len(final_list) > 0:
        if st.button("🚀 并行生成并导出全部 (ZIP)", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            zip_buf = io.BytesIO()
            
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                # 使用多线程加速处理
                with ThreadPoolExecutor() as executor:
                    # 提交任务
                    futures = {executor.submit(process_engine, itm, conf): itm for itm in final_list}
                    
                    for i, future in enumerate(futures):
                        try:
                            data, ext = future.result()
                            if data:
                                itm = futures[future]
                                name = getattr(itm, 'filename', getattr(itm, 'name', f"img_{i}.jpg"))
                                zf.writestr(f"{name.split('.')[0]}.{ext.lower()}", data)
                        except Exception as e:
                            st.warning(f"跳过一张出错图片: {e}")
                        
                        # 更新进度条
                        progress = (i + 1) / len(final_list)
                        progress_bar.progress(progress)
                        status_text.text(f"已完成 {i+1}/{len(final_list)}")
            
            status_text.success("✨ 全部处理完成！")
            st.download_button(
                label="📥 立即下载压缩包",
                data=zip_buf.getvalue(),
                file_name=f"FoodBatch_{datetime.now().strftime('%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )
else:
    st.info("💡 提示：上传包含多个菜品的原图，开启“多主体识别”可自动切分为单张规范图。")
