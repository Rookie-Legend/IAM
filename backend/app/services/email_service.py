import subprocess
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), "..", "templates")
LOGO_PATH = os.path.join(TEMPLATES_PATH, "logo.png")

async def send_email(email: str, subject: str, template_name: str, replacements: dict = None):
    template_path = os.path.join(TEMPLATES_PATH, template_name)
    replacements = replacements or {}

    with open(template_path, "r") as f:
        html_content = f.read()
        for key, value in replacements.items():
            html_content = html_content.replace(f"{{{{{key}}}}}", value)

    with open(LOGO_PATH, "rb") as f:
        logo_data = f.read()

    msg = MIMEMultipart("related")
    msg["From"] = "CorpOD <Corpod.sec@gmail.com>"
    msg["To"] = email
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html"))

    logo_image = MIMEImage(logo_data, name="logo.png")
    logo_image.add_header("Content-ID", "<logo>")
    msg.attach(logo_image)

    try:
        process = subprocess.Popen(
            ["msmtp", "-C", "./msmtprc", "-t"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(input=msg.as_bytes())
        if process.returncode != 0:
            print(f"msmtp error: {stderr.decode()}")
    except Exception as e:
        print(f"Failed to send email: {e}")