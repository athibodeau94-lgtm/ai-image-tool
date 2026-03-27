def process_engine(image_bytes, config):
    # 读取原图
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = img.size
    tw, th = config['size']

    # --- 1. 计算等比例缩放比例 (确保不裁切) ---
    # 找到缩放因子，使图片能完全装入目标尺寸
    ratio = min(tw / orig_w, th / orig_h)
    
    # 如果原图比目标小，且你不希望放大（保持原样居中），则 ratio 取 1
    # 如果希望小图也撑满画布高度，则保留上面的计算
    new_w = int(orig_w * ratio)
    new_h = int(orig_h * ratio)
    img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # --- 2. 创建画布 (背景处理) ---
    if config['bg_mode'] == "深度高斯模糊":
        # 背景依然采用全屏拉伸+模糊，营造氛围
        bg = img.resize((tw, th), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=config['blur_radius']))
    else:
        # 提取原图的主色调或简单纯色填充背景
        bg = Image.new("RGB", (tw, th), (30, 30, 30)) # 默认暗色底，也可改为提取色

    # --- 3. 垂直居中合成 ---
    # 计算偏移，确保图片在画布正中心
    offset_x = (tw - new_w) // 2
    offset_y = (th - new_h) // 2
    bg.paste(img_resized, (offset_x, offset_y))

    # --- 4. 效果增强 (仅针对合成后的成品) ---
    bg = ImageEnhance.Brightness(bg).enhance(config['bright_level'])
    bg = ImageEnhance.Sharpness(bg).enhance(config['sharp_level'])
    
    # 简单滤镜处理
    if config['filter'] == "暖色调 (食欲)":
        r, g, b = bg.split()
        r = ImageEnhance.Brightness(r).enhance(1.1)
        bg = Image.merge("RGB", (r, g, b))

    # ---
