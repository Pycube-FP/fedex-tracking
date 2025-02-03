from PIL import Image
import os

def create_icon(input_path, output_path, size):
    # Open the original image
    with Image.open(input_path) as img:
        # Convert to RGBA if not already
        img = img.convert('RGBA')
        
        # Create a white background image
        background = Image.new('RGBA', img.size, (255, 255, 255, 255))
        
        # Paste the logo onto the white background
        background.paste(img, (0, 0), img)
        
        # Resize the image
        resized_img = background.resize((size, size), Image.Resampling.LANCZOS)
        
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Save the resized image
        resized_img.save(output_path, 'PNG')
        print(f"Generated {output_path}")

def main():
    # Input logo path
    input_path = 'static/pycube-logo.png'
    
    # Define required sizes
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]
    
    # Generate icons for each size
    for size in sizes:
        output_path = f'static/icons/icon-{size}x{size}.png'
        create_icon(input_path, output_path, size)

if __name__ == '__main__':
    main() 