# utils/image_processing.py
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
import requests
import os
from urllib.parse import quote
import cv2
import numpy as np
import random

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

def erase_areas(image_pil, zones, background_color):
    """
    Nhận vào một ảnh, một danh sách vùng, và một màu nền.
    "Sơn" lại các vùng đó bằng màu nền đã cho.
    """
    if not zones or not isinstance(zones, list):
        return image_pil

    # Không cần convert sang RGBA nữa vì chúng ta chỉ fill màu RGB
    img_copy = image_pil.copy()
    draw = ImageDraw.Draw(img_copy)

    for zone in zones:
        try:
            x, y, w, h = zone['x'], zone['y'], zone['w'], zone['h']
            rectangle_coords = [x, y, x + w, y + h]
            
            # Vẽ một hình chữ nhật với màu nền được truyền vào
            draw.rectangle(rectangle_coords, fill=background_color)
            
        except (KeyError, TypeError):
            print(f"  - ⚠️ Cảnh báo: Cấu trúc zone không hợp lệ, bỏ qua: {zone}")
            continue
            
    return img_copy

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

def remove_background_advanced(design_img, tolerance=30, refine_size=8000):
    """
    Hàm tách nền cao cấp, kết hợp 3 kỹ thuật từ ktbrembg:
    1. Tách nền Magic Wand lấy mẫu 4 góc.
    2. Tinh chỉnh viền kiểu vector.
    3. Làm nét ảnh.
    """
    print("✨ Áp dụng thuật toán tách nền cao cấp...")
    try:
        # --- Chuyển đổi từ PIL sang OpenCV ---
        img_cv = cv2.cvtColor(np.array(design_img), cv2.COLOR_RGBA2BGRA)

        # --- Bước 1: Tách nền bằng Magic Wand toàn cục ---
        bgr_image = img_cv[:,:,:3]
        h, w = bgr_image.shape[:2]

        sample_size = min(10, h // 10, w // 10)
        corners = [
            bgr_image[0:sample_size, 0:sample_size],
            bgr_image[0:sample_size, w-sample_size:w],
            bgr_image[h-sample_size:h, 0:sample_size],
            bgr_image[h-sample_size:h, w-sample_size:w]
        ]
        corner_colors = [np.mean(corner, axis=(0, 1)) for corner in corners]
        
        combined_mask = np.zeros((h, w), np.uint8)
        for color in corner_colors:
            
            # <<< SỬA LỖI: Thêm dtype=np.uint8 để ép kiểu dữ liệu về số nguyên 8-bit >>>
            lower = np.array([max(0, c - tolerance) for c in color], dtype=np.uint8)
            upper = np.array([min(255, c + tolerance) for c in color], dtype=np.uint8)
            
            mask = cv2.inRange(bgr_image, lower, upper)
            combined_mask = cv2.bitwise_or(combined_mask, mask)

        foreground_mask = cv2.bitwise_not(combined_mask)
        print("   - Tách nền 4 góc thành công.")

        # --- Bước 2: Tinh chỉnh viền sắc nét ---
        # (Phần này giữ nguyên)
        scale_factor = max(1, int(refine_size / max(h, w, 1)))
        if scale_factor > 1:
            h_up, w_up = h * scale_factor, w * scale_factor
            upscaled_mask = cv2.resize(foreground_mask, (w_up, h_up), interpolation=cv2.INTER_CUBIC)
            _, binary_mask = cv2.threshold(upscaled_mask, 127, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(binary_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            perfect_mask = np.zeros((h_up, w_up), dtype=np.uint8)
            cv2.drawContours(perfect_mask, contours, -1, (255), thickness=cv2.FILLED)
            refined_mask = cv2.resize(perfect_mask, (w, h), interpolation=cv2.INTER_AREA)
            _, refined_mask = cv2.threshold(refined_mask, 127, 255, cv2.THRESH_BINARY)
            print("   - Tinh chỉnh viền thành công.")
        else:
            refined_mask = foreground_mask

        # --- Bước 3: Áp dụng mặt nạ và làm nét ---
        # (Phần này giữ nguyên)
        bgra_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2BGRA)
        bgra_image[:, :, 3] = refined_mask
        bgr_part = bgra_image[:, :, :3]
        alpha_part = bgra_image[:, :, 3]
        blurred = cv2.GaussianBlur(bgr_part, (0, 0), 3)
        sharpened_bgr = cv2.addWeighted(bgr_part, 1.5, blurred, -0.5, 0)
        final_cv_image = cv2.merge([sharpened_bgr, alpha_part])
        print("   - Làm nét ảnh thành công.")

        # --- Chuyển đổi ngược lại sang PIL để trả về ---
        return Image.fromarray(cv2.cvtColor(final_cv_image, cv2.COLOR_BGRA2RGBA))

    except Exception as e:
        print(f"  - ❌ Lỗi trong quá trình xử lý ảnh nâng cao: {e}")
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

def stylize_image(image_pil, posterize_level=4, feather_margin=0.15):
    """
    "Trừu tượng hóa" một bức ảnh bằng cách giảm màu và làm mờ viền.
    - posterize_level: Càng thấp, màu càng ít và càng "trừu tượng".
    - feather_margin: Tỷ lệ viền mờ (vd: 0.15 = 15% cạnh ngoài sẽ bị làm mờ).
    """
    # Bước 1: Posterize - Giảm số lượng màu
    # Chuyển sang chế độ 'P' với số màu giới hạn, sau đó chuyển lại RGBA
    posterized_img = image_pil.convert('P', palette=Image.ADAPTIVE, colors=2**posterize_level).convert('RGBA')

    # Bước 2: Tạo mặt nạ để làm mờ viền (Feathered Edges)
    width, height = posterized_img.size
    mask = Image.new('L', (width, height), 0) # Tạo mask đen hoàn toàn
    draw = ImageDraw.Draw(mask)

    # Vẽ một hình chữ nhật trắng nhỏ hơn ở giữa
    margin_w = int(width * feather_margin)
    margin_h = int(height * feather_margin)
    draw.rectangle(
        (margin_w, margin_h, width - margin_w, height - margin_h),
        fill=255
    )

    # Làm mờ mạnh cái mask để tạo ra gradient
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(margin_w, margin_h) // 2))

    # Áp dụng mask vào kênh alpha của ảnh
    posterized_img.putalpha(mask)
    
    return posterized_img

def add_hashtag_text(image_pil, filename, fonts_dir, text_margin=20):
    """
    Ghép text hashtag (#filename) vào bên dưới ảnh.
    """
    # 1. Chuẩn bị text và font
    text_to_add = "#" + os.path.splitext(filename)[0].replace('-', ' ').replace('_', ' ')
    
    try:
        font_files = [f for f in os.listdir(fonts_dir) if f.lower().endswith('.ttf')]
        if not font_files:
            raise FileNotFoundError("Không tìm thấy file font nào.")
        random_font_path = os.path.join(fonts_dir, random.choice(font_files))
        
        # Tự động điều chỉnh kích thước font
        font_size = max(40, int(image_pil.width / 10))
        font = ImageFont.truetype(random_font_path, font_size)
    except Exception as e:
        print(f"  - ⚠️ Lỗi font: {e}. Dùng font mặc định.")
        font = ImageFont.load_default()

    # 2. Tính toán kích thước
    draw = ImageDraw.Draw(image_pil) # Dùng tạm để tính toán
    text_bbox = draw.textbbox((0, 0), text_to_add, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # 3. Tạo canvas mới lớn hơn để chứa cả ảnh và text
    new_height = image_pil.height + text_height + text_margin
    new_width = max(image_pil.width, text_width)
    final_canvas = Image.new('RGBA', (new_width, new_height), (0,0,0,0))
    
    # 4. Ghép ảnh và text vào canvas
    # Dán ảnh vào trên
    img_paste_x = (new_width - image_pil.width) // 2
    final_canvas.paste(image_pil, (img_paste_x, 0), image_pil)
    
    # Vẽ text ở dưới
    text_draw = ImageDraw.Draw(final_canvas)
    text_paste_x = (new_width - text_width) // 2
    text_paste_y = image_pil.height + text_margin
    text_draw.text((text_paste_x, text_paste_y), text_to_add, font=font, fill=(0,0,0,255)) # Màu đen
    
    return final_canvas