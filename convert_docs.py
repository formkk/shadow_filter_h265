
import os
import markdown
import subprocess
from glob import glob

# CSS ensuring Chinese fonts are used
# We use simfang.ttf which is a standard TTF font
font_path = "/usr/share/fonts/simfang.ttf"

css_content = f"""
@font-face {{
    font-family: "FangSong";
    src: url("{font_path}");
}}

@page {{
    size: A4;
    margin: 2.5cm;
    margin-bottom: 3cm;
}}

body {{
    font-family: "FangSong", sans-serif;
    font-size: 12pt;
    line-height: 1.6;
    word-break: break-all;
    word-wrap: break-word;
}}

p {{
    margin-bottom: 10px;
    text-align: left;
}}

li {{
    margin-bottom: 5px;
    text-align: left;
}}

h1, h2, h3, h4, h5, h6 {{
    font-family: "FangSong", sans-serif;
    font-weight: bold;
}}

code, pre {{
    font-family: "FangSong", monospace;
    background-color: #f5f5f5;
    padding: 2px 4px;
}}

table {{
    border: 1px solid #000;
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1em;
}}
td, th {{
    border: 1px solid #000;
    padding: 8px;
    text-align: left;
}}
th {{
    background-color: #f2f2f2;
    font-weight: bold;
}}
"""

docs_dir = "/home/jiangfeng/shadow_filter_h265/docs"
pdf_dir = os.path.join(docs_dir, "pdf")

os.makedirs(pdf_dir, exist_ok=True)

md_files = glob(os.path.join(docs_dir, "*.md"))

def convert_html_to_pdf(source_html, output_filename):
    # Save HTML temporarily
    html_filename = output_filename.replace(".pdf", ".html")
    with open(html_filename, "w", encoding="utf-8") as f:
        f.write(source_html)
        
    # Use wkhtmltopdf instead of xhtml2pdf
    try:
        cmd = [
            'wkhtmltopdf',
            '--encoding', 'utf-8',
            '--page-size', 'A4',
            '--margin-top', '25mm',
            '--margin-bottom', '30mm',
            '--margin-left', '25mm',
            '--margin-right', '25mm',
            '--enable-local-file-access',
            html_filename,
            output_filename
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error converting {output_filename}: {result.stderr}")
            return True
        return False
    except Exception as e:
        print(f"Exception converting {output_filename}: {str(e)}")
        return True
    finally:
        # Cleanup HTML file if needed, but keeping it for now as per previous debug logic
        pass

for md_file in md_files:
    filename = os.path.basename(md_file)
    pdf_filename = os.path.splitext(filename)[0] + ".pdf"
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    
    print(f"Converting {filename} to {pdf_filename}...")
    
    with open(md_file, "r", encoding="utf-8") as f:
        text = f.read()
        
    # Convert Markdown to HTML
    html_body = markdown.markdown(text, extensions=['tables', 'fenced_code', 'sane_lists'])
    
    # Wrap in HTML structure with embedded CSS
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>{filename}</title>
        <style>
        {css_content}
        </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """
    
    # Generate PDF
    if convert_html_to_pdf(html_content, pdf_path):
        print(f"Error converting {filename}")
    
print("All done!")
