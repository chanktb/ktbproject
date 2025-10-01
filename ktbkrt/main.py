# ktbkrt/main.py

import os
import json
import random
from datetime import datetime
import pytz
from PIL import Image, ImageFilter, ImageFont
from io import BytesIO
from dotenv import load_dotenv

# Import các hàm từ module dùng chung
from utils.image_processing import (
    stylize_image,
    add_hashtag_text,
    trim_transparent_background,
    add_watermark,
    determine_mockup_color
)
from utils.file_io import (
    load_config,
    create_exif_data,
    update_total_image_count,
    find_mockup_image,
    send_telegram_summary
)

# --- Cấu hình đường dẫn ---
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOL_DIR)
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, '.env'))

# Đường dẫn tài nguyên chung
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.json")
MOCKUP_DIR = os.path.join(PROJECT_ROOT, "mockup")
WATERMARK_DIR = os.path.join(PROJECT_ROOT, "watermark")
FONT_FILE = os.path.join(PROJECT_ROOT, "verdanab.ttf")
FONTS_DIR = os.path.join(PROJECT_ROOT, "fonts")

# Đường dẫn riêng của tool
INPUT_DIR = os.path.join(TOOL_DIR, "InputImage")
OUTPUT_DIR = os.path.join(TOOL_DIR, "OutputImage")
TOTAL_IMAGE_FILE = os.path.join(TOOL_DIR, "TotalImage.txt")

# --- CÁC HÀM HỖ TRỢ RIÊNG CỦA TOOL NÀY ---

def get_krt_inputs(available_mockups):
    """Hỏi người dùng các tùy chọn cho tool KTB-KRT."""
    print("-" * 50)
    
    try:
        level_str = input("▶️ Nhập mức độ giảm màu (Posterize) (1-8, Enter = 4): ")
        posterize_level = int(level_str) if level_str else 4
    except ValueError:
        posterize_level = 4

    try:
        feather_str = input("▶️ Nhập tỷ lệ làm mờ viền (0.0-0.5, Enter = 0.15): ")
        feather_margin = float(feather_str) if feather_str else 0.15
    except ValueError:
        feather_margin = 0.15

    text_choice = input("▶️ Bạn có muốn chèn text hashtag không? (Y/n): ")
    add_text = text_choice.lower() != 'n'

    print("\n📜 Các mockup set có sẵn:")
    mockup_list = list(available_mockups.keys())
    for i, name in enumerate(mockup_list):
        print(f"  {i + 1}: {name}")

    while True:
        try:
            choices_str = input("▶️ Chọn các mockup set, cách nhau bởi dấu phẩy (vd: 1,3,4): ")
            if not choices_str:
                print("Lỗi: Vui lòng chọn ít nhất một mockup."); continue
            selected_indices = [int(i.strip()) - 1 for i in choices_str.split(',')]
            selected_mockups = [mockup_list[i] for i in selected_indices if 0 <= i < len(mockup_list)]
            if selected_mockups:
                print(f"✅ Bạn đã chọn: {', '.join(selected_mockups)}"); break
            else:
                print("Lỗi: Lựa chọn không hợp lệ.")
        except (ValueError, IndexError):
            print("Lỗi: Vui lòng chỉ nhập các số hợp lệ.")

    print("-" * 50)
    return posterize_level, feather_margin, add_text, selected_mockups

def cleanup_input_directory(directory, processed_files_list):
    """Xóa các file đã xử lý trong thư mục Input."""
    print("-" * 50)
    choice = input("▶️ Xử lý hoàn tất. Xóa các file ảnh trong InputImage? (Enter = XÓA, 'n' = Giữ lại): ")
    if choice.lower() != 'n':
        print(f"\n--- 🗑️  Dọn dẹp thư mục: {directory} ---")
        if not os.path.exists(directory): return
        for filename in processed_files_list:
            try:
                os.unlink(os.path.join(directory, filename))
                print(f"  - Đã xóa: {filename}")
            except Exception as e:
                print(f'Lỗi khi xóa {filename}. Lý do: {e}')
    else:
        print("  -> 💾 Đã giữ lại các file trong InputImage.")

