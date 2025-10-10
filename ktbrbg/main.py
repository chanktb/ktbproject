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
    Quy trình xử lý ảnh chính, tận dụng các hàm từ utils.
    """
    print(f"🚀 Bắt đầu xử lý file: {os.path.basename(input_path)} với Tolerance = {magicwand_tolerance}")
    
    try:
        original_image = Image.open(input_path).convert("RGBA")
    except Exception as e:
        print(f"❌ Lỗi: Không thể đọc file ảnh {input_path}: {e}")
        return

    # --- Bước 1, 2 & 3: Tách nền, Tinh chỉnh viền và Làm nét (Gói gọn trong 1 hàm) ---
    # Hàm remove_background_advanced đã bao gồm cả 3 bước này.
    processed_design = remove_background_advanced(
        original_image,
        tolerance=magicwand_tolerance,
        refine_size=REFINE_TARGET_SIZE
    )
    print("✅ Tách nền, tinh chỉnh và làm nét thành công.")

    # --- Bước 4: Cắt gọn nền trong suốt thừa ---
    # Sử dụng hàm trim_transparent_background từ utils để thay thế logic cv2.boundingRect
    trimmed_design = trim_transparent_background(processed_design)
    if not trimmed_design:
        print("❌ Lỗi: Không tìm thấy đối tượng sau khi tách nền.")
        return
    print(f"✅ Cắt gọn đối tượng. Kích thước gốc: {trimmed_design.width}x{trimmed_design.height}px")

    # --- Bước 5: Scale ảnh để vừa vào canvas (Đã loại bỏ padding) ---
    img_w, img_h = trimmed_design.size
    if img_w == 0 or img_h == 0:
        print("❌ Lỗi: Kích thước ảnh sau khi cắt không hợp lệ.")
        return

    img_aspect_ratio = img_w / img_h
    canvas_aspect_ratio = CANVAS_WIDTH / CANVAS_HEIGHT
    
    if img_aspect_ratio > canvas_aspect_ratio:
        target_w = CANVAS_WIDTH
        target_h = int(target_w / img_aspect_ratio)
    else:
        target_h = CANVAS_HEIGHT
        target_w = int(target_h * img_aspect_ratio)
        
    scaled_image = trimmed_design.resize((target_w, target_h), Image.Resampling.LANCZOS)
    print(f"✅ Scale ảnh. Kích thước mới: {target_w}x{target_h}px")
    
    # --- Bước 6: Đặt vào khung (Canvas) ---
    canvas = Image.new('RGBA', (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    paste_x = (CANVAS_WIDTH - target_w) // 2
    paste_y = 0 # Dán lên trên cùng vì không còn PADDING_TOP
    
    print(f"🎨 Căn giữa và dán ảnh tại tọa độ (X, Y): ({paste_x}, {paste_y})")
    canvas.paste(scaled_image, (paste_x, paste_y), mask=scaled_image)
    print(f"✅ Đặt thiết kế vào khung thành công.")

    # --- Bước 7: Lưu ảnh cuối cùng ---
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