# utils/file_io.py
import os
import json
import re
import piexif
from datetime import datetime, timedelta
import random
import requests
import pytz

# --- CÁC HÀM ĐỌC/GHI FILE VÀ CONFIG ---

def load_config(config_path): # <--- Nhận vào config_path
    """Tải file config.json."""
    try:
        # SỬA LỖI: Dùng đúng tham số config_path đã được truyền vào
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Lỗi: Không tìm thấy tệp cấu hình tại '{config_path}'!")
        return {}
    except json.JSONDecodeError:
        print(f"Lỗi: File '{config_path}' không phải là file JSON hợp lệ.")
        return {}

def update_total_image_count(filepath, new_counts, tool_name):
    """
    Đọc, cộng dồn và ghi lại file TotalImage.txt với key chi tiết theo tool.
    """
    totals = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    key, count = line.strip().split(':', 1)
                    totals[key.strip()] = int(count.strip())
    except FileNotFoundError:
        print(f"Không tìm thấy file {os.path.basename(filepath)}, sẽ tạo file mới.")
    
    if not new_counts:
        print(f"Không có ảnh mới nào được tạo để cập nhật {os.path.basename(filepath)}.")
        return

    # Tạo key kết hợp: tool_name.mockup_name
    for mockup, count in new_counts.items():
        combined_key = f"{tool_name}.{mockup}"
        totals[combined_key] = totals.get(combined_key, 0) + count
        
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            # Sắp xếp theo key để file luôn gọn gàng
            for key in sorted(totals.keys()):
                f.write(f"{key}: {totals[key]}\n")
        print(f"📊 Đã cập nhật tổng số ảnh chi tiết trong {os.path.basename(filepath)}")
    except Exception as e:
        print(f"Lỗi khi ghi file {os.path.basename(filepath)}: {e}")


# --- CÁC HÀM XỬ LÝ METADATA VÀ TEXT ---
def pre_clean_filename(base_filename, regex_pattern):
    """
    Tiền xử lý tên file bằng một biểu thức chính quy (regex)
    được định nghĩa trong config.
    """
    if not regex_pattern:
        return base_filename
    try:
        return re.sub(regex_pattern, '', base_filename)
    except re.error as e:
        print(f"  - ⚠️ Cảnh báo: Lỗi biểu thức chính quy trong pre_clean_regex: {e}")
        return base_filename


def clean_title(title, keywords):
    """
    Dọn dẹp tiêu đề file dựa trên keywords, xử lý được cả tên file
    dùng gạch ngang (-) và gạch dưới (_).
    """
    # BƯỚC 1: Chuẩn hóa chuỗi đầu vào -> thay thế cả '_' và '-' bằng dấu cách
    normalized_title = title.replace('_', ' ').replace('-', ' ')
    
    # BƯỚC 2: Xây dựng pattern để tìm và xóa keywords (logic này vẫn hiệu quả)
    # Nó sẽ tìm các keywords như "t shirt", "t-shirt"...
    cleaned_keywords = sorted([r'(?:-|\s)?'.join([re.escape(p) for p in re.split(r'[- ]', k.strip())]) for k in keywords], key=len, reverse=True)
    pattern = r'\b(' + '|'.join(cleaned_keywords) + r')\b'

    # BƯỚC 3: Xóa các keywords trên chuỗi ĐÃ ĐƯỢC CHUẨN HÓA
    cleaned_str = re.sub(pattern, '', normalized_title, flags=re.IGNORECASE)
    
    # BƯỚC 4: Dọn dẹp các dấu cách thừa và trả về kết quả cuối cùng
    final_title = re.sub(r'\s+', ' ', cleaned_str).strip()
    
    return final_title

def should_globally_skip(filename, skip_keywords):
    """Kiểm tra filename có chứa từ khóa skip toàn cục không."""
    for keyword in skip_keywords:
        if re.search(r'\b' + re.escape(keyword) + r'\b', filename, re.IGNORECASE):
            print(f"Skipping (Global): '{filename}' chứa từ khóa bị cấm '{keyword}'.")
            return True
    return False

def _convert_to_gps(value, is_longitude):
    abs_value = abs(value)
    ref = ('E' if value >= 0 else 'W') if is_longitude else ('N' if value >= 0 else 'S')
    degrees = int(abs_value)
    minutes_float = (abs_value - degrees) * 60
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60
    return {
        'value': ((degrees, 1), (minutes, 1), (int(seconds_float * 100), 100)),
        'ref': ref.encode('ascii')
    }

