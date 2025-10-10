# -*- coding: utf-8 -*-
"""
Script tự động xử lý ảnh cho tool KTBRBG. (Tối ưu từ v30)
- Tận dụng các hàm xử lý ảnh chung từ thư mục /utils.
- Chạy lần lượt với tất cả các ảnh trong thư mục InputImage.
- Với mỗi ảnh, tự động thử nhiều giá trị tolerance (60, 70).
- Tự động commit và push kết quả lên Git.
"""

import os
import subprocess
from datetime import datetime
from PIL import Image
import numpy as np
import cv2

# Import các hàm dùng chung từ thư mục utils
# Giả định script này được chạy từ thư mục gốc của ktbproject
from utils.image_processing import remove_background_advanced, trim_transparent_background

# ==============================================================================
# CẤU HÌNH DỰ ÁN KTBRBG
# ==============================================================================
INPUT_FOLDER = "InputImage"
OUTPUT_FOLDER = "OutputImage"
CANVAS_WIDTH = 4200
CANVAS_HEIGHT = 4800
TARGET_DPI = 300
REFINE_TARGET_SIZE = 10000 # Độ phân giải mục tiêu để tinh chỉnh viền

# ==============================================================================
# HẾT PHẦN CẤU HÌNH
# ==============================================================================
def create_hybrid_soft_mask(sharp_mask_cv, blur_ksize=15, erosion_ksize=5):
    """
    Tạo mặt nạ lai: Lõi 100% đặc, viền mềm mại.
    - blur_ksize: Độ rộng và độ mềm của viền. Càng lớn càng mềm.
    - erosion_ksize: Độ dày của phần lõi đặc. Càng lớn lõi càng nhỏ.
    """
    print(f"✨ Tạo mặt nạ lai (Blur: {blur_ksize}px, Erosion: {erosion_ksize}px)...")
    
    # 1. Tạo mặt nạ viền mềm (như cũ)
    blur_kernel = (blur_ksize if blur_ksize % 2 != 0 else blur_ksize + 1, ) * 2
    blurred_mask = cv2.GaussianBlur(sharp_mask_cv, blur_kernel, 0)
    
    # 2. Tạo mặt nạ lõi bằng cách "ăn mòn" (co nhỏ) mặt nạ sắc nét
    erosion_kernel = np.ones((erosion_ksize, erosion_ksize), np.uint8)
    core_mask = cv2.erode(sharp_mask_cv, erosion_kernel, iterations=1)
    
    # 3. Kết hợp: Lấy mặt nạ mờ làm nền, sau đó dán phần lõi đặc lên
    hybrid_mask = blurred_mask.copy()
    hybrid_mask[core_mask == 255] = 255
    
    return hybrid_mask

def git_push_results():
    """Tự động thêm, commit và push các kết quả lên GitHub."""
    try:
        print("\n" + "="*60)
        print("🚀 Bắt đầu quá trình tự động push lên GitHub...")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_message = f"Auto-commit: Processed images via ktbrbg on {current_time}"

        print("   1. Đang thêm các file vào staging area (git add .)...")
        subprocess.run(["git", "add", "."], check=True, cwd="..") # Thêm cwd để chạy git từ thư mục gốc

        print(f"   2. Đang commit với message: '{commit_message}'...")
        subprocess.run(["git", "commit", "-m", commit_message], check=True, cwd="..")

        print("   3. Đang đẩy các thay đổi lên remote repository (git push)...")
        subprocess.run(["git", "push"], check=True, cwd="..")

        print("✅ Push lên GitHub thành công!")
        print("="*60)

    except FileNotFoundError:
        print("❌ LỖI: Lệnh 'git' không tồn tại. Hãy chắc chắn rằng bạn đã cài đặt Git.")
    except subprocess.CalledProcessError as e:
        print(f"❌ LỖI: Một lệnh Git đã thất bại (mã lỗi: {e.returncode}).")
        print(f"   Lỗi chi tiết: {e.stderr}")
    except Exception as e:
        print(f"❌ Đã có lỗi không xác định xảy ra: {e}")

