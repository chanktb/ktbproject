# ktbimg/main.py

import os
import json
from datetime import datetime
import pytz
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

# Import các hàm từ module dùng chung
from utils.image_processing import (
    download_image,
    crop_by_coords,
    rotate_image,
    remove_background,
    remove_background_advanced,
    trim_transparent_background,
    apply_mockup,
    add_watermark
)
from utils.file_io import (
    load_config,
    clean_title,
    create_exif_data,
    update_total_image_count,
    find_mockup_image,
    send_telegram_summary
)

# --- Cấu hình đường dẫn ---
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOL_DIR)

# Tải biến môi trường từ file .env ở thư mục gốc của project
# Thao tác này sẽ nạp các biến TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID vào môi trường
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, '.env'))

# Đường dẫn tới các tài nguyên chung
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.json")
MOCKUP_DIR = os.path.join(PROJECT_ROOT, "mockup")
WATERMARK_DIR = os.path.join(PROJECT_ROOT, "watermark")
FONT_FILE = os.path.join(PROJECT_ROOT, "verdanab.ttf")

# Đường dẫn riêng của tool này
INPUT_DIR = os.path.join(TOOL_DIR, "InputImage")
OUTPUT_DIR = os.path.join(TOOL_DIR, "OutputImage")
TOTAL_IMAGE_FILE = os.path.join(TOOL_DIR, "TotalImage.txt")

# --- CÁC HÀM HỖ TRỢ RIÊNG CỦA TOOL NÀY ---
def get_user_inputs(available_mockups):
    """Hỏi người dùng các tùy chọn cho tool KTBIMG."""
    print("-" * 50)
    
    # Hỏi pattern
    pattern = input("▶️ Nhập pattern để lọc file, ví dụ -shirt.jpg (nhấn Enter để xử lý tất cả): ")

    # Hỏi tọa độ crop
    while True:
        try:
            coords_str = input('▶️ Nhập tọa độ vùng crop (ví dụ: {"x": 428, "y": 331, "w": 401, "h": 455}): ')
            crop_coords = json.loads(coords_str.replace("'", '"'))
            if all(k in crop_coords for k in ['x', 'y', 'w', 'h']):
                break
            else:
                print("Lỗi: Tọa độ phải chứa đủ các key 'x', 'y', 'w', 'h'.")
        except (json.JSONDecodeError, TypeError):
            print("Lỗi: Định dạng tọa độ không hợp lệ.")

    # Hỏi góc xoay
    while True:
        try:
            angle_str = input("▶️ Nhập góc xoay (ví dụ: -10, 5). Nhấn Enter để không xoay: ")
            angle = int(angle_str) if angle_str else 0
            break
        except ValueError:
            print("Lỗi: Vui lòng chỉ nhập số nguyên.")
    
    # Hỏi skip theo màu
    skip_choice = input("▶️ Nhập '1' để skip ảnh TRẮNG, '2' để skip ảnh ĐEN (Enter để không skip): ")
    skip_white, skip_black = skip_choice == '1', skip_choice == '2'

    # Hỏi chọn mockup set
    print("\n📜 Các mockup set có sẵn:")
    mockup_list = list(available_mockups.keys())
    for i, name in enumerate(mockup_list):
        print(f"  {i + 1}: {name}")

    while True:
        try:
            choices_str = input("▶️ Chọn các mockup set cần dùng, cách nhau bởi dấu phẩy (ví dụ: 1,3,4): ")
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
    return pattern, crop_coords, angle, skip_white, skip_black, selected_mockups

