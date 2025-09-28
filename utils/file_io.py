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

def update_total_image_count(filepath, new_counts): # <--- Nhận vào filepath
    """Đọc, cộng dồn và ghi lại file TotalImage.txt."""
    totals = {}
    try:
        # SỬA LỖI: Dùng đúng tham số filepath đã được truyền vào
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    parts = line.split(':', 1)
                    try:
                        totals[parts[0].strip()] = int(parts[1].strip())
                    except (ValueError, IndexError):
                        pass
    except FileNotFoundError:
        print(f"Không tìm thấy file {os.path.basename(filepath)}, sẽ tạo file mới.")
    
    if not new_counts:
        print(f"Không có ảnh mới nào được tạo để cập nhật {os.path.basename(filepath)}.")
        return

    for mockup, count in new_counts.items():
        totals[mockup] = totals.get(mockup, 0) + count
        
    try:
        # SỬA LỖI: Dùng đúng tham số filepath đã được truyền vào
        with open(filepath, 'w', encoding='utf-8') as f:
            for mockup in sorted(totals.keys()):
                f.write(f"{mockup}: {totals[mockup]}\n")
        print(f"📊 Đã cập nhật tổng số ảnh trong {os.path.basename(filepath)}")
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
    """Dọn dẹp tiêu đề file dựa trên keywords."""
    cleaned_keywords = sorted([r'(?:-|\s)?'.join([re.escape(p) for p in re.split(r'[- ]', k.strip())]) for k in keywords], key=len, reverse=True)
    pattern = r'\b(' + '|'.join(cleaned_keywords) + r')\b'
    return re.sub(r'\s+', ' ', re.sub(pattern, '', title, flags=re.IGNORECASE).replace('-', ' ')).strip()

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
def send_telegram_summary(tool_name, total_image_file_path):
    """
    Gửi báo cáo tóm tắt chứa nội dung của file TotalImage.txt qua Telegram.
    """
    print(f"✈️  Chuẩn bị gửi báo cáo Telegram cho tool: {tool_name}...")
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID_CN")

    if not token or not chat_id:
        print("⚠️ Cảnh báo: Không tìm thấy biến môi trường Telegram. Bỏ qua việc gửi báo cáo.")
        return

    # 1. Tạo tiêu đề và timestamp
    header = f"--- Summary of Last {tool_name} Run ---"
    timestamp = datetime.now(pytz.timezone('Asia/Ho_Chi_Minh')).strftime('%Y-%m-%d %H:%M:%S %z')

    # 2. Đọc nội dung file TotalImage.txt
    try:
        with open(total_image_file_path, 'r', encoding='utf-8') as f:
            total_content = f.read().strip()
        if not total_content:
            total_content = "Chưa có dữ liệu."
    except FileNotFoundError:
        total_content = "File TotalImage.txt chưa được tạo."

    # 3. Ghép thành nội dung tin nhắn cuối cùng
    message = f"{header}\nTimestamp: {timestamp}\n\n{total_content}"

    # 4. Gửi tin nhắn
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={'chat_id': chat_id, 'text': message},
            timeout=10
        )
        response.raise_for_status()
        print("✅ Gửi báo cáo tới Telegram thành công.")
    except Exception as e:
        print(f"❌ Lỗi khi gửi báo cáo tới Telegram: {e}")