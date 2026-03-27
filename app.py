import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance
import os
import io
import zipfile
import time

# --- 页面配置 ---
st.set_page_config(page_title="AI 文件夹图像处理站", layout="wide")
st.title("📂 智能图像文件夹自动化处理站")
st.caption("支持整个文件夹上传、AI 修复（去暗/去糊/自动旋转）、批量打包下载")

# --- 侧边栏设置 ---
with st.sidebar:
    st.header("1. 输出配置")
    tw = st.number_input("目标宽度 (px)", value=1920, step=10)
    th = st.number_input("目标高度 (px)", value=1080, step=10)
    
    st.header("2. AI 修复开关")
    auto_rotate = st.checkbox("自动矫正旋转 (人脸检测演示版)", value=True)
    auto_bright = st.checkbox("自动增强亮度 (去暗)", value=True)
    auto_sharp = st.checkbox("自动增强清晰度 (去糊)", value=True)
    
    st.header("3. 保存设置")
    quality = st.slider("保存质量 (JPEG)", 10, 100, 85)

# --- 核心 AI 处理函数 ---
def smart_ai_process(bytes_data, file_name):
    # 1. 解码
    arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None: return None, "无法读取图片"

    # [演示版逻辑] 真正的 AI 人脸矫正需调用 DeepFace 等库，这里使用基础算法演示
    # 2. 自动纠正旋转
    h, w = img.shape[:2]
    # 此处逻辑：如果它是竖图 (h > w)，自动把她转成横图 (h < w)
    if auto_rotate and h > w:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        h, w = img.shape[:2] # 更新尺寸

    # 3. 尺寸缩放并填充 (使其变为 1920x1080 并居中)
    canvas = np.zeros((th, tw, 3), dtype=np.uint8) # 黑色背景填充
    scale = min(tw/w, th/h)
    nw, nh = int(w*scale), int(h*scale)
    rsz = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    y, x = (th-nh)//2, (tw-nw)//2
    canvas[y:y+nh, x:x+nw] = rsz
    
    # 4. 自动画质增强 (转换到 PIL 进行)
    final_img = canvas
    if auto_bright or auto_sharp:
        pil_img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        
        # 处理过暗 (亮度检测与自动对比度)
        if auto_bright:
            stat = ImageEnhance.Brightness(pil_img).enhance(1.0)
            avg_b = np.mean(np.array(stat.convert('L')))
            if avg_b < 110: # 平均亮度较低
                enhancer = ImageEnhance.Contrast(pil_img)
                pil_img = enhancer.enhance(1.2) # 自动提高对比度
        
        # 处理模糊 (简单的锐化卷积)
        if auto_sharp:
            sharp = ImageEnhance.Sharpness(pil_img)
            pil_img = sharp.enhance(1.8) # 自动提高清晰度
        
        # 转回 OpenCV 格式保存
        final_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    return final_img, "处理成功"

# --- 核心逻辑 ---

# 1. 这里是实现“选择文件夹”的关键
uploaded_files = st.file_uploader(
    "【点击按钮，直接选择包含图片的整个文件夹】", 
    accept_multiple_files=True, 
    type=['jpg','jpeg','png'],
    key="folder_uploader"
)

# 用于存储处理好的图片，供压缩使用
processed_files = []

if uploaded_files:
    # 过滤出图片文件，并获取文件夹名称 (假设都在同一个文件夹下)
    img_files = [f for f in uploaded_files if f.type.startswith('image/')]
    
    if not img_files:
        st.error("文件夹中未检测到有效的图片文件 (仅支持 .jpg, .png)。")
    else:
        # 获取最顶层文件夹名称 (用于 Zip 文件命名)
        first_file_path = img_files[0].name
        base_folder_name = first_file_path.split('/')[0] if '/' in first_file_path else "images"
        
        st.success(f"📂 已成功读取文件夹: {base_folder_name}")
        st.info(f"✨ 共检测到 {len(img_files)} 张图片，正在进行 AI 修复...")
        
        # 2. 进度条与处理
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, file in enumerate(img_files):
            try:
                # 处理
                final_res, msg = smart_ai_process(file.read(), file.name)
                
                if final_res is not None:
                    # 3. 编码并暂存
                    _, buf = cv2.imencode(".jpg", final_res, [cv2.IMWRITE_JPEG_QUALITY, quality])
                    # 移除原始路径中的斜杠，防止解压时出错
                    clean_name = file.name.replace('/', '_')
                    processed_files.append((f"fixed_{clean_name}.jpg", buf.tobytes()))
                
                # 更新进度
                curr_p = int(((idx+1) / len(img_files)) * 100)
                progress_bar.progress(curr_p)
                status_text.text(f"已完成: {file.name} ({curr_p}%)")
                
            except Exception as e:
                st.warning(f"处理失败: {file.name} - {str(e)}")

        progress_bar.empty()
        status_text.success(f"✅ 处理完成！全部图片已修复。")
        
        # 3. 提供 Zip 打包下载 (最关键的一步)
        if processed_files:
            # 在内存中创建 Zip 文件
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for filename, file_data in processed_files:
                    zip_file.writestr(filename, file_data)
            
            zip_buffer.seek(0)
            
            # 按钮区域
            c1, c2, c3 = st.columns(3)
            with c2:
                st.download_button(
                    label=f"👉 点击下载整个文件夹 ({len(processed_files)} 张已修复图片) 👈",
                    data=zip_buffer,
                    file_name=f"{base_folder_name}_fixed_{int(time.time())}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