# --- HÀM MAIN CHÍNH ---
def main():
    print("🚀 Bắt đầu quy trình tương tác của KTB-IMG...")

    for dir_path in [OUTPUT_DIR, INPUT_DIR, MOCKUP_DIR]:
        if not os.path.exists(dir_path): os.makedirs(dir_path)
    
    configs = load_config(CONFIG_FILE)
    if not configs: return
        
    defaults = configs.get("defaults", {})
    mockup_sets_config = configs.get("mockup_sets", {})
    exif_defaults = defaults.get("exif_defaults", {})
    output_format = defaults.get("global_output_format", "webp")
    title_clean_keywords = defaults.get("title_clean_keywords", [])

    input_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.txt')]
    if not input_files:
        print(f"⚠️  Không có file .txt nào trong thư mục '{INPUT_DIR}' để xử lý."); return
    
    total_processed_this_run = {}

    for txt_filename in input_files:
        print(f"\n==================== BẮT ĐẦU XỬ LÝ FILE: {txt_filename} ====================")

        try:
            with open(os.path.join(INPUT_DIR, txt_filename), 'r', encoding='utf-8') as f:
                all_urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"  - ❌ Lỗi khi đọc file {txt_filename}: {e}"); continue
        
        if not all_urls:
            print("  - ⚠️  File txt trống, bỏ qua."); continue

        # Hỏi người dùng MỘT LẦN cho mỗi file .txt
        pattern, crop_coords, angle, skip_white, skip_black, selected_mockups = get_user_inputs(mockup_sets_config)
        
        # Lọc URL theo pattern
        urls_to_process = [url for url in all_urls if not pattern or pattern in os.path.basename(url)]
        if not urls_to_process:
            print(f"  - ⚠️ Không có URL nào trong file khớp với pattern '{pattern}'."); continue
        
        print(f"🔎 Tìm thấy {len(urls_to_process)} URL hợp lệ, bắt đầu xử lý...")
        images_for_output = {}
        run_timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y%m%d_%H%M%S')

        for url in urls_to_process:
            filename = os.path.basename(url)
            print(f"\n--- 🖼️  Đang xử lý: {filename} ---")
            
            try:
                img = download_image(url)
                if not img: continue
                
                # --- QUY TRÌNH XỬ LÝ ẢNH CHUẨN ---
                # 1. CẮT ẢNH GỐC THEO TỌA ĐỘ NGƯỜI DÙNG NHẬP
                initial_crop = crop_by_coords(img, crop_coords)
                if not initial_crop: continue

                # 2. XÁC ĐỊNH MÀU & TÁCH NỀN
                try:
                    pixel = initial_crop.getpixel((1, initial_crop.height - 2))
                    is_white = sum(pixel[:3]) / 3 > 128
                except IndexError:
                    is_white = True
                
                if (skip_white and is_white) or (skip_black and not is_white):
                    print(f"  - ⏩ Bỏ qua theo tùy chọn skip màu."); continue
                    
                # Cách 1: Dùng hàm cũ, nhanh hơn, chất lượng tiêu chuẩn
                bg_removed = remove_background(initial_crop)

                # Cách 2: Dùng hàm mới, chậm hơn, chất lượng vượt trội
                #bg_removed = remove_background_advanced(initial_crop)

                # 3. XOAY ẢNH (THEO GÓC NGƯỜI DÙNG NHẬP)
                final_design = rotate_image(bg_removed, angle)
                
                # 4. CẮT GỌN NỀN THỪA LẦN CUỐI
                trimmed_img = trim_transparent_background(final_design)
                if not trimmed_img:
                    print("  - ⚠️ Cảnh báo: Ảnh trống sau khi xử lý."); continue

                # 5. GHÉP VÀO CÁC MOCKUP ĐÃ CHỌN
                for mockup_name in selected_mockups:
                    mockup_config = mockup_sets_config.get(mockup_name)
                    if not mockup_config: print(f"  - ⚠️ Cảnh báo: Không tìm thấy config cho mockup '{mockup_name}'."); continue

                    mockup_path = find_mockup_image(MOCKUP_DIR, mockup_name, "white" if is_white else "black")
                    if not mockup_path: print(f"  - ⚠️ Cảnh báo: Không tìm thấy file ảnh mockup cho '{mockup_name}'."); continue
                    
                    with Image.open(mockup_path) as mockup_img:
                        final_mockup = apply_mockup(trimmed_img, mockup_img, mockup_config.get("coords"))
                        
                        watermark_desc = mockup_config.get("watermark_text")
                        final_mockup_with_wm = add_watermark(final_mockup, watermark_desc, WATERMARK_DIR, FONT_FILE)
                        
                        # 6. TẠO TÊN FILE, EXIF VÀ LƯU VÀO BỘ NHỚ
                        base_filename = os.path.splitext(filename)[0]
                        cleaned_title = clean_title(base_filename, title_clean_keywords)
                        prefix = mockup_config.get("title_prefix_to_add", "")
                        suffix = mockup_config.get("title_suffix_to_add", "")
                        
                        final_filename_base = f"{prefix} {cleaned_title} {suffix}".strip().replace('  ', ' ')
                        ext = f".{output_format}"
                        final_filename = f"{final_filename_base}{ext}"

                        image_to_save = final_mockup_with_wm.convert('RGB')
                        exif_bytes = create_exif_data(mockup_name, final_filename, exif_defaults)
                        
                        img_byte_arr = BytesIO()
                        save_format = "WEBP" if output_format == "webp" else "JPEG"
                        image_to_save.save(img_byte_arr, format=save_format, quality=90, exif=exif_bytes)
                        
                        images_for_output.setdefault(mockup_name, []).append((final_filename, img_byte_arr.getvalue()))
                        total_processed_this_run.setdefault(mockup_name, 0)
                        total_processed_this_run[mockup_name] += 1
                        print(f"    -> Đã xử lý cho mockup: '{mockup_name}'")

            except Exception as e:
                print(f"❌ Lỗi nghiêm trọng khi xử lý file {filename}: {e}")

        # --- LƯU KẾT QUẢ CHO FILE .TXT HIỆN TẠI ---
        if images_for_output:
            print(f"\n--- 💾 Bắt đầu lưu ảnh từ file {txt_filename} ---")
            for mockup_name, image_list in images_for_output.items():
                output_subdir_name = f"{mockup_name}.{run_timestamp}.{len(image_list)}"
                output_path = os.path.join(OUTPUT_DIR, output_subdir_name)
                os.makedirs(output_path, exist_ok=True)
                
                print(f"  - Đang tạo và lưu {len(image_list)} ảnh vào: {output_path}")
                for filename, data in image_list:
                    with open(os.path.join(output_path, filename), 'wb') as f:
                        f.write(data)
        # <<< THÊM MỚI: HỎI VÀ XÓA FILE INPUT ĐÃ XONG >>>
        print("-" * 50)
        choice = input(f"Xử lý file '{txt_filename}' hoàn tất. Xóa file này? (Enter = XÓA, 'n' = Giữ lại): ")
        if choice.lower() != 'n':
            try:
                os.remove(os.path.join(INPUT_DIR, txt_filename))
                print(f"  -> ✅ Đã xóa file '{txt_filename}'.")
            except OSError as e:
                print(f"  -> ❌ Lỗi khi xóa file: {e}")
        else:
            print(f"  -> 💾 Đã giữ lại file '{txt_filename}'.")

    # --- CẬP NHẬT FILE ĐẾM TỔNG SAU KHI XONG HẾT ---
    if total_processed_this_run:
        update_total_image_count(TOTAL_IMAGE_FILE, total_processed_this_run)
    
    print("\n🎉 Quy trình đã hoàn tất tất cả các file! 🎉")
    send_telegram_summary("ktbimg", TOTAL_IMAGE_FILE)

if __name__ == "__main__":
    main()