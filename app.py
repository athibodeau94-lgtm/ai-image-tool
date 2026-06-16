import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import numpy as np
import cv2
from concurrent.futures import ThreadPoolExecutor

# --- 1. 页面配置 ---
st.set_page_config(page_title="餐影工坊 2.0 Pro", layout="wide")

# --- 2. 算法引擎 ---
def advanced_extract_foreground(img_obj):
    try:
        src = np.array(img_obj)
        if src.shape[2] < 4: src = cv2.cvtColor(src, cv2.COLOR_RGB2RGBA)
        h, w = src.shape[:2]
        rect = (int(w*0.05), int(h*0.05), int(w*0.9), int(h*0.9))
        mask = np.zeros((h, w), np.uint8)
        bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
        cv2.grabCut(src[:,:,:3], mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
        bin_mask = np.where((mask==2)|(mask==0), 0, 1).astype('uint8') * 255
        out_rgba = src.copy(); out_rgba[:,:,3] = np.minimum(out_rgba[:,:,3], cv2.GaussianBlur(bin_mask, (11,11), 0))
        return Image.fromarray(out_rgba)
    except: return img_obj

def process_engine(img_input, config):
    try:
        img = Image.open(io.BytesIO(img_input)) if isinstance(img_input, bytes) else img_input
        img = img.convert("RGBA")
        if config.get('auto_crop'): img = advanced_extract_foreground(img)
            
        tw, th = config['size']
        # --- 背景渲染逻辑 ---
        if config['bg_mode'] == "深度高斯模糊":
            res_img = img.convert("RGB").resize((tw, th))
            res_img = res_img.filter(ImageFilter.GaussianBlur(15))
            res_img.paste(img, ((tw-img.width)//2, (th-img.height)//2), img if img.mode == 'RGBA' else None)
        elif config['bg_mode'] == "特定颜色":
            color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (200,200,200,255)}
            res_img = Image.new("RGBA", (tw, th), (0,0,0,0) if config['pure_color']=="透明" else color_map.get(config['pure_color'], (255,255,255,255)))
            ratio = min(tw/img.size[0], th/img.size[1])
            resized = img.resize((int(img.size[0]*ratio), int(img.size[1]*ratio)), Image.Resampling.LANCZOS)
            res_img.alpha_composite(resized, ((tw-resized.size[0])//2, (th-resized.size[1])//2))
        else: # 提取原色
            res_img = Image.new("RGBA", (tw, th), img.getpixel((0,0)))
            res_img.paste(img, ((tw-img.width)//2, (th-img.height)//2), img if img.mode == 'RGBA' else None)
        
        res_img = ImageEnhance.Brightness(res_img).enhance(config['bright'])
        res_img = ImageEnhance.Sharpness(res_img).enhance(config['sharp'])
        
        out_io = io.BytesIO()
        ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
        res_img.convert("RGB" if ext=="JPEG" else "RGBA").save(out_io, format=ext, quality=90)
        return out_io.getvalue(), ext
    except: return None, None

# --- 3. 界面 ---
left, right = st.columns([1.2, 2.4], gap="large")
with left:
    raw_uploads = st.file_uploader("上传图片", type=['jpg','jpeg','png'], accept_multiple_files=True)
    with st.expander("规格设置", expanded=True):
        res_map = {"": None, "聚合标准 (1920*1080)": "1920*1080", "屏保 (1080*1920)": "1080*1920", "自定义": "custom"}
        res_label = st.selectbox("比例预设", list(res_map.keys()))
        tw, th = 1920, 1080
        if res_map.get(res_label) and res_map[res_label] != "custom": tw, th = map(int, res_map[res_label].split('*'))
        elif res_label == "自定义": tw = st.number_input("宽", 100, 4000, 1920); th = st.number_input("高", 100, 4000, 1080)

    with st.expander("视觉设置", expanded=True):
        auto_crop = st.checkbox("开启智能自动抠图")
        # 联动逻辑：抠图时背景模式锁定为“特定颜色”
        if auto_crop:
            bg_m = st.selectbox("背景模式", ["特定颜色"], index=0)
            p_color = st.selectbox("底色选择", ["-- 请选择底色 --", "白色", "黑色", "灰色", "透明"])
        else:
            bg_m = st.selectbox("背景模式", ["深度高斯模糊", "特定颜色", "提取原色"])
            p_color = st.selectbox("底色选择", ["白色", "黑色", "灰色", "透明"])
        br = st.slider("亮度", 0.5, 1.5, 1.0); sh = st.slider("锐化", 1.0, 4.0, 1.5)

with right:
    # 渲染条件判断
    ready = raw_uploads and res_label != "" and (not auto_crop or p_color != "-- 请选择底色 --")
    if ready:
        conf = {'size': (tw, th), 'bg_mode': bg_m, 'pure_color': p_color, 'bright': br, 'sharp': sh, 'auto_crop': auto_crop}
        with ThreadPoolExecutor() as exe:
            processed = [exe.submit(process_engine, f.getvalue(), conf).result() for f in raw_uploads]
        cols = st.columns(3)
        for i, (data, ext) in enumerate(processed):
            if data: cols[i%3].image(data, use_container_width=True)
    elif auto_crop and p_color == "-- 请选择底色 --":
        st.warning("请在左侧视觉设置中选择底色以继续。")
