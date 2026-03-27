import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
import zipfile
import time

# --- 1. 页面高级感配置 (CSS 注入) ---
st.set_page_config(page_title="餐影工坊 Pro", layout="wide", page_icon="🍽️")

st.markdown("""
    <style>
    /* 侧边栏宽度优化：约占 1/4 */
    [data-testid="stSidebar"] {
        min-width: 25% !important;
        max-width: 25% !important;
        background-color: #fcfcfc;
        border-right: 1px solid #eee;
    }
    /* 隐藏顶部红条 */
    header {visibility: hidden;}
    /* 按钮样式优化 */
    .stButton>button {
        border-radius: 4px;
        background-color: #1a1a1a;
        color: white;
        border: none;
        transition: 0.3s;
    }
    .stButton>button:hover {
        background-color: #404040;
        border: none;
    }
    /* 卡片式预览 */
    .img-card {
        border: 1px solid #f0f0f0;
        border-radius: 8px;
        padding: 10px;
        background: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心处理逻辑 ---
def process_engine(file, config, is_preview=False):
    if file is None: return None
    
    # 读取图片
    img = Image.open(io.BytesIO(file.getvalue() if hasattr(file, 'getvalue') else file)).convert("RGBA")
    orig_w, orig_h = img.size
    tw, th = config['size']

    # 计算等比例缩放 (Contain模式)
    ratio = min(tw / orig_w, th / orig_h)
    new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
    img_fit = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 背景处理
    if config['bg_mode'] == "深度高斯模糊":
        bg = img.convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius'])).convert("RGBA")
    elif config['bg_mode'] == "特定颜色":
        color_map = {"白色": (255,255,255,255), "黑色": (0,0,0,255), "灰色": (128,128,128,255), "透明": (0,0,0,0)}
        bg = Image.new("RGBA", (tw, th), color_map.get(config['pure_color'], (255,255,255,255)))
    else: # 提取原色
        sample = img.convert("RGB").getpixel((orig_w//2, orig_h//2))
        bg = Image.new("RGBA", (tw, th), sample + (255,))

    # 居中合成
    offset_x, offset_y = (tw - new_w) // 2, (th - new_h) // 2
    bg.paste(img_fit, (offset_x, offset_y), img_fit)

    # 效果增强 (转换回RGB处理色彩)
    res = bg.convert("RGB")
    res = ImageEnhance.Brightness(res).enhance(config['bright'])
    res = ImageEnhance.Sharpness(res).enhance(config['sharp'])
    
    if config['filter'] == "暖色调 (诱人)":
        r, g, b = res.split(); r = ImageEnhance.Brightness(r).enhance(1.12); res = Image.merge("RGB", (r, g, b))
    elif config['filter'] == "清爽调":
        r, g, b = res.split(); b = ImageEnhance.Brightness(b).enhance(1.08); res = Image.merge("RGB", (r, g, b))

    # 输出
    out_io = io.BytesIO()
    ext = "PNG" if config.get('pure_color') == "透明" else "JPEG"
    
    if ext == "JPEG":
        q = 95
        limit = config['limit_kb'] * 1024 if config['limit_kb'] > 0 else 999999999
        while q > 15:
            out_io = io.BytesIO()
            res.save(out_io, format="JPEG", quality=q, optimize=True)
            if out_io.tell() <= limit or is_preview: break
            q -= 5
    else:
        bg.save(out_io, format="PNG")
        
    return out_io.getvalue(), ext

# --- 3. 侧边栏 UI ---
with st.sidebar:
    st.title("⚙️ 参数配置")
    
    with st.expander("📏 尺寸与体积", expanded=True):
        res_opt = st.selectbox("目标分辨率", ["1920*1080", "1000*600", "800*800", "自定义"])
        if res_opt == "自定义":
            tw = st.number_input("宽度(px)", 100, 4000, 1920)
            th = st.number_input("高度(px)", 100, 4000, 1080)
        else:
            tw, th = map(int, res_opt.split('*'))
        
        vol_opt = st.selectbox("体积控制", ["不限制", "500KB", "1MB"])
        kb = 0 if vol_opt == "不限制" else (500 if vol_opt == "500KB" else 1024)

    with st.expander("🖼️ 背景设置", expanded=True):
        bg_m = st.radio("填充模式", ["深度高斯模糊", "特定颜色", "提取原色"])
        p_color = "白色"
        b_radius = 40
        if bg_m == "特定颜色":
            p_color = st.selectbox("选择颜色", ["白色", "黑色", "灰色", "透明"])
        elif bg_m == "深度高斯模糊":
            b_radius = st.slider("模糊强度", 0, 100, 40)

    with st.expander("✨ 滤镜增强", expanded=True):
        flt = st.selectbox("风格滤镜", ["原色", "暖色调 (诱人)", "清爽调"])
        br = st.slider("亮度", 0.5, 1.5, 1.05)
        sh = st.slider("锐化(去糊)", 1.0, 4.0, 1.8)

    st.markdown("---")
    if st.button("🗑️ 重置所有设置"):
        st.rerun()

# --- 4. 主界面逻辑 ---
st.title("🍽️ 餐影工坊 Pro")
st.caption("支持文件夹拖拽上传 • 实时效果预览 • 无损比例缩放")

files = st.file_uploader("将图片或整个文件夹拖入此处", type=['jpg','jpeg','png'], accept_multiple_files=True)

if files:
    # 构建当前配置字典
    current_conf = {
        'size': (tw, th), 'limit_kb': kb, 'bg_mode': bg_m, 
        'pure_color': p_color, 'blur_radius': b_radius,
        'filter': flt, 'bright': br, 'sharp': sh
    }

    # 实时预览区 (取第一张图)
    st.subheader("👀 实时预览 (调整左侧参数立即生效)")
    preview_bytes, preview_ext = process_engine(files[0], current_conf, is_preview=True)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.image(preview_bytes, caption=f"实时预览效果 ({tw}x{th})", use_container_width=True)
    with col2:
        st.info(f"**处理详情**\n- 文件名: {files[0].name}\n- 格式: {preview_ext}\n- 缩放模式: 等比例居中")
        
        # 批量处理与下载
        if st.button("🚀 导出全部图片"):
            zip_name = f"{files[0].name.split('.')[0]}_{tw}x{th}.zip"
            zip_buf = io.BytesIO()
            
            p_bar = st.progress(0, text="正在处理中...")
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                for idx, f in enumerate(files):
                    data, ext = process_engine(f, current_conf)
                    # 保留原名，后缀根据格式调整
                    final_name = f"{f.name.rsplit('.', 1)[0]}.{ext.lower()}"
                    zf.writestr(final_name, data)
                    p_bar.progress((idx + 1) / len(files))
            
            st.success("处理完成！")
            st.download_button(
                label="📥 点击下载压缩包",
                data=zip_buf.getvalue(),
                file_name=zip_name,
                mime="application/zip",
                use_container_width=True
            )
else:
    # 未上传时的引导界面
    st.markdown("""
    <div style='text-align: center; padding: 50px; border: 2px dashed #eee; border-radius: 10px;'>
        <p style='color: #999;'>请上传菜品图片开始美化</p>
    </div>
    """, unsafe_allow_html=True)

# 底部交互提示
st.divider()
st.caption("餐影工坊 Pro - 专注餐厅数字化图片交付")
