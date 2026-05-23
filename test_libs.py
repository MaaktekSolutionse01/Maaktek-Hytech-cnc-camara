from PIL import Image
import numpy as np
import sys

try:
    print("Testing Pillow and Numpy...")
    img = Image.new('RGB', (100, 100), color = 'red')
    arr = np.array(img)
    print("Success: Pillow and Numpy are working!")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
