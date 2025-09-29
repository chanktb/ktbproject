# ktbimage/main.py

import os
import json
import re
from datetime import datetime
import pytz
from io import BytesIO
import zipfile
from dotenv import load_dotenv
import requests
import subprocess
import random
from PIL import Image

# Import các hàm từ module dùng chung
from utils.image_processing import (
    download_image,
    erase_areas,
    crop_by_coords,
    rotate_image,
    remove_background,
    remove_background_advanced,
    trim_transparent_background,
    apply_mockup,
    add_watermark,
    determine_color_from_sample_area
)
from utils.file_io import (
    load_config,
    clean_title,
    pre_clean_filename,
    should_globally_skip,
    _convert_to_gps,
    create_exif_data,
    update_total_image_count,
    find_mockup_image
)

# --- Cấu hình đường dẫn ---
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOL_DIR)
PARENT_DIR = os.path.dirname(PROJECT_ROOT)

# Đường dẫn tới repo imagecrawler
CRAWLER_REPO_PATH = os.path.join(PARENT_DIR, "imagecrawler")
CRAWLER_LOG_FILE = os.path.join(CRAWLER_REPO_PATH, "imagecrawler.log")
CRAWLER_DOMAIN_DIR = os.path.join(CRAWLER_REPO_PATH, "domain")

# Đường dẫn tới các tài nguyên và tool khác
KTBIMG_INPUT_DIR = os.path.join(PROJECT_ROOT, "ktbimg", "InputImage")
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.json")
MOCKUP_DIR = os.path.join(PROJECT_ROOT, "mockup")
WATERMARK_DIR = os.path.join(PROJECT_ROOT, "watermark")
FONT_FILE = os.path.join(PROJECT_ROOT, "verdanab.ttf")

# Đường dẫn riêng của tool ktbimage
OUTPUT_DIR = os.path.join(TOOL_DIR, "OutputImage")
TOTAL_IMAGE_FILE = os.path.join(TOOL_DIR, "TotalImage.txt")
GENERATE_LOG_FILE = os.path.join(TOOL_DIR, "generate.log")

# Tải biến môi trường từ file .env ở thư mục gốc
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, '.env'))

# --- CÁC HÀM HỖ TRỢ RIÊNG CỦA TOOL NÀY ---

def cleanup_old_zips():
    if not os.path.exists(OUTPUT_DIR): return
    print("🧹 Bắt đầu dọn dẹp các file zip cũ...")
    for filename in os.listdir(OUTPUT_DIR):
        if filename.endswith(".zip"):
            try:
                os.remove(os.path.join(OUTPUT_DIR, filename))
            except Exception as e:
                print(f"   - Lỗi khi xóa {filename}: {e}")

def commit_and_push_changes_locally():
    print("🚀 Bắt đầu quá trình commit và push...")
    try:
        os.chdir(PROJECT_ROOT)
        subprocess.run(['git', 'add', '.'], check=True)
        status_output = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True).stdout.strip()
        if not status_output:
            print("✅ Không có thay đổi mới để commit.")
            return False
        commit_message = f"Update via ktbimage tool - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        current_branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        print(f"   - Commit thành công. Bắt đầu push lên nhánh '{current_branch}'...")
        subprocess.run(['git', 'push', 'origin', current_branch], check=True)
        print("✅ Push thành công.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Lỗi trong quá trình Git: {e}")
        return False

def send_telegram_log_locally():
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️ Cảnh báo: Không tìm thấy biến môi trường Telegram. Bỏ qua việc gửi log.")
        return
    try:
        with open(GENERATE_LOG_FILE, "r", encoding="utf-8") as f:
            log_content = f.read() + "\nPush successful (from PC)."
        print("✈️  Đang gửi log tới Telegram...")
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat_id, 'text': log_content}, timeout=10)
        print("✅ Gửi log tới Telegram thành công.")
    except Exception as e:
        print(f"❌ Lỗi khi gửi log tới Telegram: {e}")

