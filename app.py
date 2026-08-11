# 2. 导出下载逻辑（应用重命名、自动去重与 .jpg 后缀）
        if len(processed_list) == 1:
            data, ext = final_outputs[0]
            if data:
                final_filename = f"{edited_names[0]}.{ext.lower()}"
                st.download_button(f"下载处理后的图片: {final_filename}", data=data, file_name=final_filename, type="primary", use_container_width=True)
        else:
            final_zip_name = f"{zip_prefix}-{dim_name}.zip"
            zip_buf = io.BytesIO()
            
            # 用于记录已使用的文件名，防止同名覆盖
            filename_counts = {}
            success_count = 0
            
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for idx, item in enumerate(processed_list):
                    data, ext = final_outputs[idx]
                    if data:
                        # 获取用户输入的名称（若为空则还原原文件名主干）
                        raw_stem = edited_names[idx].strip() if idx < len(edited_names) and edited_names[idx].strip() else os.path.splitext(item["name"])[0]
                        
                        # 重名检测：如果文件名重复，自动加上 _1, _2 后缀
                        if raw_stem in filename_counts:
                            filename_counts[raw_stem] += 1
                            final_stem = f"{raw_stem}_{filename_counts[raw_stem]}"
                        else:
                            filename_counts[raw_stem] = 0
                            final_stem = raw_stem
                        
                        final_filename = f"{final_stem}.{ext.lower()}"
                        zf.writestr(final_filename, data)
                        success_count += 1
            
            st.download_button(
                label=f"立即打包下载 ({success_count}张)", 
                data=zip_buf.getvalue(), 
                file_name=final_zip_name, 
                type="primary", 
                use_container_width=True
            )
            
            del final_outputs
            gc.collect()
