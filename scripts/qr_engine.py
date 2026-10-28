#!/usr/bin/env python3
"""
QR Code Engine: Generates both high-resolution PNG image files
and compact terminal-friendly ASCII representations.
"""
import io
import os
import qrcode


def generate_qr(text: str, png_filepath: str = None, border: int = 2) -> str:
    """
    Generate QR code for a given text or URL.
    
    Args:
        text: The node URL or string to encode.
        png_filepath: Target filesystem path to save PNG file. If None, skip saving file.
        border: Border margin in blocks.
        
    Returns:
        ASCII string representation of the QR code suitable for CLI printing.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)

    # Save PNG if requested
    if png_filepath:
        os.makedirs(os.path.dirname(os.path.abspath(png_filepath)), exist_ok=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(png_filepath)

    # Generate ASCII
    f = io.StringIO()
    qr.print_ascii(out=f, invert=True)
    return f.getvalue()


if __name__ == "__main__":
    sample_text = "https://github.com/arifulcrypto/vps-deploy-skill"
    ascii_art = generate_qr(sample_text)
    print("Sample ASCII QR Code:")
    print(ascii_art)
