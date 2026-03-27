import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 页面基本配置 ---
st.set_page_config(page_title="餐厅菜品智能处理站", layout="wide", page_icon="🍳")

st.title("👨‍🍳 餐厅菜品无水印自动美化系统")
st.caption("已移除自动旋转，保留原始朝向与原始文件名。下载纯净图片，绝无水印。")

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("1. 输出尺寸预设")
    size_mode = st.radio("选择分辨率", ["1920*1080 (HD)", "1000*600 (Web)", "自定义"])
    if size_mode == "1920*1080 (HD)": tw, th = 1920, 1080
    elif size_mode == "1000*600 (Web)": tw, th = 1000, 600
    else:
        tw = st.number_input("宽 (px)", value=1920, step=10)
        th = st.number_input("高 (px)", value=1080, step=10)

    st.header("2. 体积控制")
    max_kb_limit = st.selectbox("文件大小限制", ["500KB", "1MB", "2MB", "不限制"])
    
    st.header("3. 效果增强")
    sharp_level = st.slider("清晰度增强 (去糊)", 1.0, 3.0, 1.6, step=0.1)
    color_level = st.slider("色彩鲜艳度 (提色)", 1.0, 2.0, 1.3, step=0.1)

# --- 核心图像算法 ---
def process_food_image_optimized(bytes_data):
    # 1. 基础读取
    img_arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if img is None: return None
    
    # [已移除] 自动朝向纠正逻辑，保留原始图片方向
    h, w = img.shape[:2]

    # 2. 创建高斯模糊背景
    bg_blur = cv2.resize(img, (tw, th), interpolation=cv2.INTER_LINEAR)
    bg_pil = Image.fromarray(cv2.cvtColor(bg_blur, cv2.COLOR_BGR2RGB))
    bg_pil = bg_pil.filter(ImageFilter.GaussianBlur(radius=70))

    # 3. 处理主体菜品 (居中缩放)
    target_h = int(th * 0.88)
    scale = target_h / h
    target_w = int(w * scale)
    
    if target_w > tw * 0.92:
        scale = (tw * 0.92) / w
        target_w = int(tw * 0.92)
        target_h = int(h * scale)
        
    img_rsz = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)
    main_pil = Image.fromarray(cv2.cvtColor(img_rsz, cv2.COLOR_BGR2RGB))

    # 4. 效果增强
    main_pil = ImageEnhance.Color(main_pil).enhance(color_level)
    main_pil = ImageEnhance.Sharpness(main_pil).enhance(sharp_level)
    main_pil = ImageEnhance.Contrast(main_pil).enhance(1.1)

    # 5. 合成
    offset = ((tw - target_w) // 2, (th - target_h) // 2)
    bg_pil.paste(main_pil, offset)

    # 6. 体积压缩控制
    limit_bytes = 0
    if max_kb_limit == "500KB": limit_bytes = 500 * 1024
    elif max_kb_limit == "1MB": limit_bytes = 1024 * 1024
    elif max_kb_limit == "2MB": limit_bytes = 2048 * 1024
    
    q = 98
    out_buf = io.BytesIO()
    while q > 15:
        out_buf = io.BytesIO()
        bg_pil.save(out_buf, format="JPEG", quality=q, optimize=True)
        if limit_bytes == 0 or out_buf.tell() < limit_bytes:
            break
        q -= 4
        
    return out_buf.getvalue()

# --- 网页交互逻辑 ---
uploaded_files = st.file_uploader(
    "👉 拖入菜品图片进行处理", 
    accept_multiple_files=True, 
    type=['jpg','png','jpeg']
)

if uploaded_files:
    processed_list = []
    st.info(f"正在处理 {len(uploaded_files)} 张图片...")
    
    bar = st.progress(0)
    for i, f in enumerate(uploaded_files):
        # 传入原始文件名
        original_name = f.name
        # 如果原图是PNG，我们处理后默认转为质量更好的JPG，但你可以保留后缀
        if not original_name.lower().endswith('.jpg') and not original_name.lower().endswith('.jpeg'):
            save_name = original_name.rsplit('.', 1)[0] + ".jpg"
        else:
            save_name = original_name

        result_data = process_food_image_optimized(f.read())
        
        if result_data:
            processed_list.append((save_name, result_data))
        
        bar.progress((i + 1) / len(uploaded_files))

    if processed_list:
        st.success("✅ 处理完成！")
        
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, data in processed_list:
                zf.writestr(name, data)
        
        st.download_button(
            label="📦 一键打包下载 (保留原始文件名)",
            data=zip_io.getvalue(),
            file_name=f"restaurant_fixed_{int(time.time())}.zip",
            mime="application/zip",
            use_container_width=True
        )
        
        st.subheader("处理结果预览")
        cols = st.columns(3)
        for i, (name, data) in enumerate(processed_list[:3]):
            cols[i].image(data, caption=name, use_container_width=True)
