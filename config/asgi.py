"""
ASGI config for Newtonite Operations Hub project.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from django.core.asgi import get_asgi_application

base_dir = Path(__file__).resolve().parent.parent
load_dotenv(base_dir / ".env")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
