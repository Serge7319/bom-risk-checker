"""PDF entitlement helpers for Cadivor Sprint 31.2."""
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color
from pypdf import PdfReader, PdfWriter

def add_student_edition_watermark(pdf_bytes: bytes, enabled: bool) -> bytes:
    if not enabled or not pdf_bytes: return pdf_bytes
    reader=PdfReader(BytesIO(pdf_bytes)); writer=PdfWriter()
    for page in reader.pages:
        width=float(page.mediabox.width); height=float(page.mediabox.height)
        overlay_buffer=BytesIO(); c=canvas.Canvas(overlay_buffer, pagesize=(width,height))
        c.saveState(); c.translate(width/2,height/2); c.rotate(35)
        c.setFillColor(Color(.15,.32,.62,alpha=.13)); c.setFont("Helvetica-Bold",42)
        c.drawCentredString(0,0,"STUDENT EDITION")
        c.restoreState(); c.setFillColor(Color(.25,.35,.5,alpha=.7)); c.setFont("Helvetica",8)
        c.drawCentredString(width/2,14,"Cadivor Student Edition — Academic use")
        c.save()
        overlay_buffer.seek(0); page.merge_page(PdfReader(overlay_buffer).pages[0]); writer.add_page(page)
    output=BytesIO(); writer.write(output); return output.getvalue()