def process_image(input_path, output_path, magicwand_tolerance):
    """
    Quy trình xử lý ảnh chính, sử dụng kỹ thuật mặt nạ lai.
    """
    print(f"🚀 Bắt đầu xử lý file: {os.path.basename(input_path)} với Tolerance = {magicwand_tolerance}")
    
    try:
        original_image = Image.open(input_path).convert("RGBA")
    except Exception as e:
        print(f"❌ Lỗi: Không thể đọc file ảnh {input_path}: {e}")
        return

    # Bước 1 & 2: Tách nền và cắt gọn (giữ nguyên)
    processed_design = remove_background_advanced(original_image, tolerance=magicwand_tolerance, refine_size=REFINE_TARGET_SIZE)
    trimmed_design = trim_transparent_background(processed_design)
    if not trimmed_design:
        print("❌ Lỗi: Không tìm thấy đối tượng sau khi tách nền.")
        return
    print(f"✅ Tách nền và cắt gọn thành công.")

    # <<< BƯỚC MỚI: TẠO MẶT NẠ LAI VÀ ÁP DỤNG >>>
    try:
        rgb_channels = trimmed_design.convert("RGB")
        sharp_alpha_channel = trimmed_design.split()[3]
        sharp_alpha_cv = np.array(sharp_alpha_channel)
        
        # Gọi hàm tạo mặt nạ lai mới
        hybrid_mask_cv = create_hybrid_soft_mask(
            sharp_alpha_cv, 
            blur_ksize=7,    # Điều chỉnh độ mềm của viền
            erosion_ksize=5   # Điều chỉnh độ dày của lõi
        )
        
        hybrid_mask_pil = Image.fromarray(hybrid_mask_cv)
        
        final_design = rgb_channels.copy()
        final_design.putalpha(hybrid_mask_pil)

    except Exception as e:
        print(f"⚠️ Cảnh báo: Lỗi khi tạo mặt nạ lai, sử dụng ảnh gốc. Lỗi: {e}")
        final_design = trimmed_design

    # --- Các bước còn lại sử dụng 'final_design' với viền mềm và lõi đặc ---
    
    # Bước 4: Scale ảnh
    # ... (phần code scale giữ nguyên như cũ) ...
    img_w, img_h = final_design.size
    img_aspect_ratio = img_w / img_h
    canvas_aspect_ratio = CANVAS_WIDTH / CANVAS_HEIGHT
    if img_aspect_ratio > canvas_aspect_ratio:
        target_w = CANVAS_WIDTH
        target_h = int(target_w / img_aspect_ratio)
    else:
        target_h = CANVAS_HEIGHT
        target_w = int(target_h * img_aspect_ratio)
    scaled_image = final_design.resize((target_w, target_h), Image.Resampling.LANCZOS)
    print(f"✅ Scale ảnh. Kích thước mới: {target_w}x{target_h}px")

    # Bước 5 & 6: Đặt vào khung và Lưu
    canvas = Image.new('RGBA', (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    paste_x = (CANVAS_WIDTH - target_w) // 2
    paste_y = 0
    canvas.paste(scaled_image, (paste_x, paste_y), mask=scaled_image)
    canvas.save(output_path, 'PNG', dpi=(TARGET_DPI, TARGET_DPI))
    print(f"🎉 Hoàn thành! File đã được lưu tại: {output_path}")
    print("-" * 50)

def main():
    print("==========================================================")
    print("=== SCRIPT XỬ LÝ ẢNH - TOOL KTBRBG (Tối ưu từ v30) ===")
    print("==========================================================")
    
    if not os.path.exists(INPUT_FOLDER):
        os.makedirs(INPUT_FOLDER)
        print(f"📂 Thư mục '{INPUT_FOLDER}' đã được tạo. Vui lòng thêm ảnh vào và chạy lại script.")
        return
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
    
    tolerances_to_test = [60, 70]
    files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(('.png', '.jpg', 'jpeg'))]
    if not files:
        print(f"📂 Không tìm thấy file ảnh nào trong thư mục '{INPUT_FOLDER}'.")
        return

    total_files = len(files)
    total_processes = total_files * len(tolerances_to_test)
    current_process = 0
    
    for image_file in files:
        for tolerance_value in tolerances_to_test:
            current_process += 1
            print(f"\n🔄 XỬ LÝ LƯỢT {current_process}/{total_processes} 🔄")
            
            input_file_path = os.path.join(INPUT_FOLDER, image_file)
            filename, _ = os.path.splitext(image_file)
            
            output_filename = f"{filename}_tol{tolerance_value}_processed.png"
            output_file_path = os.path.join(OUTPUT_FOLDER, output_filename)
            
            process_image(input_file_path, output_file_path, tolerance_value)
            
    print("\n========================================================")
    print(f"✅✅✅ ĐÃ XỬ LÝ XONG TOÀN BỘ {total_files} ẢNH! ✅✅✅")
    print("========================================================")
    #git_push_results()

if __name__ == "__main__":
    # Thay đổi thư mục làm việc hiện tại thành thư mục chứa file script
    # để các đường dẫn tương đối (INPUT_FOLDER) hoạt động chính xác
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()