# --- HÀM MAIN CHÍNH ---
def main():
    print("🚀 Bắt đầu quy trình sáng tạo của KTB-KRT...")
    
    for dir_path in [OUTPUT_DIR, INPUT_DIR, MOCKUP_DIR, FONTS_DIR]:
        if not os.path.exists(dir_path): os.makedirs(dir_path)
    
    configs = load_config(CONFIG_FILE)
    if not configs: return
        
    defaults = configs.get("defaults", {})
    mockup_sets_config = configs.get("mockup_sets", {})
    exif_defaults = defaults.get("exif_defaults", {})
    output_format = defaults.get("global_output_format", "webp")
    
    images_to_process = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f)) and not f.startswith('.')]
    if not images_to_process:
        print("✅ Không có ảnh mới trong InputImage để xử lý."); return

    posterize_level, feather_margin, add_text, selected_mockups = get_krt_inputs(mockup_sets_config)

    print(f"🔎 Tìm thấy {len(images_to_process)} ảnh, sẽ áp dụng {len(selected_mockups)} mockup đã chọn.")
    images_for_output = {}
    total_processed_this_run = {}
    run_timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y%m%d_%H%M%S')

    for image_filename in images_to_process:
        print(f"\n--- 🎨  Đang sáng tạo từ: {image_filename} ---")
        try:
            with Image.open(os.path.join(INPUT_DIR, image_filename)) as img:
                input_img = img.convert("RGBA")
                
                # BƯỚC 1: TỰ ĐỘNG CHỌN MÀU MOCKUP
                use_black_mockup = determine_mockup_color(input_img)
                print(f"  - Phân tích ảnh: Đề xuất dùng mockup {'ĐEN' if use_black_mockup else 'TRẮNG'}.")

                # BƯỚC 2: "TRỪU TƯỢNG HÓA" ẢNH GỐC
                print(f"  - Stylizing ảnh (Posterize: {posterize_level}, Feather: {feather_margin})...")
                stylized_img = stylize_image(input_img, posterize_level, feather_margin)
                
                # BƯỚC 3: (TÙY CHỌN) THÊM TEXT
                if add_text:
                    print("  - Thêm text hashtag...")
                    final_design = add_hashtag_text(stylized_img, image_filename, FONTS_DIR, stylized_img.width, use_black_mockup)
                else:
                    final_design = stylized_img
                
                # BƯỚC 4: CẮT GỌN LẠI TOÀN BỘ DESIGN
                final_design_trimmed = trim_transparent_background(final_design)
                if not final_design_trimmed:
                    print("  - ⚠️ Cảnh báo: Ảnh trống sau khi xử lý, bỏ qua."); continue

                # BƯỚC 5: GHÉP VÀO CÁC MOCKUP ĐÃ CHỌN
                for mockup_name in selected_mockups:
                    mockup_config = mockup_sets_config.get(mockup_name)
                    if not mockup_config: continue

                    print(f"  - Áp dụng mockup: '{mockup_name}'")
                    mockup_path = find_mockup_image(MOCKUP_DIR, mockup_name, "black" if use_black_mockup else "white")
                    if not mockup_path:
                        print(f"    - ⚠️ Cảnh báo: Không tìm thấy file ảnh mockup. Bỏ qua."); continue
                    
                    with Image.open(mockup_path) as mockup_img:
                        
                        # BƯỚC 6: LOGIC RESIZE VÀ CĂN CHỈNH TỔNG THỂ MỚI
                        mockup_coords = mockup_config.get("coords")
                        if not mockup_coords:
                            print(f"    - ⚠️ Cảnh báo: Mockup '{mockup_name}' thiếu 'coords'. Bỏ qua."); continue

                        obj_w, obj_h = final_design_trimmed.size
                        frame_w, frame_h = mockup_coords['w'], mockup_coords['h']
                        
                        scale_w = frame_w / obj_w
                        scale_h = frame_h / obj_h
                        scale = min(scale_w, scale_h)

                        final_w, final_h = int(obj_w * scale), int(obj_h * scale)
                        resized_final_design = final_design_trimmed.resize((final_w, final_h), Image.Resampling.LANCZOS)
                        
                        if scale_w < scale_h: # Chiều rộng đạt trước
                            paste_x = mockup_coords['x']
                            paste_y = mockup_coords['y']
                        else: # Chiều cao đạt trước
                            paste_x = mockup_coords['x'] + (frame_w - final_w) // 2
                            paste_y = mockup_coords['y']
                        
                        final_mockup = mockup_img.copy().convert("RGBA")
                        final_mockup.paste(resized_final_design, (paste_x, paste_y), resized_final_design)

                        # BƯỚC 7: CÁC BƯỚC CÒN LẠI
                        watermark_desc = mockup_config.get("watermark_text")
                        final_mockup_with_wm = add_watermark(final_mockup, watermark_desc, WATERMARK_DIR, FONT_FILE)
                        
                        prefix = mockup_config.get("title_prefix_to_add", "")
                        suffix = mockup_config.get("title_suffix_to_add", "")
                        base_name = os.path.splitext(image_filename)[0].replace('-', ' ').replace('_', ' ')
                        
                        final_filename_base = f"{prefix} {base_name} {suffix}".strip().replace('  ', ' ')
                        ext = f".{output_format}"
                        final_filename = f"{final_filename_base}{ext}"

                        image_to_save = final_mockup_with_wm.convert('RGB')
                        exif_bytes = create_exif_data(mockup_name, final_filename, exif_defaults)
                        
                        img_byte_arr = BytesIO()
                        save_format = "WEBP" if output_format == "webp" else "JPEG"
                        image_to_save.save(img_byte_arr, format=save_format, quality=90, exif=exif_bytes)
                        
                        images_for_output.setdefault(mockup_name, []).append((final_filename, img_byte_arr.getvalue()))
                        total_processed_this_run[mockup_name] = total_processed_this_run.get(mockup_name, 0) + 1
        
        except Exception as e:
            print(f"❌ Lỗi nghiêm trọng khi xử lý file {image_filename}: {e}")

    if images_for_output:
        print("\n--- 💾 Bắt đầu lưu ảnh vào các thư mục ---")
        for mockup_name, image_list in images_for_output.items():
            output_subdir_name = f"{mockup_name}.{run_timestamp}.{len(image_list)}"
            output_path = os.path.join(OUTPUT_DIR, output_subdir_name)
            os.makedirs(output_path, exist_ok=True)
            print(f"  - Đang tạo và lưu {len(image_list)} ảnh vào: {output_path}")
            for filename, data in image_list:
                with open(os.path.join(output_path, filename), 'wb') as f:
                    f.write(data)

    if images_to_process:
        cleanup_input_directory(INPUT_DIR, images_to_process)

    if total_processed_this_run:
        update_total_image_count(TOTAL_IMAGE_FILE, total_processed_this_run)
    
    print(f"\n--- ✨ Hoàn tất! ---")
    send_telegram_summary("ktbkrt", TOTAL_IMAGE_FILE)

if __name__ == "__main__":
    main()