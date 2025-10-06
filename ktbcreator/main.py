# ktbcreator/main.py

import os
import json
import random
from datetime import datetime
import pytz
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

# Import các hàm từ module dùng chung
from utils.image_processing import (
    remove_background,
    remove_background_advanced,
    trim_transparent_background,
    apply_mockup,
    add_watermark,
    rotate_image,
    crop_by_coords
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
FONT_FILE = os.path.join(PROJECT_ROOT, "fonts", "verdanab.ttf")

# Đường dẫn riêng của tool
INPUT_DIR = os.path.join(TOOL_DIR, "InputImage")
OUTPUT_DIR = os.path.join(TOOL_DIR, "OutputImage")
TOTAL_IMAGE_FILE = os.path.join(PROJECT_ROOT, "TotalImage.txt")

# --- CÁC HÀM HỖ TRỢ RIÊNG CỦA TOOL NÀY ---

def get_creator_inputs(available_mockups):
    """Hỏi người dùng các tùy chọn cho tool KTB-CREATOR (phiên bản rút gọn)."""
    print("-" * 50)
    
    crop_coords = None
    while True:
        try:
            coords_str = input('▶️ Nhập tọa độ crop (ví dụ: {"x":100,"y":100,"w":500,"h":600}) hoặc Enter để bỏ qua: ')
            if not coords_str.strip():
                print("  - Bỏ qua bước crop.")
                break
            crop_coords = json.loads(coords_str.replace("'", '"'))
            if all(k in crop_coords for k in ['x', 'y', 'w', 'h']):
                print(f"✅ Sẽ crop ảnh theo tọa độ: {crop_coords}")
                break
            else:
                print("  Lỗi: Tọa độ phải chứa đủ các key 'x', 'y', 'w', 'h'.")
        except (json.JSONDecodeError, TypeError):
            print("  Lỗi: Định dạng tọa độ không hợp lệ. Vui lòng nhập lại.")

    while True:
        try:
            angle_str = input("▶️ Nhập góc xoay (ví dụ: -10, 5). Nhấn Enter để không xoay: ")
            angle = int(angle_str) if angle_str else 0
            break
        except ValueError:
            print("Lỗi: Vui lòng chỉ nhập số nguyên.")

    print("\n📜 Các mockup set có sẵn:")
    mockup_list = list(available_mockups.keys())
    for i, name in enumerate(mockup_list):
        print(f"  {i + 1}: {name}")

    while True:
        try:
            choices_str = input("▶️ Chọn các mockup set, cách nhau bởi dấu phẩy (ví dụ: 1, 3, 4): ")
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
    return crop_coords, angle, selected_mockups

def cleanup_input_directory(directory, processed_files_list):
    """Hỏi và xóa các file đã xử lý trong thư mục Input."""
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
    print("🚀 Bắt đầu quy trình của KTB-CREATOR...")
    
    for dir_path in [OUTPUT_DIR, INPUT_DIR, MOCKUP_DIR]:
        if not os.path.exists(dir_path): os.makedirs(dir_path)
    
    configs = load_config(CONFIG_FILE)
    if not configs: return
        
    defaults = configs.get("defaults", {})
    mockup_sets_config = configs.get("mockup_sets", {})
    exif_defaults = defaults.get("exif_defaults", {})
    output_format = defaults.get("global_output_format", "webp")
    color_threshold = defaults.get("color_detection_threshold", 128)
    
    images_to_process = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f)) and not f.startswith('.')]
    if not images_to_process:
        print("✅ Không có ảnh mới để xử lý."); return

    crop_coords, global_angle, selected_mockups = get_creator_inputs(mockup_sets_config)

    # --- LOGIC MỚI: CHỌN NGẪU NHIÊN VÀ CACHE MOCKUP (Hỗ trợ cả config cũ và mới) ---
    print("\n🎲 Đang chọn ngẫu nhiên 1 phiên bản cho mỗi mockup set...")
    mockup_cache = {}
    for name in selected_mockups:
        mockup_config = mockup_sets_config.get(name)
        if not mockup_config: continue

        # Logic thông minh cho mockup TRẮNG
        white_value = mockup_config.get("white")
        selected_white = None
        if isinstance(white_value, list) and white_value:
            selected_white = random.choice(white_value)
            print(f"  - Mockup '{name}' (trắng): đã chọn file ngẫu nhiên '{selected_white['file']}'")
        elif isinstance(white_value, str): # Hỗ trợ cấu trúc cũ
            selected_white = {"file": white_value, "coords": mockup_config.get("coords")}
            print(f"  - Mockup '{name}' (trắng): sử dụng file config cũ '{selected_white['file']}'")

        # Logic thông minh cho mockup ĐEN
        black_value = mockup_config.get("black")
        selected_black = None
        if isinstance(black_value, list) and black_value:
            selected_black = random.choice(black_value)
            print(f"  - Mockup '{name}' (đen): đã chọn file ngẫu nhiên '{selected_black['file']}'")
        elif isinstance(black_value, str): # Hỗ trợ cấu trúc cũ
            selected_black = {"file": black_value, "coords": mockup_config.get("coords")}
            print(f"  - Mockup '{name}' (đen): sử dụng file config cũ '{selected_black['file']}'")

        mockup_cache[name] = {
            "white_data": selected_white, "black_data": selected_black,
            "watermark_text": mockup_config.get("watermark_text"),
            "title_prefix_to_add": mockup_config.get("title_prefix_to_add", ""),
            "title_suffix_to_add": mockup_config.get("title_suffix_to_add", "")
        }
    print("-" * 50)
    
    images_for_output = {}
    total_processed_this_run = {}
    run_timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y%m%d_%H%M%S')

    for image_filename in images_to_process:
        print(f"\n--- 🖼️  Đang xử lý: {image_filename} ---")
        try:
            with Image.open(os.path.join(INPUT_DIR, image_filename)) as img:
                img_rgba = img.convert("RGBA")

                if crop_coords:
                    processed_img = crop_by_coords(img_rgba, crop_coords)
                    if not processed_img:
                        print("  - ⚠️ Lỗi khi crop, bỏ qua ảnh này."); continue
                else:
                    processed_img = img_rgba

                try:
                    pixel = processed_img.getpixel((1, processed_img.height - 2))
                    is_white = sum(pixel[:3]) / 3 > color_threshold
                except IndexError:
                    is_white = True
                
                # bg_removed = remove_background(processed_img)
                bg_removed = remove_background_advanced(processed_img)

                final_design = rotate_image(bg_removed, global_angle)
                trimmed_img = trim_transparent_background(final_design)
                if not trimmed_img:
                    print("  - ⚠️ Cảnh báo: Ảnh trống sau khi xử lý, bỏ qua."); continue

                for mockup_name in selected_mockups:
                    cached_data = mockup_cache.get(mockup_name)
                    if not cached_data: continue
                    
                    print(f"  - Áp dụng mockup: '{mockup_name}'")
                    
                    mockup_data_to_use = cached_data['white_data'] if is_white else cached_data['black_data']
                    if not mockup_data_to_use:
                        print(f"    - ⚠️ Cảnh báo: Không có tùy chọn mockup cho màu này. Bỏ qua."); continue

                    mockup_filename = mockup_data_to_use.get('file')
                    mockup_coords = mockup_data_to_use.get('coords')

                    if not mockup_filename or not mockup_coords:
                        print(f"    - ⚠️ Cảnh báo: Cấu hình mockup cho '{mockup_name}' bị lỗi. Bỏ qua."); continue

                    mockup_path = os.path.join(MOCKUP_DIR, mockup_filename)
                    if not os.path.exists(mockup_path):
                        print(f"    - ⚠️ Cảnh báo: Không tìm thấy file ảnh mockup '{mockup_filename}'. Bỏ qua."); continue
                    
                    with Image.open(mockup_path) as mockup_img:
                        final_mockup = apply_mockup(trimmed_img, mockup_img, mockup_coords)
                        watermark_desc = cached_data.get("watermark_text")
                        final_mockup_with_wm = add_watermark(final_mockup, watermark_desc, WATERMARK_DIR, FONT_FILE)
                        
                        prefix = cached_data.get("title_prefix_to_add", "")
                        suffix = cached_data.get("title_suffix_to_add", "")
                        base_name = os.path.splitext(image_filename)[0].replace('-', ' ').replace('_', ' ')
                        
                        final_filename_base = f"{prefix} {base_name} {suffix}".strip().replace('  ', ' ')
                        ext = f".{output_format}"
                        
                        MAX_FILENAME_LENGTH = 120
                        if len(final_filename_base) + len(ext) > MAX_FILENAME_LENGTH:
                            allowed_base_length = MAX_FILENAME_LENGTH - len(ext)
                            final_filename_base = final_filename_base[:allowed_base_length]
                        
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
        update_total_image_count(TOTAL_IMAGE_FILE, total_processed_this_run, "ktbcreator")
    
    print(f"\n--- ✨ Hoàn tất! ---")
    send_telegram_summary("ktbcreator", TOTAL_IMAGE_FILE, total_processed_this_run)

if __name__ == "__main__":
    main()