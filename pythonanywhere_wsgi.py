# ==============================================================================
# TextBridge - PythonAnywhere WSGI Configuration File
# ==============================================================================
# Instructions:
# 1. Open your PythonAnywhere Dashboard -> 'Web' tab.
# 2. Click on the 'WSGI configuration file' link:
#    (/var/www/<your_username>_pythonanywhere_com_wsgi.py)
# 3. Replace all its content with the code below and click 'Save'.
# ==============================================================================

import os
import sys

# Add your project directory to the sys.path
path = os.path.expanduser('~/TextBridge')
if path not in sys.path:
    sys.path.insert(0, path)

# Set the Django settings module
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# Load the WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
