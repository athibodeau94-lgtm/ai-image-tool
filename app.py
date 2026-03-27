import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageEnhance

st.set_page_config(page_title="AI 图像处理站", layout="wide")
st.title("🖼️ 智能图像自动化处理站")

with st.sidebar:
    st.header("输出配置")
    tw = st.number_input("目标宽度", value=1920)
    th = st.number_input("目标高度", value=1080)
    quality = st.slider("保存质量", 10, 100, 90)
    auto_fix = st.checkbox("自动修复 (暗光/模糊/色彩)", value=True)

# 允许一次拖入大量图片（模拟文件夹上传）
files = st.file_uploader("全选文件夹里的图片拖到这里", accept_multiple_files=True, type=['jpg','png','jpeg'])

def smart_process(bytes_data):
    # 解码
    arr = np.frombuffer(bytes_data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None: return None

    # 1. 自动纠正旋转（根据长宽比简单判断，复杂判断需AI模型）
    h, w = img.shape[:2]
    if h > w: # 如果是竖图，自动转为横图以适应屏幕
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        h, w = img.shape[:2]

    # 2. 画质增强
    if auto_fix:
        # 处理过暗：自动直方图均衡化
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        img = cv2.cvtColor(cv2.merge((l,a,b)), cv2.COLOR_LAB2BGR)
        
        # 处理过糊：锐化卷积
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        img = cv2.filter2D(img, -1, kernel)

    # 3. 尺寸缩放并填充 (补齐 1920x1080)
    canvas = np.zeros((th, tw, 3), dtype=np.uint8)
    scale = min(tw/w, th/h)
    nw, nh = int(w*scale), int(h*scale)
    rsz = cv2.resize(img, (nw, nh))
    y, x = (th-nh)//2, (tw-nw)//2
    canvas[y:y+nh, x:x+nw] = rsz
    
    return canvas

if files:
    st.success(f"已就绪！共检测到 {len(files)} 张图片")
    for f in files:
        with st.expander(f"处理结果: {f.name}"):
            res = smart_process(f.read())
            if res is not None:
                st.image(res, channels="BGR", use_container_width=True)
                _, buf = cv2.imencode(".jpg", res, [cv2.IMWRITE_JPEG_QUALITY, quality])
                st.download_button(f"下载 {f.name}", buf.tobytes(), f"fixed_{f.name}", "image/jpeg")
