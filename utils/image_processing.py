# utils/image_processing.py
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import requests
import os
from urllib.parse import quote  # <<< THÊM DÒNG NÀY
# --- CÁC HÀM XỬ LÝ ẢNH CỐT LÕI ---

def download_image(url):
    headers = {'User-Agent': 'Mozilla/5.0...', 'Referer': quote(url, safe='/:?=&')}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as e:
        print(f"Lỗi khi tải ảnh từ {url}: {e}")
        return None

def crop_by_coords(image, coords_dict):
    """Chỉ cắt một vùng chữ nhật từ ảnh dựa trên tọa độ {x, y, w, h}."""
    try:
        box = (
            coords_dict['x'], 
            coords_dict['y'], 
            coords_dict['x'] + coords_dict['w'], 
            coords_dict['y'] + coords_dict['h']
        )
        return image.crop(box)
    except Exception as e:
        print(f"  - ❌ Lỗi khi thực hiện crop: {e}")
        return None

def rotate_image(image, angle):
    """Chỉ xoay ảnh. Nếu angle = 0, trả về ảnh gốc."""
    if angle == 0:
        return image
    
    # Xoay ảnh và lấp đầy nền thừa bằng màu trong suốt
    return image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0,0,0,0))

def determine_color_from_sample_area(image, sample_coords):
    """
    Xác định màu nền (trắng/đen) bằng cách lấy trung bình độ sáng
    của 5 điểm trong một vùng chữ nhật cho trước trên ảnh gốc.
    """
    if not sample_coords:
        return True # Mặc định là trắng nếu không có vùng lấy mẫu

    try:
        x, y, w, h = sample_coords['x'], sample_coords['y'], sample_coords['w'], sample_coords['h']
        
        # Lấy 5 điểm: 4 góc và trung tâm của vùng lấy mẫu
        points_to_sample = [
            (x, y),
            (x + w - 1, y),
            (x, y + h - 1),
            (x + w - 1, y + h - 1),
            (x + w // 2, y + h // 2)
        ]

        brightness_values = []
        img_w, img_h = image.size

        for px, py in points_to_sample:
            # Đảm bảo điểm lấy mẫu nằm trong ảnh
            if 0 <= px < img_w and 0 <= py < img_h:
                pixel = image.getpixel((px, py))
                brightness = sum(pixel[:3]) / 3
                brightness_values.append(brightness)
        
        if not brightness_values:
            return True # Trả về trắng nếu không lấy được mẫu nào

        # Tính độ sáng trung bình và quyết định màu
        avg_brightness = sum(brightness_values) / len(brightness_values)
        return avg_brightness > 128

    except (KeyError, IndexError):
        print("  - ⚠️ Cảnh báo: 'color_sample_coords' không hợp lệ.")
        return True # Mặc định là trắng nếu có lỗi

def remove_background(design_img):
    """Xóa nền của ảnh thiết kế bằng logic 'magic wand' từ 8 điểm."""
    design_w, design_h = design_img.size
    pixels = design_img.load()
    visited = set()
    start_points = [
        (0, 0), (design_w - 1, 0), (0, design_h - 1), (design_w - 1, design_h - 1),
        (design_w // 2, 0), (design_w // 2, design_h - 1), 
        (0, design_h // 2), (design_w - 1, design_h // 2)
    ]
    for start_x, start_y in start_points:
        if not (0 <= start_x < design_w and 0 <= start_y < design_h) or (start_x, start_y) in visited:
            continue
        try:
            seed_pixel = design_img.getpixel((start_x, start_y))
        except IndexError:
            continue
        if seed_pixel[3] == 0:
            continue
        seed_r, seed_g, seed_b = seed_pixel[:3]
        stack = [(start_x, start_y)]
        while stack:
            x, y = stack.pop()
            if not (0 <= x < design_w and 0 <= y < design_h) or (x, y) in visited:
                continue
            current_r, current_g, current_b = pixels[x, y][:3]
            if all(abs(c1 - c2) < 30 for c1, c2 in zip((current_r, current_g, current_b), (seed_r, seed_g, seed_b))):
                pixels[x, y] = (0, 0, 0, 0)
                visited.add((x, y))
                stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    return design_img

def trim_transparent_background(image):
    """Cắt bỏ toàn bộ phần nền trong suốt thừa xung quanh vật thể."""
    bbox = image.getbbox()
    if bbox:
        return image.crop(bbox)
    return None

def apply_mockup(trimmed_design, mockup_img, mockup_coords):
    """
    Ghép design vào mockup với logic căn chỉnh động:
    - Resize để vừa khít với khung dán (theo chiều rộng hoặc cao).
    - Nếu thừa chiều cao, dán sát lề trên.
    - Nếu thừa chiều rộng, căn giữa theo chiều ngang.
    """
    # Lấy thông số của khung mockup và design
    mockup_frame_w = mockup_coords['w']
    mockup_frame_h = mockup_coords['h']
    obj_w, obj_h = trimmed_design.size

    # Tính toán tỷ lệ co giãn theo từng chiều
    scale_w = mockup_frame_w / obj_w
    scale_h = mockup_frame_h / obj_h

    # Chọn tỷ lệ nhỏ hơn để đảm bảo design nằm trọn trong khung
    scale_ratio = min(scale_w, scale_h)

    # Kích thước cuối cùng sau khi resize
    final_w = int(obj_w * scale_ratio)
    final_h = int(obj_h * scale_ratio)
    resized_design = trimmed_design.resize((final_w, final_h), Image.Resampling.LANCZOS)

    # === LOGIC CĂN CHỈNH ĐỘNG ===
    # Mặc định dán lên trên cùng
    paste_y = mockup_coords['y']
    
    # Chỉ căn giữa theo chiều ngang KHI design thừa chiều rộng
    # (tức là chiều cao là yếu tố quyết định tỷ lệ co giãn)
    if scale_h < scale_w:
        paste_x = mockup_coords['x'] + (mockup_frame_w - final_w) // 2
    else: # Ngược lại, dán sát lề trái
        paste_x = mockup_coords['x']

    # Thực hiện ghép ảnh
    final_mockup = mockup_img.copy().convert("RGBA")
    final_mockup.paste(resized_design, (paste_x, paste_y), resized_design)
    
    return final_mockup

def add_watermark(image_to_watermark, watermark_descriptor, watermark_dir, font_path):
    """
    Thêm chữ ký vào ảnh. Ưu tiên tìm file ảnh trong folder Watermark,
    nếu không thấy sẽ coi descriptor là text.
    """
    if not watermark_descriptor:
        return image_to_watermark

    # Bước 1: Kiểm tra xem có file ảnh watermark tồn tại không
    potential_path = os.path.join(watermark_dir, watermark_descriptor)

    # --- Xử lý watermark dạng ảnh nếu file tồn tại ---
    if os.path.exists(potential_path):
        try:
            watermark_img = Image.open(potential_path).convert("RGBA")
            
            # Logic resize watermark (giữ nguyên như cũ)
            max_wm_width = 280
            wm_w, wm_h = watermark_img.size
            if wm_w > max_wm_width:
                scale = max_wm_width / wm_w
                watermark_img = watermark_img.resize((int(wm_w * scale), int(wm_h * scale)), Image.Resampling.LANCZOS)
            
            wm_w, wm_h = watermark_img.size
            paste_x = image_to_watermark.width - wm_w - 20
            paste_y = image_to_watermark.height - wm_h - 50
            image_to_watermark.paste(watermark_img, (paste_x, paste_y), watermark_img)

        except Exception as e:
            print(f"Lỗi khi xử lý ảnh watermark: {e}")
    
    # --- Xử lý watermark dạng chữ nếu không tìm thấy file ---
    else:
        draw = ImageDraw.Draw(image_to_watermark)
        try:
            font = ImageFont.truetype(font_path, 100)
        except IOError:
            font = ImageFont.load_default()
            
        text_bbox = draw.textbbox((0, 0), watermark_descriptor, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        text_x = image_to_watermark.width - text_w - 20
        text_y = image_to_watermark.height - text_h - 50
        draw.text((text_x, text_y), watermark_descriptor, fill=(0, 0, 0, 128), font=font)
            
    return image_to_watermark