def write_log(urls_summary):
    """Ghi log chi tiết, bao gồm các loại skip khác nhau."""
    with open(GENERATE_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"--- Summary of Last Generation ---\n")
        f.write(f"Timestamp: {datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%d %H:%M:%S')} +07\n\n")
        if not urls_summary:
            f.write("No new images were processed in this run.\n")
        else:
            for domain, counts in sorted(urls_summary.items()):
                f.write(f"Domain: {domain}\n")
                if counts.get('processed_by_mockup'):
                    for mockup, count in sorted(counts['processed_by_mockup'].items()):
                        f.write(f"  - {mockup}: {count} images\n")
                f.write(f"  - Skipped (Global): {counts['skipped_global']} images\n")
                f.write(f"  - Skipped (No Rule): {counts['skipped_no_rule']} images\n")
                f.write(f"  - Skipped (Action/Error): {counts['skipped_by_rule']} images\n")
                if counts.get('skip_file_generated'):
                    f.write(f"  - Skip File -> ktbimg: {counts['skip_file_generated']}\n")
                f.write(f"  - Total Processed URLs: {counts['total_to_process']}\n\n")
    print(f"✅ Generation summary saved to {GENERATE_LOG_FILE}")


# --- HÀM MAIN CHÍNH ---
def main():
    print("🚀 Bắt đầu quy trình tự động của KTB-IMAGE...")
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    cleanup_old_zips()

    configs = load_config(CONFIG_FILE)
    if not configs: return
    
    defaults = configs.get("defaults", {})
    domains_configs = configs.get("domains", {})
    mockup_sets_config = configs.get("mockup_sets", {})
    exif_defaults = defaults.get("exif_defaults", {})
    title_clean_keywords = defaults.get("title_clean_keywords", [])
    global_skip_keywords = defaults.get("global_skip_keywords", [])

    try:
        with open(CRAWLER_LOG_FILE, 'r', encoding='utf-8') as f:
            log_content = f.read()
    except FileNotFoundError:
        print(f"❌ Lỗi: Không tìm thấy file log tại '{CRAWLER_LOG_FILE}'."); return

    domains_to_process = {p[0].strip(): int(p[1].split()[0]) for l in log_content.splitlines() if "New Images" in l for p in [l.split(":")] if int(p[1].split()[0]) > 0}
    
    if not domains_to_process:
        print("✅ Không có ảnh mới nào được tìm thấy trong log. Kết thúc."); return

    print(f"🔎 Tìm thấy {len(domains_to_process)} domain có ảnh mới.")
    urls_summary = {}
    total_processed_this_run = {}
    images_for_zip = {}

    for domain, new_count in domains_to_process.items():
        print(f"\n==================== Bắt đầu xử lý {new_count} ảnh mới từ domain: {domain} ====================")
        
        try:
            with open(os.path.join(CRAWLER_DOMAIN_DIR, f"{domain}.txt"), 'r', encoding='utf-8') as f:
                urls_to_process = f.read().splitlines()[:new_count]
        except FileNotFoundError:
            print(f"  - ❌ Lỗi: Không tìm thấy file URL cho domain {domain}. Bỏ qua."); continue
        
        domain_rules = sorted(domains_configs.get(domain, []), key=lambda x: len(x.get('pattern', '')), reverse=True)
        if not domain_rules:
            print(f"  - ⚠️ Cảnh báo: Không tìm thấy quy tắc cho domain '{domain}'."); continue

        skipped_urls_for_domain = []
        processed_by_mockup = {}
        skipped_global_count, skipped_no_rule_count, skipped_by_rule_count = 0, 0, 0

        # <<< THÊM MỚI: BIẾN ĐẾM LỖI VÀ NGƯỠNG LỖI >>>
        consecutive_error_count = 0
        ERROR_THRESHOLD = 5 # Dừng lại nếu có 5 lỗi tải ảnh liên tiếp

        for url in urls_to_process:
            filename = os.path.basename(url)
            print(f"\n--- Đang xử lý: {filename} ---")
            
            if should_globally_skip(filename, global_skip_keywords):
                skipped_global_count += 1  # Chỉ tăng bộ đếm, không thêm url vào danh sách skip
                print(f"  - ⏩ Bỏ qua (Global): '{filename}' khớp với từ khóa skip toàn cục.")
                continue
            
            matched_rule = next((r for r in domain_rules if r.get("pattern", "") in filename), None)
            
            if not matched_rule:
                print("  - ⏩ Bỏ qua: Không có quy tắc phù hợp."); skipped_urls_for_domain.append(url); skipped_no_rule_count += 1; continue
            if matched_rule.get("action") == "skip":
                print("  - ⏩ Bỏ qua: Quy tắc có action là 'skip'."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue

            try:
                img = download_image(url)
                if not img:
                    skipped_urls_for_domain.append(url)
                    consecutive_error_count += 1 # Tăng biến đếm lỗi
                    
                    # KIỂM TRA NẾU VƯỢT NGƯỠNG
                    if consecutive_error_count >= ERROR_THRESHOLD:
                        print(f"  - ❌ Lỗi: Đã có {consecutive_error_count} lỗi tải ảnh liên tiếp. Bỏ qua các URL còn lại của domain {domain}.")
                        break # Thoát khỏi vòng lặp của domain này
                    
                    continue # Chuyển sang URL tiếp theo
                
                # Nếu tải thành công, reset biến đếm lỗi về 0
                consecutive_error_count = 0
                # <<< BƯỚC MỚI: XÓA WATERMARK CŨ TRÊN ẢNH GỐC >>>
                erase_zones = matched_rule.get("erase_zones")
                if erase_zones:
                    print("  - Tẩy watermark cũ trên ảnh gốc...")
                    img = erase_areas(img, erase_zones)
                # <<< KẾT THÚC BƯỚC MỚI >>>
                sample_coords = matched_rule.get("color_sample_coords")
                angle = matched_rule.get("angle", 0)
                is_white = True
                
                if sample_coords:
                    is_white = determine_color_from_sample_area(img, sample_coords)
                    print(f"  - Màu áo (từ ảnh gốc) là: {'Trắng' if is_white else 'Đen'}")
                    rect_coords = matched_rule.get("coords_white") if is_white else matched_rule.get("coords_black")
                    if not rect_coords: rect_coords = matched_rule.get("coords")
                else:
                    rect_coords = matched_rule.get("coords")

                if not rect_coords:
                    print("  - ⏩ Bỏ qua: Không tìm thấy tọa độ phù hợp."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue
                
                initial_crop = crop_by_coords(img, rect_coords)
                if not initial_crop:
                    skipped_urls_for_domain.append(url); continue

                if not sample_coords: # Fallback logic
                    try:
                        pixel = initial_crop.getpixel((1, initial_crop.height - 2))
                        is_white = sum(pixel[:3]) / 3 > 128
                        print(f"  - Màu áo (từ ảnh crop) là: {'Trắng' if is_white else 'Đen'}")
                    except IndexError:
                        is_white = True
                
                if (matched_rule.get("skipWhite") and is_white) or (matched_rule.get("skipBlack") and not is_white):
                    print("  - ⏩ Bỏ qua theo quy tắc skip màu."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue
                
                # Cách 1: Dùng hàm cũ, nhanh hơn, chất lượng tiêu chuẩn
                #bg_removed = remove_background(initial_crop)

                # Cách 2: Dùng hàm mới, chậm hơn, chất lượng vượt trội
                bg_removed = remove_background_advanced(initial_crop)
                final_design = rotate_image(bg_removed, angle)
                trimmed_img = trim_transparent_background(final_design)
                if not trimmed_img:
                    print("  - ⚠️ Cảnh báo: Ảnh trống sau khi xử lý."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue
                
                mockup_names_to_use = matched_rule.get("mockup_sets_to_use", [])
                if not mockup_names_to_use:
                    print("  - ⏩ Bỏ qua: Quy tắc không chỉ định 'mockup_sets_to_use'."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue

                for mockup_name in mockup_names_to_use:
                    mockup_config = mockup_sets_config.get(mockup_name)
                    if not mockup_config: print(f"  - ⚠️ Cảnh báo: Không tìm thấy config cho mockup '{mockup_name}'."); continue
                    
                    mockup_path = find_mockup_image(MOCKUP_DIR, mockup_name, "white" if is_white else "black")
                    if not mockup_path: print(f"  - ⚠️ Cảnh báo: Không tìm thấy file ảnh mockup cho '{mockup_name}'."); continue
                    
                    mockup_img = Image.open(mockup_path)
                    final_mockup = apply_mockup(trimmed_img, mockup_img, mockup_config.get("coords"))
                    watermark_desc = mockup_config.get("watermark_text")
                    final_mockup_with_wm = add_watermark(final_mockup, watermark_desc, WATERMARK_DIR, FONT_FILE)

                    # --- LOGIC TẠO TÊN FILE (ĐÃ CẬP NHẬT) ---
                    base_filename = os.path.splitext(filename)[0]

                    # BƯỚC PHỤ: TIỀN XỬ LÝ TÊN FILE NẾU CÓ REGEX
                    pre_clean_pattern = matched_rule.get("pre_clean_regex")
                    if pre_clean_pattern:
                        print(f"  - Áp dụng pre_clean_regex: '{pre_clean_pattern}'")
                        base_filename = pre_clean_filename(base_filename, pre_clean_pattern)

                    # BƯỚC CHÍNH: DỌN DẸP TÊN FILE BẰNG KEYWORDS
                    cleaned_title = clean_title(base_filename, title_clean_keywords)
                    prefix = mockup_config.get("title_prefix_to_add", "")
                    suffix = mockup_config.get("title_suffix_to_add", "")
                    final_filename_base = f"{prefix} {cleaned_title} {suffix}".strip().replace('  ', ' ')
                    save_format, ext = ("WEBP", ".webp") if defaults.get("global_output_format", "webp") == "webp" else ("JPEG", ".jpg")
                    final_filename = f"{final_filename_base}{ext}"
                    
                    image_to_save = final_mockup_with_wm.convert('RGB')
                    exif_bytes = create_exif_data(mockup_name, final_filename, exif_defaults)
                    
                    img_byte_arr = BytesIO()
                    image_to_save.save(img_byte_arr, format=save_format, quality=90, exif=exif_bytes)
                    
                    images_for_zip.setdefault(mockup_name, {}).setdefault(domain, []).append((final_filename, img_byte_arr.getvalue()))
                    processed_by_mockup[mockup_name] = processed_by_mockup.get(mockup_name, 0) + 1
            
            except Exception as e:
                print(f"  - ❌ Lỗi nghiêm trọng khi xử lý ảnh {url}: {e}")
                skipped_urls_for_domain.append(url)
                skipped_by_rule_count += 1

        skip_file_name = None
        if skipped_urls_for_domain:
            if not os.path.exists(KTBIMG_INPUT_DIR): os.makedirs(KTBIMG_INPUT_DIR)
            timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y%m%d%H%M%S')
            total_skipped = len(skipped_urls_for_domain)
            skip_file_name = f"{domain}.{total_skipped}.{timestamp}.txt"
            skip_file_path = os.path.join(KTBIMG_INPUT_DIR, skip_file_name)
            with open(skip_file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(skipped_urls_for_domain))
            print(f"📝 Đã tạo file skip '{skip_file_name}' và đẩy vào Input của KTBIMG.")

        urls_summary[domain] = {
            'processed_by_mockup': processed_by_mockup, 'skipped_global': skipped_global_count,
            'skipped_no_rule': skipped_no_rule_count, 'skipped_by_rule': skipped_by_rule_count,
            'skip_file_generated': skip_file_name, 'total_to_process': new_count
        }
        for mockup, count in processed_by_mockup.items():
            total_processed_this_run[mockup] = total_processed_this_run.get(mockup, 0) + count

    if images_for_zip:
        for mockup_name, domains_dict in images_for_zip.items():
            for domain_name, image_list in domains_dict.items():
                if not image_list: continue
                now_vietnam = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh'))
                zip_filename = f"{mockup_name}.{domain_name.split('.')[0]}.{now_vietnam.strftime('%Y%m%d_%H%M%S')}.{len(image_list)}.zip"
                zip_path = os.path.join(OUTPUT_DIR, zip_filename)
                print(f"📦 Đang tạo file: {zip_path} với {len(image_list)} ảnh.")
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    for filename, data in image_list:
                        zf.writestr(filename, data)

    write_log(urls_summary)
    update_total_image_count(TOTAL_IMAGE_FILE, total_processed_this_run)
    print("\n✅ Hoàn thành tạo file zip và log.")

    #if commit_and_push_changes_locally():
    #    send_telegram_log_locally()
    commit_and_push_changes_locally()
    send_telegram_log_locally()
    print("\n🎉 Quy trình đã hoàn tất! 🎉")

if __name__ == "__main__":
    main()