def create_exif_data(prefix, final_filename, exif_defaults):
    domain_exif = prefix + ".com"
    digitized_time = datetime.now() - timedelta(hours=2)
    original_time = digitized_time - timedelta(seconds=random.randint(3600, 7500))
    digitized_str = digitized_time.strftime("%Y:%m:%d %H:%M:%S")
    original_str = original_time.strftime("%Y:%m:%d %H:%M:%S")
    try:
        zeroth_ifd = {
            piexif.ImageIFD.Artist: domain_exif.encode('utf-8'),
            piexif.ImageIFD.Copyright: domain_exif.encode('utf-8'),
            piexif.ImageIFD.ImageDescription: final_filename.encode('utf-8'),
            piexif.ImageIFD.Software: exif_defaults.get("Software", "Adobe Photoshop 25.0").encode('utf-8'),
            piexif.ImageIFD.DateTime: digitized_str.encode('utf-8'),
            piexif.ImageIFD.Make: exif_defaults.get("Make", "").encode('utf-8'),
            piexif.ImageIFD.Model: exif_defaults.get("Model", "").encode('utf-8'),
            piexif.ImageIFD.XPAuthor: domain_exif.encode('utf-16le'),
            piexif.ImageIFD.XPComment: final_filename.encode('utf-16le'),
            piexif.ImageIFD.XPSubject: final_filename.encode('utf-16le'),
            piexif.ImageIFD.XPKeywords: (prefix + ";" + "shirt;").encode('utf-16le')
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: original_str.encode('utf-8'),
            piexif.ExifIFD.DateTimeDigitized: digitized_str.encode('utf-8'),
            piexif.ExifIFD.FNumber: tuple(exif_defaults.get("FNumber", [0,1])),
            piexif.ExifIFD.ExposureTime: tuple(exif_defaults.get("ExposureTime", [0,1])),
            piexif.ExifIFD.ISOSpeedRatings: exif_defaults.get("ISOSpeedRatings", 0),
            piexif.ExifIFD.FocalLength: tuple(exif_defaults.get("FocalLength", [0,1]))
        }
        gps_ifd = {}
        lat, lon = exif_defaults.get("GPSLatitude"), exif_defaults.get("GPSLongitude")
        if lat is not None and lon is not None:
            gps_lat_data, gps_lon_data = _convert_to_gps(lat, False), _convert_to_gps(lon, True)
            gps_ifd.update({
                piexif.GPSIFD.GPSLatitude: gps_lat_data['value'], piexif.GPSIFD.GPSLatitudeRef: gps_lat_data['ref'],
                piexif.GPSIFD.GPSLongitude: gps_lon_data['value'], piexif.GPSIFD.GPSLongitudeRef: gps_lon_data['ref']
            })
        return piexif.dump({"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": gps_ifd})
    except Exception as e:
        print(f"Lỗi khi tạo dữ liệu EXIF: {e}")
        return b''

def find_mockup_image(mockup_dir, mockup_name, color):
    """
    Tìm file ảnh mockup trong thư mục được chỉ định.
    Hỗ trợ các định dạng .jpg, .webp, .png.
    """
    for ext in ['.jpg', '.webp', '.png']:
        filepath = os.path.join(mockup_dir, f"{mockup_name}_{color}{ext}")
        if os.path.exists(filepath):
            return filepath
    return None

# Thêm hàm mới này vào cuối file
def send_telegram_summary(tool_name, total_image_file_path, session_counts):
    """
    Tạo báo cáo chi tiết, phân nhóm theo tool và gửi qua Telegram.
    Báo cáo sẽ bao gồm cả các mockup không có ảnh mới (added: 0).
    """
    print(f"✈️  Chuẩn bị gửi báo cáo Telegram cho tool: {tool_name}...")
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("⚠️ Cảnh báo: Không tìm thấy biến môi trường Telegram. Bỏ qua."); return

    # 1. Tạo tiêu đề và timestamp
    header = f"--- Summary of Last {tool_name} Run ---"
    timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%d %H:%M:%S %z')
    
    report_body = ""
    try:
        # --- LOGIC MỚI ĐỂ TẠO BÁO CÁO ĐẦY ĐỦ ---

        # 2. Đọc tất cả dữ liệu tổng từ file
        all_totals = {}
        with open(total_image_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    key, count = line.strip().split(':', 1)
                    all_totals[key.strip()] = int(count.strip())

        # 3. Lấy tất cả các mockup liên quan đến tool này (cả cũ và mới)
        # Lấy từ lịch sử
        historical_mockups = {key.split('.', 1)[1] for key in all_totals if key.startswith(f"{tool_name}.")}
        # Lấy từ lần chạy hiện tại
        session_mockups = set(session_counts.keys())
        # Gộp lại và sắp xếp
        all_relevant_mockups = sorted(list(historical_mockups.union(session_mockups)))

        # 4. Tạo báo cáo chi tiết
        report_lines = []
        if not all_relevant_mockups:
            report_body = "Chưa có dữ liệu nào được xử lý cho tool này."
        else:
            for mockup in all_relevant_mockups:
                # Lấy số mới thêm, nếu không có thì mặc định là 0
                new_count = session_counts.get(mockup, 0)
                
                # Lấy tổng số từ file
                combined_key = f"{tool_name}.{mockup}"
                total_count = all_totals.get(combined_key, 0)
                
                report_lines.append(f"    {mockup}: {total_count} (added: {new_count})")
            report_body = "\n".join(report_lines)

    except FileNotFoundError:
        report_body = "File TotalImage.txt chưa được tạo."
    except Exception as e:
        report_body = f"Lỗi khi đọc file báo cáo: {e}"

    # 5. Ghép và gửi tin nhắn (không đổi)
    message = f"{header}\nTimestamp: {timestamp}\n\n{tool_name}:\n{report_body}"

    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat_id, 'text': message}, timeout=10)
        print("✅ Gửi báo cáo tới Telegram thành công.")
    except Exception as e:
        print(f"❌ Lỗi khi gửi báo cáo tới Telegram: {e}")