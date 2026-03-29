import streamlit as st
from PIL import Image
import io, zipfile

st.set_page_config(page_title="餐影工坊 1.1", layout="wide")

def process_img(file_obj, size_cfg):
    # 使用 BytesIO 深度拷贝，防止文件被提前关闭导致的 OSError
    img_data = io.BytesIO(file_obj.read())
    img = Image.open(img_data).convert("RGB")
    img.thumbnail(size_cfg, Image.Resampling.LANCZOS)
    
    out_io = io.BytesIO()
    img.save(out_io, format="JPEG", quality=85)
    return out_io.getvalue()

st.title("🍽️ 餐影工坊")
uploaded = st.file_uploader("上传图片", type=['jpg', 'png'], accept_multiple_files=True)

if uploaded:
    # 侧边栏分辨率设置
    res = st.sidebar.selectbox("分辨率", ["1920*1080", "1000*600"])
    tw, th = map(int, res.split('*'))
    
    cols = st.columns(3)
    processed_data = []
    
    for i, f in enumerate(uploaded):
        data = process_img(f, (tw, th))
        processed_data.append((f.name, data))
        with cols[i % 3]:
            st.image(data, use_container_width=True)
            
    if st.sidebar.button("导出 ZIP"):
        z_io = io.BytesIO()
        with zipfile.ZipFile(z_io, 'w') as zf:
            for name, d in processed_data:
                zf.writestr(f"p_{name}", d)
        st.sidebar.download_button("下载 ZIP", z_io.getvalue(), "output.zip")
