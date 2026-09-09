from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def make_contact_sheet(image_paths, out_path: str | Path, thumb_size=(320, 220), cols=3):
    paths = [Path(p) for p in image_paths]
    if not paths:
        return None
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols*thumb_size[0], rows*(thumb_size[1]+32)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(paths):
        img = Image.open(p).convert("RGB")
        img.thumbnail(thumb_size)
        x = (i % cols) * thumb_size[0]
        y = (i // cols) * (thumb_size[1]+32)
        sheet.paste(img, (x, y+24))
        draw.text((x+4,y+4), p.name[:44], fill=(0,0,0))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)
    return out_path
