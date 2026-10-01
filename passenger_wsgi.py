import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_ROOT)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from a2wsgi import ASGIMiddleware

from api import app as fastapi_app

application = ASGIMiddleware(fastapi_app)