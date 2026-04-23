import os
import sys

project_home = '/home/123kfchem/SELLSENSE-AI'
if project_home not in sys.path:
    sys.path.append(project_home)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sellsense_ai.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
