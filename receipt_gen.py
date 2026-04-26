from PIL import Image, ImageDraw, ImageFont
import os
import time

def generate_receipt(plate, v_type, entry_time, exit_time, duration, fee, img_path):
    # 1. Create a blank white canvas (Made it taller: 850px to fit the photo)
    width, height = 400, 850
    ticket = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(ticket)
    
    # 2. Draw a border
    draw.rectangle([10, 10, 390, height-10], outline=(0, 0, 0), width=2)
    
    # 3. Add Content
    try:
        font_header = ImageFont.truetype("arial.ttf", 30)
        font_body = ImageFont.truetype("arial.ttf", 18)
        font_price = ImageFont.truetype("arial.ttf", 25)
    except:
        font_header = font_body = font_price = ImageFont.load_default()

    draw.text((80, 40), "SMART PARKING", fill=(0, 0, 0), font=font_header)
    draw.text((120, 80), "OFFICIAL RECEIPT", fill=(0, 0, 0), font=font_body)
    draw.line((40, 110, 360, 110), fill=(0, 0, 0), width=1)

    y_pos = 140

    # --- NEW: PASTE THE CAR PHOTO ---
    if img_path and os.path.exists(img_path):
        try:
            car_img = Image.open(img_path)
            # Calculate aspect ratio to resize it neatly
            aspect_ratio = car_img.height / car_img.width
            new_width = 320
            new_height = int(new_width * aspect_ratio)
            car_img = car_img.resize((new_width, new_height))

            # Center the image horizontally on the 400px wide ticket
            x_offset = (width - new_width) // 2
            ticket.paste(car_img, (x_offset, y_pos))

            y_pos += new_height + 30 # Push the text down below the new image
        except Exception as e:
            print(f"Could not load image: {e}")
    else:
        draw.text((100, y_pos), "[ Image Not Available ]", fill=(100, 100, 100), font=font_body)
        y_pos += 50
    # --------------------------------

    # Details
    details = [
        f"Plate Number: {plate}",
        f"Vehicle Type: {v_type.upper()}",
        f"Entry: {entry_time}",
        f"Exit: {exit_time}",
        f"Duration: {duration:.2f} Minutes",
    ]

    for line in details:
        draw.text((40, y_pos), line, fill=(0, 0, 0), font=font_body)
        y_pos += 40

    draw.line((40, y_pos + 10, 360, y_pos + 10), fill=(0, 0, 0), width=2)
    draw.text((80, y_pos + 40), f"TOTAL PAID: ${fee:.2f}", fill=(0, 0, 0), font=font_price)
    draw.text((60, height - 60), "Thank you for parking with us!", fill=(0, 0, 0), font=font_body)

    # 4. Save the receipt
    os.makedirs("receipts", exist_ok=True)
    save_path = f"receipts/receipt_{plate}_{int(time.time())}.png"
    ticket.save(save_path)
    return save_path