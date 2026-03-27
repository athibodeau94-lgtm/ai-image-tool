import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 页面基本配置 ---
st.set_page_config(page_title="餐厅菜品智能处理站", layout="wide", page_icon="🍳")

# 标题与介绍
st.title("👨‍🍳 餐厅菜品无水印自动美化系统")
st.caption("针对菜品图优化：自动纠正朝向、去除丑陋黑边、增强画质、严格体积控制。下载纯净图片，绝无水印。")

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
    
    st.info("💡 提示：此版本使用高级模糊填充代替黑边，实现基础居中效果。若需‘凭空补全’被切碗，请在未来升级 AI API 版本。")

# --- 核心图像算法 (OpenCV + Pillow) ---
def process_food_image_pure(bytes_data):
    # 1. 基础读取
    img_arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if img is None: return None
    
    # 2. 自动朝向纠正 (核心逻辑：餐厅菜品通常需要横图呈现)
    h, w = img.shape[:2]
    # 如果高度大于宽度（竖图），自动顺时针旋转90度
    if h > w:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        h, w = img.shape[:2] # 更新旋转后的尺寸

    # 3. 创建“高级感”模糊背景（模仿图三，彻底解决丑陋黑边）
    # 先把原图拉伸到目标全屏尺寸，作为背景
    bg_blur = cv2.resize(img, (tw, th), interpolation=cv2.INTER_LINEAR)
    # 转换到 PIL 进行深度高斯模糊
    bg_pil = Image.fromarray(cv2.cvtColor(bg_blur, cv2.COLOR_BGR2RGB))
    bg_pil = bg_pil.filter(ImageFilter.GaussianBlur(radius=70)) # 强力模糊，营造氛围

    # 4. 处理主体菜品 (居中缩放与美化)
    # 让菜品占据目标高度的 88%，确保视觉大小一致
    target_h = int(th * 0.88)
    scale = target_h / h
    target_w = int(w * scale)
    
    # 如果缩放后宽度超标，重新按宽度缩放
    if target_w > tw * 0.92:
        scale = (tw * 0.92) / w
        target_w = int(tw * 0.92)
        target_h = int(h * scale)
        
    img_rsz = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_CUBIC)
    main_pil = Image.fromarray(cv2.cvtColor(img_rsz, cv2.COLOR_BGR2RGB))

    # 5. 菜品专属色彩与清晰度增强
    main_pil = ImageEnhance.Color(main_pil).enhance(color_level) # 提色
    main_pil = ImageEnhance.Sharpness(main_pil).enhance(sharp_level) # 去糊
    main_pil = ImageEnhance.Contrast(main_pil).enhance(1.1) # 微调对比度

    # 6. 合成：将纯净美化后的菜品贴在模糊背景中心
    offset = ((tw - target_w) // 2, (th - target_h) // 2)
    # 粘贴过程中不会产生任何水印
    bg_pil.paste(main_pil, offset)

    # 7. 严格体积递归压缩控制
    limit_bytes = 0
    if max_kb_limit == "500KB": limit_bytes = 500 * 1024
    elif max_kb_limit == "1MB": limit_bytes = 1024 * 1024
    elif max_kb_limit == "2MB": limit_bytes = 2048 * 1024
    
    q = 98 # 初始质量
    out_buf = io.BytesIO()
    
    # 递归下调质量，直到满足体积要求
    while q > 15:
        out_buf = io.BytesIO()
        # 保存为无水印、纯净的 JPEG
        bg_pil.save(out_buf, format="JPEG", quality=q, optimize=True)
        if limit_bytes == 0 or out_buf.tell() < limit_bytes:
            break
        q -= 4 # 质量步进下调
        
    return out_buf.getvalue(), q

# --- 网页交互逻辑 (Streamlit) ---
files = st.file_uploader(
    "👉 点击或直接拖拽整个菜品文件夹（图片）到这里", 
    accept_multiple_files=True, 
    type=['jpg','png','jpeg']
)

if files:
    processed_list = []
    st.info(f"正在准备批量处理 {len(files)} 张菜品图片，请稍候...")
    
    # 创建进度条
    bar = st.progress(0)
    
    for i, f in enumerate(files):
        # 处理图片得到纯净数据和最终质量
        result_data, final_q = process_food_image_pure(f.read())
        
        if result_data:
            processed_list.append((f"pure_fixed_{f.name.split('.')[0]}.jpg", result_data))
        
        # 更新进度
        bar.progress((i + 1) / len(files))

    if processed_list:
        st.success(f"✅ 处理完成！共生成 {len(processed_list)} 张无水印纯净图片。")
        
        # 批量打包
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, data in processed_list:
                zf.writestr(name, data)
        
        # 提供一个显眼的、一键下载的按钮
        st.download_button(
            label="📦 一键打包下载全部纯净图片 (Zip压缩包)",
            data=zip_io.getvalue(),
            file_name=f"restaurant_pure_fixed_{int(time.time())}.zip",
            mime="application/zip",
            use_container_width=True
        )
        
        # 预览功能 (为了展示无水印效果)
        st.subheader("处理结果预览 (前3张)")
        cols = st.columns(3)
        for i, (name, data) in enumerate(processed_list[:3]):
            # st.image 显示的图片直接来源于处理好的纯净数据
            cols[i].image(data, caption=f"{name} (无水印)", use_container_width=True)
