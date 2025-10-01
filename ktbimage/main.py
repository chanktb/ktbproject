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
FONT_FILE = os.path.join(PROJECT_ROOT, "fonts", "verdanab.ttf")

# Đường dẫn riêng của tool ktbimage
OUTPUT_DIR = os.path.join(TOOL_DIR, "OutputImage")
TOTAL_IMAGE_FILE = os.path.join(TOOL_DIR, "TotalImage.txt")
GENERATE_LOG_FILE = os.path.join(TOOL_DIR, "generate.log")

# Tải biến môi trường từ file .env ở thư mục gốc
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, '.env'))

# --- CÁC HÀM HỖ TRỢ RIÊNG CỦA TOOL NÀY ---

def cleanup_old_zips():
    """Hàm này chỉ tìm và xóa các file có đuôi .zip"""
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


# --- HÀM MAIN CHÍNH (PHIÊN BẢN HOÀN CHỈNH CUỐI CÙNG) ---
def main():
    configs = load_config(CONFIG_FILE)
    if not configs: return
    
    defaults = configs.get("defaults", {})
    # <<< SỬA LỖI: Định nghĩa output_mode ở đây >>>
    output_mode = defaults.get("ktbimage_output_mode", "zip")
    
    print(f"🚀 Bắt đầu quy trình tự động của KTB-IMAGE (Chế độ Output mặc định: {output_mode.upper()})")

    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    cleanup_old_zips()

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

    for domain, new_count in domains_to_process.items():
        print(f"\n==================== Bắt đầu xử lý {new_count} ảnh mới từ domain: {domain} ====================")
        
        domain_config = domains_configs.get(domain, {})
        # Lấy output_mode riêng của domain, nếu không có thì dùng output_mode chung
        output_mode_domain = domain_config.get("output_mode", output_mode)
        domain_rules = sorted(domain_config.get("rules", []), key=lambda x: len(x.get('pattern', '')), reverse=True)
        
        print(f"  - Chế độ output cho domain này: {output_mode_domain.upper()}")

        if not domain_rules:
            print(f"  - ⚠️ Cảnh báo: Không tìm thấy quy tắc ('rules') cho domain '{domain}'. Bỏ qua."); continue
        
        try:
            with open(os.path.join(CRAWLER_DOMAIN_DIR, f"{domain}.txt"), 'r', encoding='utf-8') as f:
                urls_to_process = f.read().splitlines()[:new_count]
        except FileNotFoundError:
            print(f"  - ❌ Lỗi: Không tìm thấy file URL cho domain {domain}. Bỏ qua."); continue
        
        images_for_domain = {}
        skipped_urls_for_domain = []
        processed_by_mockup = {}
        skipped_global_count, skipped_no_rule_count, skipped_by_rule_count = 0, 0, 0
        consecutive_error_count, ERROR_THRESHOLD = 0, 5

        for url in urls_to_process:
            filename = os.path.basename(url)
            print(f"\n--- Đang xử lý: {filename} ---")
            
            # --- LOGIC SKIP ĐÃ ĐƯỢC KIỂM TRA LẠI ---
            if should_globally_skip(filename, global_skip_keywords):
                skipped_global_count += 1 
                # Không thêm vào skipped_urls_for_domain theo đúng yêu cầu của bạn
                continue
            
            matched_rule = next((r for r in domain_rules if r.get("pattern", "") in filename), None)
            
            if not matched_rule:
                print("  - ⏩ Bỏ qua: Không có quy tắc phù hợp."); skipped_urls_for_domain.append(url); skipped_no_rule_count += 1; continue
            if matched_rule.get("action") == "skip":
                print("  - ⏩ Bỏ qua: Quy tắc có action là 'skip'."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue

            try:
                img = download_image(url)
                if not img:
                    skipped_urls_for_domain.append(url);
                    consecutive_error_count += 1
                    skipped_by_rule_count += 1
                    if consecutive_error_count >= ERROR_THRESHOLD:
                        print(f"  - ❌ Lỗi: Đã có {consecutive_error_count} lỗi tải ảnh liên tiếp. Bỏ qua các URL còn lại của domain {domain}.")
                        break
                    continue
                consecutive_error_count = 0
                
                # --- QUY TRÌNH SỬA LỖI ---
                
                # BƯỚC 1: XÁC ĐỊNH MÀU NỀN TRƯỚC TIÊN (LOGIC THÔNG MINH CÓ FALLBACK)
                sample_coords = matched_rule.get("color_sample_coords")
                is_white = True # Mặc định
                
                # Trường hợp 1: Dùng logic mới nếu có color_sample_coords
                if sample_coords:
                    is_white = determine_color_from_sample_area(img, sample_coords)
                # Trường hợp 2: Dùng logic fallback nếu không có
                else:
                    rect_coords_for_color = matched_rule.get("coords")
                    if rect_coords_for_color:
                        temp_crop = crop_by_coords(img, rect_coords_for_color)
                        if temp_crop:
                            try:
                                pixel = temp_crop.getpixel((1, temp_crop.height - 2))
                                is_white = sum(pixel[:3]) / 3 > 128
                            except IndexError:
                                is_white = True # Mặc định là trắng nếu ảnh crop quá nhỏ
                
                background_color = (255, 255, 255) if is_white else (0, 0, 0)
                print(f"  - Màu nền được xác định là: {'Trắng' if is_white else 'Đen'}")

                # BƯỚC 2: TẨY WATERMARK (NẾU CÓ) BẰNG MÀU NỀN VỪA TÌM ĐƯỢC
                erase_zones = matched_rule.get("erase_zones")
                if erase_zones:
                    print("  - Tẩy watermark bằng màu nền...")
                    img = erase_areas(img, erase_zones, background_color)

                # BƯỚC 3: CÁC BƯỚC XỬ LÝ CÒN LẠI NHƯ CŨ
                # Chọn đúng bộ tọa độ dựa trên màu đã xác định
                rect_coords = None
                if is_white and "coords_white" in matched_rule: rect_coords = matched_rule["coords_white"]
                elif not is_white and "coords_black" in matched_rule: rect_coords = matched_rule["coords_black"]
                else: rect_coords = matched_rule.get("coords")

                if not rect_coords:
                    print("  - ⏩ Bỏ qua: Không tìm thấy tọa độ phù hợp."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue
                
                angle = matched_rule.get("angle", 0)
                initial_crop = crop_by_coords(img, rect_coords)
                if not initial_crop:
                    skipped_urls_for_domain.append(url); continue
                
                if (matched_rule.get("skipWhite") and is_white) or (matched_rule.get("skipBlack") and not is_white):
                    print("  - ⏩ Bỏ qua theo quy tắc skip màu."); skipped_urls_for_domain.append(url); skipped_by_rule_count += 1; continue
                
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
                    
                    with Image.open(mockup_path) as mockup_img:
                        final_mockup = apply_mockup(trimmed_img, mockup_img, mockup_config.get("coords"))
                        watermark_desc = mockup_config.get("watermark_text")
                        final_mockup_with_wm = add_watermark(final_mockup, watermark_desc, WATERMARK_DIR, FONT_FILE)

                    base_filename = os.path.splitext(filename)[0]
                    pre_clean_pattern = matched_rule.get("pre_clean_regex")
                    if pre_clean_pattern:
                        print(f"  - Áp dụng pre_clean_regex: '{pre_clean_pattern}'")
                        base_filename = pre_clean_filename(base_filename, pre_clean_pattern)
                    
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
                    
                    images_for_domain.setdefault(mockup_name, []).append((final_filename, img_byte_arr.getvalue()))
                    processed_by_mockup[mockup_name] = processed_by_mockup.get(mockup_name, 0) + 1
            
            except Exception as e:
                print(f"  - ❌ Lỗi nghiêm trọng khi xử lý ảnh {url}: {e}")
                skipped_urls_for_domain.append(url)
                skipped_by_rule_count += 1

        # LƯU KẾT QUẢ CỦA DOMAIN
        if images_for_domain:
            if output_mode_domain == 'zip':
                for mockup_name, image_list in images_for_domain.items():
                    now = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh'))
                    zip_filename = f"{mockup_name}.{domain.split('.')[0]}.{now.strftime('%Y%m%d_%H%M%S')}.{len(image_list)}.zip"
                    zip_path = os.path.join(OUTPUT_DIR, zip_filename)
                    print(f"📦 Đang tạo file zip: {zip_path}")
                    with zipfile.ZipFile(zip_path, 'w') as zf:
                        for filename, data in image_list: zf.writestr(filename, data)
            elif output_mode_domain == 'folder':
                for mockup_name, image_list in images_for_domain.items():
                    now = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh'))
                    folder_name = f"{mockup_name}.{domain.split('.')[0]}.{now.strftime('%Y%m%d_%H%M%S')}.{len(image_list)}"
                    folder_path = os.path.join(OUTPUT_DIR, folder_name)
                    os.makedirs(folder_path, exist_ok=True)
                    print(f"📁 Đang tạo thư mục và lưu ảnh: {folder_path}")
                    for filename, data in image_list:
                        with open(os.path.join(folder_path, filename), 'wb') as f: f.write(data)

        # GHI FILE SKIP
        skip_file_name = None
        if skipped_urls_for_domain:
            if not os.path.exists(KTBIMG_INPUT_DIR): os.makedirs(KTBIMG_INPUT_DIR)
            timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y%m%d%H%M%S')
            skip_file_name = f"{domain}.{len(skipped_urls_for_domain)}.{timestamp}.txt"
            with open(os.path.join(KTBIMG_INPUT_DIR, skip_file_name), 'w', encoding='utf-8') as f:
                f.write('\n'.join(skipped_urls_for_domain))
            print(f"📝 Đã tạo file skip '{skip_file_name}' và đẩy vào Input của KTBIMG.")
        
        # CẬP NHẬT BÁO CÁO
        urls_summary[domain] = {
            'processed_by_mockup': processed_by_mockup, 'skipped_global': skipped_global_count,
            'skipped_no_rule': skipped_no_rule_count, 'skipped_by_rule': skipped_by_rule_count,
            'skip_file_generated': skip_file_name, 'total_to_process': new_count
        }
        for mockup, count in processed_by_mockup.items():
            total_processed_this_run[mockup] = total_processed_this_run.get(mockup, 0) + count

    # CÁC BƯỚC CUỐI CÙNG
    write_log(urls_summary)
    update_total_image_count(TOTAL_IMAGE_FILE, total_processed_this_run)
    print("\n✅ Hoàn thành xử lý và ghi log.")

    commit_and_push_changes_locally()
    send_telegram_log_locally()

    print("\n🎉 Quy trình đã hoàn tất! 🎉")

if __name__ == "__main__":
    main()