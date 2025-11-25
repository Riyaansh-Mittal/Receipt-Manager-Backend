# """
# Receipt Image Enhancer - Standalone Test Script
# Improves receipt images for better OCR accuracy

# Usage:
#     python enhance_receipt.py path/to/receipt.jpg

# Output:
#     Saves enhanced image to same folder as: receipt_enhanced.jpg
# """

# import cv2
# import numpy as np
# import sys
# from pathlib import Path


# def enhance_receipt_image(image_path: str) -> str:
#     """
#     Advanced receipt image enhancement for optimal OCR
    
#     Techniques applied:
#     1. Upscaling (if needed)
#     2. Grayscale conversion
#     3. Noise reduction (bilateral filter)
#     4. Adaptive histogram equalization (CLAHE)
#     5. Morphological operations
#     6. Adaptive thresholding
#     7. Background brightening + text darkening
    
#     Args:
#         image_path: Path to input image
        
#     Returns:
#         Path to enhanced image
#     """
    
#     print(f"\n{'='*60}")
#     print(f"Processing: {image_path}")
#     print(f"{'='*60}\n")
    
#     # Read image
#     img = cv2.imread(image_path)
#     if img is None:
#         raise ValueError(f"Could not read image: {image_path}")
    
#     original_shape = img.shape
#     print(f"✓ Original size: {img.shape[1]}x{img.shape[0]} pixels")
    
#     # Step 1: Upscale if image is too small
#     min_dimension = 1200
#     height, width = img.shape[:2]
    
#     if width < min_dimension or height < min_dimension:
#         scale_factor = min_dimension / min(width, height)
#         scale_factor = min(scale_factor, 3.0)  # Max 3x upscale
        
#         new_width = int(width * scale_factor)
#         new_height = int(height * scale_factor)
        
#         img = cv2.resize(
#             img, 
#             (new_width, new_height), 
#             interpolation=cv2.INTER_CUBIC
#         )
#         print(f"✓ Upscaled: {new_width}x{new_height} ({scale_factor:.2f}x)")
#     else:
#         print(f"✓ Size OK, no upscaling needed")
    
#     # Step 2: Convert to grayscale
#     if len(img.shape) == 3:
#         gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
#         print(f"✓ Converted to grayscale")
#     else:
#         gray = img
    
#     # Step 3: Denoise using bilateral filter (preserves edges!)
#     denoised = cv2.bilateralFilter(gray, 9, 75, 75)
#     print(f"✓ Noise removed (bilateral filter)")
    
#     # Step 4: Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
#     # This enhances local contrast
#     clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
#     contrast_enhanced = clahe.apply(denoised)
#     print(f"✓ Contrast enhanced (CLAHE)")
    
#     # Step 5: Morphological operations to remove small noise
#     kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
#     morph = cv2.morphologyEx(
#         contrast_enhanced, 
#         cv2.MORPH_CLOSE, 
#         kernel, 
#         iterations=1
#     )
#     print(f"✓ Morphological cleanup")
    
#     # Step 6: Adaptive thresholding - makes background bright, text dark
#     # This is KEY for OCR!
#     thresh = cv2.adaptiveThreshold(
#         morph,
#         255,
#         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY,
#         11,  # Block size
#         2    # C constant
#     )
#     print(f"✓ Adaptive thresholding applied")
    
#     # Step 7: Invert if text is lighter than background
#     # Calculate mean brightness
#     mean_brightness = np.mean(thresh)
#     if mean_brightness < 127:
#         thresh = cv2.bitwise_not(thresh)
#         print(f"✓ Inverted (text was light on dark)")
#     else:
#         print(f"✓ No inversion needed")
    
#     # Step 8: Final sharpening for crisp text edges
#     kernel_sharpen = np.array([
#         [-1, -1, -1],
#         [-1,  9, -1],
#         [-1, -1, -1]
#     ])
#     sharpened = cv2.filter2D(thresh, -1, kernel_sharpen)
#     print(f"✓ Sharpened for crisp edges")
    
#     # Save enhanced image
#     input_path = Path(image_path)
#     output_path = input_path.parent / f"{input_path.stem}_enhanced{input_path.suffix}"
    
#     cv2.imwrite(str(output_path), sharpened, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
#     print(f"\n{'='*60}")
#     print(f"✓ Enhanced image saved: {output_path}")
#     print(f"{'='*60}\n")
    
#     # Show comparison info
#     print("Comparison:")
#     print(f"  Original: {original_shape[1]}x{original_shape[0]}")
#     print(f"  Enhanced: {sharpened.shape[1]}x{sharpened.shape[0]}")
#     print(f"  Processing steps: 8")
    
#     return str(output_path)


# def enhance_receipt_aggressive(image_path: str) -> str:
#     """
#     More aggressive enhancement for very noisy/low quality receipts
#     """
    
#     print(f"\n{'='*60}")
#     print(f"AGGRESSIVE MODE: {image_path}")
#     print(f"{'='*60}\n")
    
#     # Read image
#     img = cv2.imread(image_path)
#     if img is None:
#         raise ValueError(f"Could not read image: {image_path}")
    
#     print(f"✓ Original size: {img.shape[1]}x{img.shape[0]}")
    
#     # Upscale aggressively
#     height, width = img.shape[:2]
#     scale_factor = 1800 / min(width, height)
#     scale_factor = min(scale_factor, 4.0)
    
#     new_width = int(width * scale_factor)
#     new_height = int(height * scale_factor)
    
#     img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
#     print(f"✓ Aggressive upscale: {new_width}x{new_height} ({scale_factor:.2f}x)")
    
#     # Grayscale
#     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    
#     # Heavy denoising
#     denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
#     print(f"✓ Heavy noise reduction")
    
