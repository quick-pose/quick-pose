# This file is only used if you use `make publish` or
# explicitly specify it as your config file.
import json
import os
import sys

sys.path.append(os.curdir)
from pelicanconf import *

SITEURL = "https://quick-pose.github.io/quick-pose"
RELATIVE_URLS = False

DELETE_OUTPUT_DIRECTORY = True

CATEGORIES = json.loads(os.environ['CATEGORIES'])
IMAGES_NUMBER_PER_CATEGORY = int(os.environ['IMAGES_NUMBER_PER_CATEGORY'])

YADISK_LISTINGS_PATH = os.environ['YADISK_DEST_PATH']
YANDEX_CLIENT_ID = os.environ['YANDEX_CLIENT_ID']

OPENAI_SYSTEM_PROMPT = os.environ['OPENAI_SYSTEM_PROMPT']
OPENAI_USER_PROMPT = os.environ['OPENAI_USER_PROMPT']
OPENAI_MODEL_NAME = os.environ['OPENAI_MODEL_NAME']
