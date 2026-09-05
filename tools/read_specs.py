from pathlib import Path
import fitz

out = Path("artifacts/specs")
out.mkdir(parents=True, exist_ok=True)
for stem in ("doc-1788536456", "doc-1788536476"):
    doc = fitz.open(Path("E:/") / (stem + ".pdf"))
    for i, page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).save(
            out / f"{stem}-{i + 1:02}.png"
        )
    print(stem, len(doc))