#     # Aggressive CLAHE
#     clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
#     contrast = clahe.apply(denoised)
#     print(f"✓ Aggressive contrast enhancement")
    
#     # Morphological opening to remove noise
#     kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
#     morph = cv2.morphologyEx(contrast, cv2.MORPH_OPEN, kernel)
    
#     # Adaptive threshold with larger block size for noisy images
#     thresh = cv2.adaptiveThreshold(
#         morph, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY, 15, 3
#     )
    
#     # Invert if needed
#     if np.mean(thresh) < 127:
#         thresh = cv2.bitwise_not(thresh)
    
#     # Save
#     input_path = Path(image_path)
#     output_path = input_path.parent / f"{input_path.stem}_aggressive{input_path.suffix}"
#     cv2.imwrite(str(output_path), thresh, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
#     print(f"\n✓ Aggressive enhanced: {output_path}\n")
    
#     return str(output_path)


# if __name__ == "__main__":
#     if len(sys.argv) < 2:
#         print("Usage: python enhance_receipt.py <image_path> [--aggressive]")
#         print("\nExample:")
#         print("  python enhance_receipt.py receipt.jpg")
#         print("  python enhance_receipt.py noisy_receipt.jpg --aggressive")
#         sys.exit(1)
    
#     image_path = sys.argv[1]
    
#     if not Path(image_path).exists():
#         print(f"❌ Error: File not found: {image_path}")
#         sys.exit(1)
    
#     try:
#         if len(sys.argv) > 2 and sys.argv[2] == "--aggressive":
#             output = enhance_receipt_aggressive(image_path)
#         else:
#             output = enhance_receipt_image(image_path)
        
#         print("\n✅ Success! Test the enhanced image with OCR.")
#         print(f"   Original: {image_path}")
#         print(f"   Enhanced: {output}")
        
#     except Exception as e:
#         print(f"\n❌ Error: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         sys.exit(1)




"""
Receipt OCR with Perspective Transform
Detects receipt contours, applies perspective transform, and extracts text

Usage:
    python receipt_ocr_transform.py -i path/to/receipt.jpg

Output:
    Saves preprocessed image as: receipt_preprocessed.jpg
    Prints extracted text to console
"""

import argparse
import os
from pathlib import Path

import cv2
import imutils
import pytesseract
from imutils.perspective import four_point_transform


def process_receipt_image(image_path: str) -> tuple:
    """
    Process receipt image using perspective transform and OCR
    
    Args:
        image_path: Path to input receipt image
        
    Returns:
        tuple: (preprocessed_image_path, extracted_text)
    """
    
    print(f"\n{'='*60}")
    print(f"Processing: {image_path}")
    print(f"{'='*60}\n")
    
    # Check if image exists
    if not os.path.exists(image_path):
        raise Exception(f"The given image does not exist: {image_path}")
    
    # Load the image, resize and compute ratio
    img_orig = cv2.imread(image_path)
    if img_orig is None:
        raise ValueError(f"Could not read image: {image_path}")
    
    print(f"✓ Original size: {img_orig.shape[1]}x{img_orig.shape[0]} pixels")
    
    image = img_orig.copy()
    image = imutils.resize(image, width=500)
    ratio = img_orig.shape[1] / float(image.shape[1])
    print(f"✓ Resized for processing (ratio: {ratio:.2f})")
    
    # Convert to grayscale, blur, and apply edge detection
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 75, 200)
    print(f"✓ Edge detection completed")
    
    # Find contours and sort by size (largest first)
    cnts = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = imutils.grab_contours(cnts)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)
    print(f"✓ Found {len(cnts)} contours")
    
    # Find the receipt contour (4-point polygon)
    receiptCnt = None
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        
        if len(approx) == 4:
            receiptCnt = approx
            break
    
    # Handle case where receipt outline is not found
    if receiptCnt is None:
        print("⚠ Could not find 4-point receipt outline")
        print("⚠ Using original image for OCR")
        receipt = img_orig
    else:
        print(f"✓ Receipt outline detected (4 corners)")
        
        # Apply perspective transform to original image
        receipt = four_point_transform(img_orig, receiptCnt.reshape(4, 2) * ratio)
        print(f"✓ Perspective transform applied")
        print(f"  Transformed size: {receipt.shape[1]}x{receipt.shape[0]}")
    
    # Save preprocessed image
    input_path = Path(image_path)
    output_path = input_path.parent / f"{input_path.stem}_preprocessed{input_path.suffix}"
    cv2.imwrite(str(output_path), receipt, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"✓ Preprocessed image saved: {output_path}")
    
    # Apply OCR using pytesseract
    print(f"\n{'='*60}")
    print("Running OCR...")
    print(f"{'='*60}\n")
    
    # PSM 6 assumes uniform block of text
    options = "--psm 6"
    text = pytesseract.image_to_string(
        cv2.cvtColor(receipt, cv2.COLOR_BGR2RGB),
        config=options
    )
    
    return str(output_path), text


def main():
    parser = argparse.ArgumentParser(
        description="Receipt OCR with perspective transform"
    )
    parser.add_argument(
        "-i", "--image",
        type=str,
        required=True,
        help="path to input receipt image"
    )
    args = parser.parse_args()
    
    try:
        # Process the image
        preprocessed_path, extracted_text = process_receipt_image(args.image)
        
        # Print results
        print("[INFO] Raw OCR Output:")
        print("=" * 60)
        print(extracted_text)
        print("=" * 60)
        
        print(f"\n✅ Success!")
        print(f"   Original: {args.image}")
        print(f"   Preprocessed: {preprocessed_path}")
        print(f"   Text extracted: {len(extracted_text)} characters\n")
        
    except Exception as e:
        print(f"\n Error: {str(e)}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
